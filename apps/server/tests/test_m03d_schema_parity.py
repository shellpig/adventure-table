from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db import metadata
from app.persistence import builder_drafts as _builder_drafts  # noqa: F401
from app.persistence import character_imports as _character_imports  # noqa: F401
from app.persistence import characters as _characters  # noqa: F401


CHARACTER_TABLES = {
    "characters",
    "character_versions",
    "character_states",
    "character_build_drafts",
    "character_import_records",
}
FORBIDDEN_MULTIPLAYER_TABLES = {
    "rooms",
    "room_access_sessions",
    "room_characters",
    "room_builder_drafts",
    "campaigns",
    "campaign_roster_entries",
    "campaign_seats",
    "sessions",
    "session_participants",
    "active_character_session_leases",
    "session_table_runtime",
    "session_events",
    "session_messages",
    "room_stage_images",
    "session_stages",
}


def _alembic_config(server_root: Path) -> Config:
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    return config


def _sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def _schema_snapshot(engine, *, allowed: set[str]) -> dict[str, object]:
    inspector = inspect(engine)
    table_names = sorted(
        name
        for name in inspector.get_table_names()
        if name != "alembic_version" and name in allowed
    )

    tables: dict[str, object] = {}
    for table_name in table_names:
        columns = {
            column["name"]: {
                "type": str(column["type"]),
                "nullable": bool(column["nullable"]),
            }
            for column in inspector.get_columns(table_name)
        }
        indexes = sorted(
            (
                index["name"],
                tuple(index["column_names"]),
                bool(index["unique"]),
            )
            for index in inspector.get_indexes(table_name)
        )
        unique_constraints = sorted(
            (
                constraint["name"],
                tuple(constraint["column_names"]),
            )
            for constraint in inspector.get_unique_constraints(table_name)
        )
        tables[table_name] = {
            "columns": columns,
            "indexes": indexes,
            "unique_constraints": unique_constraints,
        }
    return tables


def test_sqlite_character_migration_schema_matches_character_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    server_root = Path(__file__).resolve().parents[1]
    migrated_path = tmp_path / "migrated.sqlite3"
    metadata_path = tmp_path / "metadata.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(migrated_path))

    command.upgrade(_alembic_config(server_root), "character@head")

    migrated_engine = create_engine(_sqlite_url(migrated_path))
    metadata_engine = create_engine(_sqlite_url(metadata_path))
    try:
        metadata.create_all(
            metadata_engine,
            tables=[metadata.tables[name] for name in sorted(CHARACTER_TABLES)],
        )
        assert set(_schema_snapshot(migrated_engine, allowed=CHARACTER_TABLES)) == CHARACTER_TABLES
        assert _schema_snapshot(
            migrated_engine, allowed=CHARACTER_TABLES
        ) == _schema_snapshot(metadata_engine, allowed=CHARACTER_TABLES)
        migrated_tables = set(inspect(migrated_engine).get_table_names())
        assert FORBIDDEN_MULTIPLAYER_TABLES.isdisjoint(migrated_tables)
    finally:
        migrated_engine.dispose()
        metadata_engine.dispose()
