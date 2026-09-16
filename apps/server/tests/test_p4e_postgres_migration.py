from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text


POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P4_POSTGRES_URL is only supplied by the P4 PostgreSQL job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]
P4E_PARENT = "0025_p4c_core_resolution"
P4E_HEAD = "0026_p4e_monster_concentration"


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


def _assert_concentration_column_present() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        inspector = inspect(engine)
        columns = {column["name"]: column for column in inspector.get_columns("monster_instances")}
        assert "concentration" in columns
        assert columns["concentration"]["nullable"] is True
    finally:
        engine.dispose()


def _assert_concentration_column_absent() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        inspector = inspect(engine)
        columns = {column["name"]: column for column in inspector.get_columns("monster_instances")}
        assert "concentration" not in columns
    finally:
        engine.dispose()


def test_p4e_real_postgres_upgrade_and_downgrade_from_p4c_parent() -> None:
    _reset()
    command.upgrade(_config(), P4E_PARENT)
    assert P4E_HEAD not in _revision_set()
    _assert_concentration_column_absent()

    command.upgrade(_config(), "heads")
    assert P4E_HEAD in _revision_set()
    _assert_concentration_column_present()

    command.downgrade(_config(), P4E_PARENT)
    assert P4E_HEAD not in _revision_set()
    _assert_concentration_column_absent()


def test_p4e_schema_survives_fresh_upgrade_to_heads() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert P4E_HEAD in _revision_set()
    _assert_concentration_column_present()
