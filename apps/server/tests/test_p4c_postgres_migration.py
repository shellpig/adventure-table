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
P4C_PARENT = "0024_p4b_combat_roll_targets"
P4C_HEAD = "0025_p4c_core_resolution"
P4C_APPLIED_HEADS = {
    P4C_HEAD,
    "0026_p4e_monster_concentration",
    "0027_p4f_monster_outcome",
    "0028_p4f_monster_reveal_state",
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


def _assert_schema() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        inspector = inspect(engine)
        entry_columns = {column["name"]: column for column in inspector.get_columns("combat_entries")}
        assert {
            "death_save_successes",
            "death_save_failures",
            "death_save_stable",
            "death_save_dead",
        } <= entry_columns.keys()
        for name in (
            "death_save_successes",
            "death_save_failures",
            "death_save_stable",
            "death_save_dead",
        ):
            assert entry_columns[name]["nullable"] is False

        action_columns = {column["name"]: column for column in inspector.get_columns("combat_actions")}
        assert {
            "target_entry_id",
            "resolution_status",
            "roll_request_id",
            "roll_result_id",
            "resolution_result",
        } <= action_columns.keys()
        assert action_columns["resolution_status"]["nullable"] is False

        action_fks = {
            tuple(fk["constrained_columns"]): fk
            for fk in inspector.get_foreign_keys("combat_actions")
        }
        assert action_fks[("target_entry_id",)]["referred_table"] == "combat_entries"
        assert action_fks[("target_entry_id",)]["options"].get("ondelete") == "CASCADE"

        action_indexes = {index["name"] for index in inspector.get_indexes("combat_actions")}
        assert "ix_combat_actions_target_entry_id" in action_indexes
        assert "ix_combat_actions_roll_request_id" in action_indexes

        entry_checks = {check["name"] for check in inspector.get_check_constraints("combat_entries")}
        assert {
            "ck_combat_entries_death_save_successes",
            "ck_combat_entries_death_save_failures",
            "ck_combat_entries_death_save_terminal",
        } <= entry_checks
        action_checks = {check["name"] for check in inspector.get_check_constraints("combat_actions")}
        assert "ck_combat_actions_resolution_status" in action_checks
    finally:
        engine.dispose()


def test_p4c_real_postgres_upgrade_from_p4b_parent() -> None:
    _reset()
    command.upgrade(_config(), P4C_PARENT)
    assert P4C_HEAD not in _revision_set()
    command.upgrade(_config(), "heads")
    assert _revision_set() & P4C_APPLIED_HEADS
    _assert_schema()


def test_p4c_schema_survives_fresh_upgrade_to_heads() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    assert _revision_set() & P4C_APPLIED_HEADS
    _assert_schema()
