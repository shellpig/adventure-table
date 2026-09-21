from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.migration_support import migration_heads
from tests.test_p4f_postgres_migration import _seed_room_and_campaign


POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
pytestmark = [
    pytest.mark.xdist_group("postgres"),
    pytest.mark.skipif(
        not POSTGRES_URL,
        reason="P4_POSTGRES_URL is only supplied by the P4 PostgreSQL job",
    ),
]
SERVER_ROOT = Path(__file__).resolve().parents[1]
P6B_PARENT = "0031_p6a_room_assets_adventures"
P6B_TABLES = {
    "campaign_world_entries",
    "campaign_world_entry_characters",
    "campaign_adventure_overrides",
    "campaign_runtime_context",
    "campaign_world_mutations",
}


def _config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    config.attributes["target_database_url"] = POSTGRES_URL
    return config


def _reset() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def _revision_set() -> set[str]:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.connect() as connection:
            return set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    finally:
        engine.dispose()


def _seed_adventure_and_entry(connection, *, room_id, adventure_id=None, entry_id=None):
    adv_id = adventure_id or uuid4()
    ent_id = entry_id or uuid4()
    connection.execute(
        text(
            "INSERT INTO adventure_definitions (id, room_id, name, status) "
            "VALUES (:id, :room_id, 'Test Adventure', 'finalized')"
        ),
        {"id": adv_id, "room_id": room_id},
    )
    connection.execute(
        text(
            "INSERT INTO adventure_entries (id, adventure_id, kind, title, data_json) "
            "VALUES (:id, :adv_id, 'scene', 'Scene 1', '{}')"
        ),
        {"id": ent_id, "adv_id": adv_id},
    )
    return adv_id, ent_id


def test_p6b_real_postgres_upgrade_and_downgrade_from_p6a_parent() -> None:
    _reset()
    command.upgrade(_config(), P6B_PARENT)
    assert P6B_PARENT in _revision_set()

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        table_names = set(inspect(engine).get_table_names())
        assert P6B_TABLES.isdisjoint(table_names)

        command.upgrade(_config(), "heads")
        assert _revision_set() == set(migration_heads(_config()).values())

        table_names = set(inspect(engine).get_table_names())
        assert P6B_TABLES.issubset(table_names)

        command.downgrade(_config(), P6B_PARENT)
        assert P6B_PARENT in _revision_set()

        table_names = set(inspect(engine).get_table_names())
        assert P6B_TABLES.isdisjoint(table_names)

        command.upgrade(_config(), "heads")
        table_names = set(inspect(engine).get_table_names())
        assert P6B_TABLES.issubset(table_names)
    finally:
        engine.dispose()


def test_p6b_schema_structure_and_constraints() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() == set(migration_heads(_config()).values())

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        inspector = inspect(engine)

        # 1. campaign_world_entries
        cols_cwe = {c["name"]: c for c in inspector.get_columns("campaign_world_entries")}
        assert {"id", "campaign_id", "kind", "title", "body", "state_json", "dm_notes",
                "visibility", "needs_review", "source_adventure_entry_id", "provenance_json",
                "revision", "created_by_actor_kind", "created_by_actor_id", "created_at",
                "updated_at", "archived_at"}.issubset(cols_cwe.keys())
        assert not cols_cwe["state_json"]["nullable"]
        assert not cols_cwe["revision"]["nullable"]
        assert cols_cwe["archived_at"]["nullable"]

        # 2. campaign_world_entry_characters
        pk_cwec = inspector.get_pk_constraint("campaign_world_entry_characters")
        assert set(pk_cwec["constrained_columns"]) == {"world_entry_id", "character_id"}

        # 3. campaign_adventure_overrides
        uq_cao = inspector.get_unique_constraints("campaign_adventure_overrides")
        assert any(set(u["column_names"]) == {"campaign_id", "adventure_entry_id"} for u in uq_cao)

        # 4. campaign_runtime_context
        pk_crc = inspector.get_pk_constraint("campaign_runtime_context")
        assert pk_crc["constrained_columns"] == ["campaign_id"]

        # 5. campaign_world_mutations
        uq_cwm = inspector.get_unique_constraints("campaign_world_mutations")
        assert any(set(u["column_names"]) == {"campaign_id", "idempotency_key"} for u in uq_cwm)
    finally:
        engine.dispose()


def test_p6b_world_entries_kind_visibility_and_revision_checks() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() == set(migration_heads(_config()).values())

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id = uuid4()
        campaign_id = uuid4()
        with engine.begin() as connection:
            _seed_room_and_campaign(connection, room_id=room_id, campaign_id=campaign_id)
            # Valid insert
            connection.execute(
                text(
                    "INSERT INTO campaign_world_entries ("
                    "id, campaign_id, kind, title, state_json, visibility, revision, created_by_actor_kind"
                    ") VALUES ("
                    ":id, :campaign_id, 'npc', 'Old Bart', '{\"name\": \"Bart\"}', 'public', 1, 'human'"
                    ")"
                ),
                {"id": uuid4(), "campaign_id": campaign_id},
            )

        # Invalid kind
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO campaign_world_entries ("
                        "id, campaign_id, kind, state_json, visibility, revision, created_by_actor_kind"
                        ") VALUES ("
                        ":id, :campaign_id, 'invalid_kind', '{}', 'public', 1, 'human'"
                        ")"
                    ),
                    {"id": uuid4(), "campaign_id": campaign_id},
                )

        # Invalid visibility
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO campaign_world_entries ("
                        "id, campaign_id, kind, state_json, visibility, revision, created_by_actor_kind"
                        ") VALUES ("
                        ":id, :campaign_id, 'fact', '{}', 'private', 1, 'human'"
                        ")"
                    ),
                    {"id": uuid4(), "campaign_id": campaign_id},
                )

        # Non-positive revision
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO campaign_world_entries ("
                        "id, campaign_id, kind, state_json, visibility, revision, created_by_actor_kind"
                        ") VALUES ("
                        ":id, :campaign_id, 'fact', '{}', 'public', 0, 'human'"
                        ")"
                    ),
                    {"id": uuid4(), "campaign_id": campaign_id},
                )
    finally:
        engine.dispose()


def test_p6b_adventure_overrides_uniqueness_and_detach_independence() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() == set(migration_heads(_config()).values())

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id = uuid4()
        campaign_id = uuid4()
        with engine.begin() as connection:
            _seed_room_and_campaign(connection, room_id=room_id, campaign_id=campaign_id)
            adv_id, ent_id = _seed_adventure_and_entry(connection, room_id=room_id)
            connection.execute(
                text(
                    "INSERT INTO campaign_adventure_links (campaign_id, adventure_id, sort_order) "
                    "VALUES (:campaign_id, :adv_id, 0)"
                ),
                {"campaign_id": campaign_id, "adv_id": adv_id},
            )
            # Insert first override -> succeeds
            connection.execute(
                text(
                    "INSERT INTO campaign_adventure_overrides ("
                    "id, campaign_id, adventure_entry_id, state_json, revision"
                    ") VALUES ("
                    ":id, :campaign_id, :ent_id, '{\"hostile\": true}', 1"
                    ")"
                ),
                {"id": uuid4(), "campaign_id": campaign_id, "ent_id": ent_id},
            )

        # Second override for same campaign + adventure_entry -> violates unique constraint
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO campaign_adventure_overrides ("
                        "id, campaign_id, adventure_entry_id, state_json, revision"
                        ") VALUES ("
                        ":id, :campaign_id, :ent_id, '{\"hostile\": false}', 1"
                        ")"
                    ),
                    {"id": uuid4(), "campaign_id": campaign_id, "ent_id": ent_id},
                )

        # Detach adventure link: override and adventure_entry survive
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM campaign_adventure_links WHERE campaign_id = :campaign_id"),
                {"campaign_id": campaign_id},
            )
            override_count = connection.execute(
                text("SELECT count(*) FROM campaign_adventure_overrides WHERE campaign_id = :campaign_id"),
                {"campaign_id": campaign_id},
            ).scalar()
            assert override_count == 1
    finally:
        engine.dispose()


def test_p6b_runtime_context_single_scene_check() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() == set(migration_heads(_config()).values())

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id = uuid4()
        campaign_id = uuid4()
        with engine.begin() as connection:
            _seed_room_and_campaign(connection, room_id=room_id, campaign_id=campaign_id)
            adv_id, adv_entry_id = _seed_adventure_and_entry(connection, room_id=room_id)
            rt_entry_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO campaign_world_entries ("
                    "id, campaign_id, kind, title, state_json, visibility, revision, created_by_actor_kind"
                    ") VALUES ("
                    ":id, :campaign_id, 'scene', 'Town Square', '{}', 'public', 1, 'human'"
                    ")"
                ),
                {"id": rt_entry_id, "campaign_id": campaign_id},
            )

            # Valid: current_adventure_scene_entry_id only
            connection.execute(
                text(
                    "INSERT INTO campaign_runtime_context ("
                    "campaign_id, current_adventure_scene_entry_id, current_runtime_scene_entry_id, revision"
                    ") VALUES (:campaign_id, :adv_entry_id, NULL, 1)"
                ),
                {"campaign_id": campaign_id, "adv_entry_id": adv_entry_id},
            )

            # Valid: switch to current_runtime_scene_entry_id only
            connection.execute(
                text(
                    "UPDATE campaign_runtime_context SET "
                    "current_adventure_scene_entry_id = NULL, current_runtime_scene_entry_id = :rt_entry_id "
                    "WHERE campaign_id = :campaign_id"
                ),
                {"campaign_id": campaign_id, "rt_entry_id": rt_entry_id},
            )

            # Valid: both NULL
            connection.execute(
                text(
                    "UPDATE campaign_runtime_context SET "
                    "current_adventure_scene_entry_id = NULL, current_runtime_scene_entry_id = NULL "
                    "WHERE campaign_id = :campaign_id"
                ),
                {"campaign_id": campaign_id},
            )

        # Invalid: both non-null
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE campaign_runtime_context SET "
                        "current_adventure_scene_entry_id = :adv_entry_id, "
                        "current_runtime_scene_entry_id = :rt_entry_id "
                        "WHERE campaign_id = :campaign_id"
                    ),
                    {
                        "campaign_id": campaign_id,
                        "adv_entry_id": adv_entry_id,
                        "rt_entry_id": rt_entry_id,
                    },
                )
    finally:
        engine.dispose()


def test_p6b_world_mutations_idempotency_unique() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() == set(migration_heads(_config()).values())

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id = uuid4()
        campaign_id1 = uuid4()
        campaign_id2 = uuid4()
        with engine.begin() as connection:
            _seed_room_and_campaign(connection, room_id=room_id, campaign_id=campaign_id1)
            connection.execute(
                text(
                    "INSERT INTO campaigns (id, room_id, name, ruleset, status) "
                    "VALUES (:id, :room_id, 'Campaign 2', 'dnd5e-2014', 'active')"
                ),
                {"id": campaign_id2, "room_id": room_id},
            )
            # Insert mutation for campaign 1
            connection.execute(
                text(
                    "INSERT INTO campaign_world_mutations ("
                    "id, campaign_id, idempotency_key, action_kind, command_payload, result_payload, created_by_actor_kind"
                    ") VALUES ("
                    ":id, :campaign_id, 'idem-1', 'create_entry', '{}', '{\"success\": true}', 'human'"
                    ")"
                ),
                {"id": uuid4(), "campaign_id": campaign_id1},
            )
            # Same idempotency_key for different campaign -> succeeds
            connection.execute(
                text(
                    "INSERT INTO campaign_world_mutations ("
                    "id, campaign_id, idempotency_key, action_kind, command_payload, result_payload, created_by_actor_kind"
                    ") VALUES ("
                    ":id, :campaign_id, 'idem-1', 'create_entry', '{}', '{\"success\": true}', 'human'"
                    ")"
                ),
                {"id": uuid4(), "campaign_id": campaign_id2},
            )

        # Same idempotency_key for same campaign -> violates unique constraint
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO campaign_world_mutations ("
                        "id, campaign_id, idempotency_key, action_kind, command_payload, result_payload, created_by_actor_kind"
                        ") VALUES ("
                        ":id, :campaign_id, 'idem-1', 'create_entry', '{}', '{\"success\": true}', 'human'"
                        ")"
                    ),
                    {"id": uuid4(), "campaign_id": campaign_id1},
                )
    finally:
        engine.dispose()


def test_p6b_fk_cascade_and_set_null_behavior() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() == set(migration_heads(_config()).values())

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id = uuid4()
        campaign_id = uuid4()
        char_id = uuid4()
        with engine.begin() as connection:
            _seed_room_and_campaign(connection, room_id=room_id, campaign_id=campaign_id)
            adv_id, adv_entry_id = _seed_adventure_and_entry(connection, room_id=room_id)
            connection.execute(
                text(
                    "INSERT INTO characters (id, name, ruleset) "
                    "VALUES (:id, 'Hero', 'dnd5e-2014')"
                ),
                {"id": char_id},
            )
            connection.execute(
                text(
                    "INSERT INTO room_characters (room_id, character_id) "
                    "VALUES (:room_id, :char_id)"
                ),
                {"room_id": room_id, "char_id": char_id},
            )

            world_entry_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO campaign_world_entries ("
                    "id, campaign_id, kind, title, state_json, visibility, source_adventure_entry_id, revision, created_by_actor_kind"
                    ") VALUES ("
                    ":id, :campaign_id, 'scene', 'Camp', '{}', 'public', :adv_entry_id, 1, 'human'"
                    ")"
                ),
                {
                    "id": world_entry_id,
                    "campaign_id": campaign_id,
                    "adv_entry_id": adv_entry_id,
                },
            )

            connection.execute(
                text(
                    "INSERT INTO campaign_world_entry_characters (world_entry_id, character_id) "
                    "VALUES (:world_entry_id, :char_id)"
                ),
                {"world_entry_id": world_entry_id, "char_id": char_id},
            )

            connection.execute(
                text(
                    "INSERT INTO campaign_runtime_context ("
                    "campaign_id, current_adventure_scene_entry_id, current_runtime_scene_entry_id, revision"
                    ") VALUES (:campaign_id, :adv_entry_id, NULL, 1)"
                ),
                {"campaign_id": campaign_id, "adv_entry_id": adv_entry_id},
            )

            # Deleting adventure_entry sets NULL in source_adventure_entry_id and current_adventure_scene_entry_id
            connection.execute(
                text("DELETE FROM adventure_entries WHERE id = :id"),
                {"id": adv_entry_id},
            )

            # Check that world entry still exists and source_adventure_entry_id is now NULL
            row = connection.execute(
                text("SELECT source_adventure_entry_id FROM campaign_world_entries WHERE id = :id"),
                {"id": world_entry_id},
            ).mappings().one()
            assert row["source_adventure_entry_id"] is None

            # Check that campaign_runtime_context still exists and current_adventure_scene_entry_id is now NULL
            ctx_row = connection.execute(
                text("SELECT current_adventure_scene_entry_id FROM campaign_runtime_context WHERE campaign_id = :cid"),
                {"cid": campaign_id},
            ).mappings().one()
            assert ctx_row["current_adventure_scene_entry_id"] is None

            # Deleting campaign cascades to all 5 tables
            connection.execute(
                text("DELETE FROM campaigns WHERE id = :id"),
                {"id": campaign_id},
            )
            assert connection.execute(text("SELECT count(*) FROM campaign_world_entries")).scalar() == 0
            assert connection.execute(text("SELECT count(*) FROM campaign_world_entry_characters")).scalar() == 0
            assert connection.execute(text("SELECT count(*) FROM campaign_adventure_overrides")).scalar() == 0
            assert connection.execute(text("SELECT count(*) FROM campaign_runtime_context")).scalar() == 0
            assert connection.execute(text("SELECT count(*) FROM campaign_world_mutations")).scalar() == 0
    finally:
        engine.dispose()
