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
    reason="P4_POSTGRES_URL is only supplied by the P4-A PostgreSQL job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]
P4A_PARENT = "0021_m04b_ai_oauth"
P4A_REVISION = "0022_p4a_monster_instances"


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    config.attributes["target_database_url"] = POSTGRES_URL
    return config


def _reset_database() -> None:
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


def _assert_p4a_schema() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {"monster_templates", "monster_instances"} <= tables

        template_columns = {
            column["name"]: column for column in inspector.get_columns("monster_templates")
        }
        instance_columns = {
            column["name"]: column for column in inspector.get_columns("monster_instances")
        }
        assert {
            "id",
            "campaign_id",
            "name",
            "source_key",
            "rules",
            "created_at",
            "updated_at",
        } <= template_columns.keys()
        assert {
            "id",
            "campaign_id",
            "template_key",
            "custom_template_id",
            "name",
            "rules_snapshot",
            "current_hp",
            "temp_hp",
            "conditions",
            "effects",
            "combat_status",
            "initiative",
            "reaction_available",
            "resources",
            "visibility",
            "position_note",
            "created_at",
            "updated_at",
        } <= instance_columns.keys()

        for column in (template_columns["rules"], instance_columns["rules_snapshot"], instance_columns["conditions"], instance_columns["effects"], instance_columns["resources"]):
            assert type(column["type"]).__name__.upper() in {"JSON", "JSONB"}

        template_fks = {
            tuple(fk["constrained_columns"]): fk
            for fk in inspector.get_foreign_keys("monster_templates")
        }
        instance_fks = {
            tuple(fk["constrained_columns"]): fk
            for fk in inspector.get_foreign_keys("monster_instances")
        }
        assert template_fks[("campaign_id",)]["options"].get("ondelete") == "CASCADE"
        assert instance_fks[("campaign_id",)]["options"].get("ondelete") == "CASCADE"
        assert instance_fks[("custom_template_id",)]["options"].get("ondelete") == "SET NULL"

        checks = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("monster_instances")
        }
        assert {
            "ck_monster_instances_single_template_source",
            "ck_monster_instances_current_hp",
            "ck_monster_instances_temp_hp",
            "ck_monster_instances_combat_status",
            "ck_monster_instances_visibility",
        } <= checks

        template_indexes = {index["name"] for index in inspector.get_indexes("monster_templates")}
        instance_indexes = {index["name"] for index in inspector.get_indexes("monster_instances")}
        assert "ix_monster_templates_campaign_id" in template_indexes
        assert "ix_monster_instances_campaign_id" in instance_indexes
        assert "ix_monster_instances_custom_template_id" in instance_indexes
    finally:
        engine.dispose()


def test_p4a_migration_runs_on_real_postgres_from_web_parent() -> None:
    _reset_database()
    command.upgrade(_alembic_config(), P4A_PARENT)

    assert P4A_REVISION not in _revision_set()
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert "monster_templates" not in tables
    assert "monster_instances" not in tables

    command.upgrade(_alembic_config(), P4A_REVISION)

    assert P4A_REVISION in _revision_set()
    _assert_p4a_schema()


def test_p4a_schema_survives_full_postgres_upgrade_to_heads() -> None:
    _reset_database()
    command.upgrade(_alembic_config(), "heads")

    assert P4A_REVISION in _revision_set()
    _assert_p4a_schema()
