from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


def _alembic_config(server_root: Path) -> Config:
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    return config


def _sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def test_sqlite_alembic_upgrade_downgrade_upgrade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    server_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration-chain.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(database_path))

    config = _alembic_config(server_root)
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    assert expected_head is not None

    command.upgrade(config, "head")

    engine = create_engine(_sqlite_url(database_path))
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == expected_head
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

    command.upgrade(config, "head")

    engine = create_engine(_sqlite_url(database_path))
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == expected_head
        assert "character_import_records" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
