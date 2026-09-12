from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def _config(server_root: Path) -> Config:
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    return config


def test_m04b_migration_creates_only_documented_oauth_tables(tmp_path: Path, monkeypatch) -> None:
    server_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "m04b.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(database_path))

    command.upgrade(_config(server_root), "web@head")

    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    try:
        inspector = inspect(engine)
        names = set(inspector.get_table_names())
        assert {
            "ai_oauth_clients",
            "ai_oauth_authorizations",
            "ai_oauth_authorization_codes",
            "ai_oauth_tokens",
        }.issubset(names)

        token_columns = {column["name"] for column in inspector.get_columns("ai_oauth_tokens")}
        assert token_columns == {
            "id",
            "token_hash",
            "kind",
            "authorization_id",
            "expires_at",
            "revoked_at",
            "last_used_at",
        }
    finally:
        engine.dispose()


def test_m04b_active_authorization_index_is_partial_and_unique(tmp_path: Path, monkeypatch) -> None:
    server_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "m04b-index.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(database_path))

    command.upgrade(_config(server_root), "web@head")

    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    try:
        indexes = {
            item["name"]: item
            for item in inspect(engine).get_indexes("ai_oauth_authorizations")
        }
        active = indexes["uq_ai_oauth_authorizations_active_grant"]
        assert active["unique"] is True
        assert active["column_names"] == ["grant_id"]
    finally:
        engine.dispose()
