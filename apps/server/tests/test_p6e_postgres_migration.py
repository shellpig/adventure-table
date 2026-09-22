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
P6E_PARENT = "0032_p6b_campaign_world_runtime"
P6E_TABLES = {
    "adventure_imports",
    "adventure_import_sources",
    "adventure_import_drafts",
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
            return set(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
            )
    finally:
        engine.dispose()


def test_p6e_real_postgres_upgrade_and_downgrade_from_p6b_parent() -> None:
    _reset()
    command.upgrade(_config(), P6E_PARENT)
    assert P6E_PARENT in _revision_set()

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        table_names = set(inspect(engine).get_table_names())
        assert P6E_TABLES.isdisjoint(table_names)

        command.upgrade(_config(), "heads")
        assert _revision_set() == set(migration_heads(_config()).values())

        table_names = set(inspect(engine).get_table_names())
        assert P6E_TABLES.issubset(table_names)

        command.downgrade(_config(), P6E_PARENT)
        assert P6E_PARENT in _revision_set()

        table_names = set(inspect(engine).get_table_names())
        assert P6E_TABLES.isdisjoint(table_names)

        command.upgrade(_config(), "heads")
        table_names = set(inspect(engine).get_table_names())
        assert P6E_TABLES.issubset(table_names)
    finally:
        engine.dispose()


def test_p6e_schema_structure_and_constraints() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() == set(migration_heads(_config()).values())

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        inspector = inspect(engine)

        # 1. adventure_imports
        cols_ai = {c["name"]: c for c in inspector.get_columns("adventure_imports")}
        assert {"id", "room_id", "name", "status", "target_adventure_id", "revision", "created_at", "updated_at"}.issubset(cols_ai.keys())
        assert not cols_ai["name"]["nullable"]
        assert not cols_ai["status"]["nullable"]
        assert cols_ai["target_adventure_id"]["nullable"]
        assert not cols_ai["revision"]["nullable"]

        # 2. adventure_import_sources
        cols_ais = {c["name"]: c for c in inspector.get_columns("adventure_import_sources")}
        assert {"id", "import_id", "asset_id", "source_kind", "source_url", "normalized_text", "metadata_json", "sha256", "created_at"}.issubset(cols_ais.keys())
        assert cols_ais["asset_id"]["nullable"]
        assert cols_ais["source_url"]["nullable"]
        assert not cols_ais["normalized_text"]["nullable"]
        assert not cols_ais["metadata_json"]["nullable"]
        assert not cols_ais["sha256"]["nullable"]
        uq_ais = inspector.get_unique_constraints("adventure_import_sources")
        assert any(set(u["column_names"]) == {"import_id", "sha256"} for u in uq_ais)

        # 3. adventure_import_drafts
        cols_aid = {c["name"]: c for c in inspector.get_columns("adventure_import_drafts")}
        assert {"import_id", "draft_json", "warnings_json", "revision", "updated_at"}.issubset(cols_aid.keys())
        pk_aid = inspector.get_pk_constraint("adventure_import_drafts")
        assert pk_aid["constrained_columns"] == ["import_id"]
    finally:
        engine.dispose()


def test_p6e_imports_status_and_sources_kind_checks() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() == set(migration_heads(_config()).values())

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id = uuid4()
        import_id = uuid4()
        with engine.begin() as connection:
            _seed_room_and_campaign(connection, room_id=room_id, campaign_id=uuid4())
            # Valid import insert
            connection.execute(
                text(
                    "INSERT INTO adventure_imports (id, room_id, name, status, revision) "
                    "VALUES (:id, :room_id, 'Valid Import', 'source', 0)"
                ),
                {"id": import_id, "room_id": room_id},
            )
            # Valid source insert
            connection.execute(
                text(
                    "INSERT INTO adventure_import_sources ("
                    "id, import_id, source_kind, normalized_text, metadata_json, sha256"
                    ") VALUES ("
                    ":id, :import_id, 'paste', 'Some text', '{}', 'sha-1'"
                    ")"
                ),
                {"id": uuid4(), "import_id": import_id},
            )

        # Invalid status on adventure_imports
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO adventure_imports (id, room_id, name, status, revision) "
                        "VALUES (:id, :room_id, 'Invalid', 'bad_status', 0)"
                    ),
                    {"id": uuid4(), "room_id": room_id},
                )

        # Invalid source_kind on adventure_import_sources
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO adventure_import_sources ("
                        "id, import_id, source_kind, normalized_text, metadata_json, sha256"
                        ") VALUES ("
                        ":id, :import_id, 'bad_kind', 'Some text', '{}', 'sha-2'"
                    ),
                    {"id": uuid4(), "import_id": import_id},
                )
    finally:
        engine.dispose()


def test_p6e_sources_unique_and_cascade_delete() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() == set(migration_heads(_config()).values())

    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        room_id = uuid4()
        import_id = uuid4()
        with engine.begin() as connection:
            _seed_room_and_campaign(connection, room_id=room_id, campaign_id=uuid4())
            connection.execute(
                text(
                    "INSERT INTO adventure_imports (id, room_id, name, status, revision) "
                    "VALUES (:id, :room_id, 'Test', 'source', 0)"
                ),
                {"id": import_id, "room_id": room_id},
            )
            connection.execute(
                text(
                    "INSERT INTO adventure_import_sources ("
                    "id, import_id, source_kind, normalized_text, metadata_json, sha256"
                    ") VALUES ("
                    ":id, :import_id, 'paste', 'text', '{}', 'same-sha'"
                    ")"
                ),
                {"id": uuid4(), "import_id": import_id},
            )
            connection.execute(
                text(
                    "INSERT INTO adventure_import_drafts ("
                    "import_id, draft_json, warnings_json, revision"
                    ") VALUES ("
                    ":import_id, '{}', '[]', 0"
                    ")"
                ),
                {"import_id": import_id},
            )

        # Duplicate (import_id, sha256)
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO adventure_import_sources ("
                        "id, import_id, source_kind, normalized_text, metadata_json, sha256"
                        ") VALUES ("
                        ":id, :import_id, 'txt', 'text 2', '{}', 'same-sha'"
                        ")"
                    ),
                    {"id": uuid4(), "import_id": import_id},
                )

        # Cascade delete
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM adventure_imports WHERE id = :id"),
                {"id": import_id},
            )
            assert connection.execute(text("SELECT count(*) FROM adventure_import_sources")).scalar() == 0
            assert connection.execute(text("SELECT count(*) FROM adventure_import_drafts")).scalar() == 0
    finally:
        engine.dispose()
