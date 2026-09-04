from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db import metadata
from app.persistence import builder_drafts as _builder_drafts  # noqa: F401
from app.persistence import character_imports as _character_imports  # noqa: F401
from app.persistence import characters as _characters  # noqa: F401


EXPECTED_HEAD = "0008_m03c_import_records"


def _alembic_config(server_root: Path) -> Config:
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    return config


def _sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def _schema_snapshot(engine) -> dict[str, object]:
    inspector = inspect(engine)
    table_names = sorted(
        name for name in inspector.get_table_names() if name != "alembic_version"
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


def test_sqlite_alembic_upgrade_head_and_downgrade_base(
    tmp_path: Path,
    monkeypatch,
) -> None:
    server_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration-chain.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(database_path))

    config = _alembic_config(server_root)
    command.upgrade(config, "head")

    engine = create_engine(_sqlite_url(database_path))
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == EXPECTED_HEAD
        assert "character_import_records" in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.downgrade(config, "base")

    engine = create_engine(_sqlite_url(database_path))
    try:
        inspector = inspect(engine)
        assert inspector.get_table_names() == ["alembic_version"]
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT COUNT(*) FROM alembic_version")
            ).scalar_one() == 0
    finally:
        engine.dispose()


def test_sqlite_migration_schema_matches_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    server_root = Path(__file__).resolve().parents[1]
    migrated_path = tmp_path / "migrated.sqlite3"
    metadata_path = tmp_path / "metadata.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(migrated_path))

    command.upgrade(_alembic_config(server_root), "head")

    migrated_engine = create_engine(_sqlite_url(migrated_path))
    metadata_engine = create_engine(_sqlite_url(metadata_path))
    try:
        metadata.create_all(metadata_engine)
        assert _schema_snapshot(migrated_engine) == _schema_snapshot(metadata_engine)
    finally:
        migrated_engine.dispose()
        metadata_engine.dispose()
