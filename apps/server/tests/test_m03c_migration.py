from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


POSTGRES_URL = os.environ.get("M03C_POSTGRES_URL") or os.environ.get("P2_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="PostgreSQL migration URL is supplied by migration CI jobs",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    config.attributes["target_database_url"] = POSTGRES_URL
    return config


def test_m03c_postgres_upgrade_downgrade_upgrade() -> None:
    assert POSTGRES_URL is not None
    config = _alembic_config()
    engine = create_engine(POSTGRES_URL)
    expected_heads = set(ScriptDirectory.from_config(config).get_heads())

    command.upgrade(config, "heads")
    tables = inspect(engine).get_table_names()
    assert "character_import_records" in tables
    assert "rooms" in tables
    assert "room_access_sessions" in tables
    with engine.connect() as connection:
        revisions = set(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
    assert revisions == expected_heads
    assert all(len(revision) <= 32 for revision in revisions)

    command.downgrade(config, "0007_m03b_builder_provenance")
    assert not inspect(engine).has_table("character_import_records")
    assert not inspect(engine).has_table("rooms")

    command.upgrade(config, "heads")
    assert inspect(engine).has_table("character_import_records")
    with engine.connect() as connection:
        assert set(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        ) == expected_heads
    engine.dispose()
