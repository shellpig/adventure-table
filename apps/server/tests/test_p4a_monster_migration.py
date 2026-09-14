from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext


def _load_migration():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0022_p4a_monster_instances.py"
    spec = importlib.util.spec_from_file_location("p4a_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p4a_migration_is_on_web_track_after_m04b() -> None:
    migration = _load_migration()
    assert migration.revision == "0022_p4a_monster_instances"
    assert migration.down_revision == "0021_m04b_ai_oauth"
    assert migration.branch_labels is None


def test_p4a_migration_upgrade_and_downgrade_create_only_combat_tables() -> None:
    migration = _load_migration()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE campaigns (id CHAR(32) PRIMARY KEY)"
            )
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
            names = set(sa.inspect(connection).get_table_names())
            assert {"campaigns", "monster_templates", "monster_instances"} <= names
            assert "sessions" not in names
            with Operations.context(context):
                migration.downgrade()
            assert set(sa.inspect(connection).get_table_names()) == {"campaigns"}
    finally:
        engine.dispose()
