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
P4B_PARENT = "0022_p4a_monster_instances"
P4B_HEAD = "0024_p4b_combat_roll_targets"
P4B_APPLIED_HEADS = {
    P4B_HEAD,
    "0025_p4c_core_resolution",
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


def _assert_p4b_applied() -> None:
    assert _revision_set() & P4B_APPLIED_HEADS


def _assert_schema() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        inspector = inspect(engine)
        assert {"combats", "combat_entries", "combat_actions"} <= set(inspector.get_table_names())

        combat_columns = {column["name"]: column for column in inspector.get_columns("combats")}
        assert {
            "campaign_id",
            "started_session_id",
            "ended_session_id",
            "status",
            "round_number",
            "current_turn_entry_id",
            "revision",
        } <= combat_columns.keys()

        entry_columns = {column["name"]: column for column in inspector.get_columns("combat_entries")}
        assert {
            "subject_kind",
            "character_id",
            "monster_instance_id",
            "is_hostile",
            "initiative_roll_request_id",
            "initiative_roll_result_id",
            "initiative_total",
            "turn_order",
            "action_available",
            "bonus_action_available",
            "reaction_available",
            "attacks_allowed",
            "attacks_used",
        } <= entry_columns.keys()
        assert entry_columns["is_hostile"]["nullable"] is False

        request_columns = {column["name"]: column for column in inspector.get_columns("roll_requests")}
        result_columns = {column["name"]: column for column in inspector.get_columns("roll_results")}
        assert request_columns["target_seat_id"]["nullable"] is True
        assert result_columns["subject_seat_id"]["nullable"] is True
        assert "target_combat_entry_id" in request_columns
        assert "subject_combat_entry_id" in result_columns

        request_fks = {
            tuple(fk["constrained_columns"]): fk
            for fk in inspector.get_foreign_keys("roll_requests")
        }
        result_fks = {
            tuple(fk["constrained_columns"]): fk
            for fk in inspector.get_foreign_keys("roll_results")
        }
        assert request_fks[("target_combat_entry_id",)]["referred_table"] == "combat_entries"
        assert request_fks[("target_combat_entry_id",)]["options"].get("ondelete") == "CASCADE"
        assert result_fks[("subject_combat_entry_id",)]["referred_table"] == "combat_entries"
        assert result_fks[("subject_combat_entry_id",)]["options"].get("ondelete") == "CASCADE"

        combat_indexes = {index["name"]: index for index in inspector.get_indexes("combats")}
        assert combat_indexes["uq_combats_campaign_active"]["unique"] is True
        assert "ix_combat_entries_turn_order" in {
            index["name"] for index in inspector.get_indexes("combat_entries")
        }
        assert "ix_roll_requests_target_combat_entry_id" in {
            index["name"] for index in inspector.get_indexes("roll_requests")
        }
        assert "ix_roll_results_subject_combat_entry_id" in {
            index["name"] for index in inspector.get_indexes("roll_results")
        }
    finally:
        engine.dispose()


def test_p4b_real_postgres_upgrade_from_p4a_parent() -> None:
    _reset()
    command.upgrade(_config(), P4B_PARENT)
    assert P4B_HEAD not in _revision_set()
    command.upgrade(_config(), "heads")
    _assert_p4b_applied()
    _assert_schema()


def test_p4b_schema_survives_fresh_upgrade_to_heads() -> None:
    _reset()
    command.upgrade(_config(), "heads")
    _assert_p4b_applied()
    _assert_schema()
