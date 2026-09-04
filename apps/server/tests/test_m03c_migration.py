from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


POSTGRES_URL = os.environ.get("M03C_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="M03C_POSTGRES_URL is only supplied by the M03-C PostgreSQL migration job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    return config


def test_m03c_postgres_upgrade_downgrade_upgrade() -> None:
    assert POSTGRES_URL is not None
    assert os.environ.get("DATABASE_URL") == POSTGRES_URL
    config = _alembic_config()
    engine = create_engine(POSTGRES_URL)

    command.upgrade(config, "head")
    assert inspect(engine).has_table("character_import_records")
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "0008_m03c_import_records"
    assert len(revision) <= 32

    command.downgrade(config, "0007_m03b_builder_provenance")
    assert not inspect(engine).has_table("character_import_records")

    command.upgrade(config, "head")
    assert inspect(engine).has_table("character_import_records")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == revision
    engine.dispose()
