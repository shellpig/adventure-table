from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
# All Postgres tests reset the one shared database: keep them on a single xdist worker.
pytestmark = [
    pytest.mark.xdist_group("postgres"),
    pytest.mark.skipif(
        not POSTGRES_URL,
        reason="P4_POSTGRES_URL is only supplied by the P4 PostgreSQL job",
    ),
]
SERVER_ROOT = Path(__file__).resolve().parents[1]
P5A_PARENT = "0034_m06b_event_actor_stamp"

BATTLE_MAP_TABLES = (
    "battle_maps",
    "battle_map_walls",
    "battle_map_doors",
    "battle_map_terrain",
    "battle_map_drawings",
)


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


def _table_names() -> set[str]:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.connect() as connection:
            return set(
                connection.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                    )
                ).scalars()
            )
    finally:
        engine.dispose()


def _seed_p6_snapshot(connection) -> dict[str, object]:
    """Minimal P6 Adventure/Runtime + P4 combat rows at 0034."""
    room_id = uuid4()
    campaign_id = uuid4()
    seat_id = uuid4()
    session_id = uuid4()
    quick_combat_id = uuid4()
    adventure_id = uuid4()
    connection.execute(
        text(
            "INSERT INTO rooms (id, code, name, password_salt, password_hash, owner_key_hash, dm_key_hash, "
            "created_at, updated_at) VALUES (:room_id, :code, 'p5a room', :salt, :hash, :owner, :dm, now(), now())"
        ),
        {"room_id": room_id, "code": str(room_id)[:10], "salt": bytes(32), "hash": bytes(64),
         "owner": bytes(32), "dm": bytes(32)},
    )
    connection.execute(
        text(
            "INSERT INTO campaigns (id, room_id, name, ruleset, status) "
            "VALUES (:campaign_id, :room_id, 'p5a campaign', 'dnd5e-2014', 'active')"
        ),
        {"campaign_id": campaign_id, "room_id": room_id},
    )
    connection.execute(
        text(
            "INSERT INTO campaign_seats (id, campaign_id, role, controller_kind) "
            "VALUES (:seat_id, :campaign_id, 'dm', 'none')"
        ),
        {"seat_id": seat_id, "campaign_id": campaign_id},
    )
    connection.execute(
        text(
            "INSERT INTO sessions (id, campaign_id, status, dm_seat_id, dm_controller_kind, started_at) "
            "VALUES (:session_id, :campaign_id, 'active', :seat_id, 'none', now())"
        ),
        {"session_id": session_id, "campaign_id": campaign_id, "seat_id": seat_id},
    )
    connection.execute(
        text(
            "INSERT INTO combats (id, campaign_id, started_session_id, mode, status) "
            "VALUES (:combat_id, :campaign_id, :session_id, 'quick', 'ended')"
        ),
        {"combat_id": quick_combat_id, "campaign_id": campaign_id, "session_id": session_id},
    )
    connection.execute(
        text(
            "INSERT INTO adventure_definitions (id, room_id, name) "
            "VALUES (:adventure_id, :room_id, 'p5a adventure')"
        ),
        {"adventure_id": adventure_id, "room_id": room_id},
    )
    connection.execute(
        text(
            "INSERT INTO campaign_runtime_context (campaign_id, current_situation) "
            "VALUES (:campaign_id, 'p5a situation')"
        ),
        {"campaign_id": campaign_id},
    )
    return {
        "campaign_id": campaign_id,
        "session_id": session_id,
        "quick_combat_id": quick_combat_id,
        "adventure_id": adventure_id,
    }


def test_p5a_postgres_migration() -> None:
    _reset()
    config = _config()
    command.upgrade(config, P5A_PARENT)
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.begin() as connection:
            seeded = _seed_p6_snapshot(connection)
            campaign_id = seeded["campaign_id"]
            session_id = seeded["session_id"]

        # At 0034 the old quick-only constraint still rejects tactical.
        with engine.begin() as connection:
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO combats (id, campaign_id, started_session_id, mode, status) "
                        "VALUES (:combat_id, :campaign_id, :session_id, 'tactical', 'ended')"
                    ),
                    {"combat_id": uuid4(), "campaign_id": campaign_id, "session_id": session_id},
                )

        command.upgrade(config, "heads")
        assert BATTLE_MAP_TABLES[0] in _table_names()

        with engine.begin() as connection:
            # P6 Adventure/Runtime rows survive the upgrade untouched.
            row = connection.execute(
                text("SELECT name FROM adventure_definitions WHERE id = :adventure_id"),
                {"adventure_id": seeded["adventure_id"]},
            ).one()
            assert row[0] == "p5a adventure"
            row = connection.execute(
                text(
                    "SELECT current_situation FROM campaign_runtime_context WHERE campaign_id = :campaign_id"
                ),
                {"campaign_id": campaign_id},
            ).one()
            assert row[0] == "p5a situation"
            # The pre-upgrade quick combat row is unchanged.
            row = connection.execute(
                text("SELECT mode FROM combats WHERE id = :combat_id"),
                {"combat_id": seeded["quick_combat_id"]},
            ).one()
            assert row[0] == "quick"

            # Quick inserts still work; tactical inserts are now accepted.
            quick_id = uuid4()
            tactical_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO combats (id, campaign_id, started_session_id, mode, status) "
                    "VALUES (:combat_id, :campaign_id, :session_id, 'quick', 'ended')"
                ),
                {"combat_id": quick_id, "campaign_id": campaign_id, "session_id": session_id},
            )
            connection.execute(
                text(
                    "INSERT INTO combats (id, campaign_id, started_session_id, mode, status) "
                    "VALUES (:combat_id, :campaign_id, :session_id, 'tactical', 'ended')"
                ),
                {"combat_id": tactical_id, "campaign_id": campaign_id, "session_id": session_id},
            )

        # Downgrade refuses while a tactical row exists and must not touch data.
        with pytest.raises(RuntimeError):
            command.downgrade(config, P5A_PARENT)
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT COUNT(*) FROM combats WHERE mode = 'tactical'")
            ).scalar() == 1

        # After removing tactical rows the downgrade lands back on 0034 cleanly.
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM combats WHERE mode = 'tactical'"))
        command.downgrade(config, P5A_PARENT)
        names = _table_names()
        for table in BATTLE_MAP_TABLES:
            assert table not in names
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT COUNT(*) FROM combats WHERE mode = 'quick'")
            ).scalar() == 2
            row = connection.execute(
                text("SELECT name FROM adventure_definitions WHERE id = :adventure_id"),
                {"adventure_id": seeded["adventure_id"]},
            ).one()
            assert row[0] == "p5a adventure"
    finally:
        engine.dispose()


BOARD_TABLES = ("combat_boards", "combat_board_doors", "combat_positions")


def test_p5a_postgres_board_tables_migration() -> None:
    """0037 creates the combat board tables; downgrade drops them cleanly."""
    _reset()
    config = _config()
    command.upgrade(config, P5A_PARENT)
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.begin() as connection:
            seeded = _seed_p6_snapshot(connection)
            campaign_id = seeded["campaign_id"]
            session_id = seeded["session_id"]

        command.upgrade(config, "heads")
        names = _table_names()
        for table in BOARD_TABLES:
            assert table in names

        with engine.begin() as connection:
            combat_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO combats (id, campaign_id, started_session_id, mode, status) "
                    "VALUES (:combat_id, :campaign_id, :session_id, 'tactical', 'initiative_pending')"
                ),
                {"combat_id": combat_id, "campaign_id": campaign_id, "session_id": session_id},
            )
            # Minimal frozen board row.
            connection.execute(
                text(
                    "INSERT INTO combat_boards (combat_id, width_cells, height_cells, baseline, "
                    "source_battle_map_revision, runtime_revision, created_at) "
                    "VALUES (:combat_id, 20, 15, '{}', 1, 1, now())"
                ),
                {"combat_id": combat_id},
            )
            door_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO combat_board_doors (combat_id, door_id, state, revealed, created_at) "
                    "VALUES (:combat_id, :door_id, 'closed', false, now())"
                ),
                {"combat_id": combat_id, "door_id": door_id},
            )
            # Position rows need a combat entry; create a minimal monster entry.
            monster_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO monster_instances (id, campaign_id, name, rules_snapshot, current_hp, "
                    "conditions, effects, combat_status, visibility, resources) "
                    "VALUES (:monster_id, :campaign_id, 'Goblin', '{}', 7, '[]', '[]', 'active', 'public', '{}')"
                ),
                {"monster_id": monster_id, "campaign_id": campaign_id},
            )
            entry_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO combat_entries (id, combat_id, subject_kind, monster_instance_id, "
                    "display_name, status, ready_state, pending_reaction_state) "
                    "VALUES (:entry_id, :combat_id, 'monster', :monster_id, 'Goblin', 'active', '{}', '{}')"
                ),
                {"entry_id": entry_id, "combat_id": combat_id, "monster_id": monster_id},
            )
            connection.execute(
                text(
                    "INSERT INTO combat_positions (combat_entry_id, combat_id, anchor_x, anchor_y, "
                    "footprint_width, footprint_height, revision) "
                    "VALUES (:entry_id, :combat_id, 3, 4, 1, 1, 1)"
                ),
                {"entry_id": entry_id, "combat_id": combat_id},
            )
            # Cascade: deleting the combat removes board, doors, and positions.
            connection.execute(
                text("DELETE FROM combats WHERE id = :combat_id"),
                {"combat_id": combat_id},
            )
            for table in BOARD_TABLES:
                count = connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                assert count == 0, table

        # Downgrade back to 0034 drops the board tables with the battle maps.
        command.downgrade(config, P5A_PARENT)
        names = _table_names()
        for table in BOARD_TABLES + BATTLE_MAP_TABLES:
            assert table not in names
    finally:
        engine.dispose()
