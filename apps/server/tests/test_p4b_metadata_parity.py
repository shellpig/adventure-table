from __future__ import annotations

from sqlalchemy import create_engine, inspect

from app.db import metadata
from app.persistence.combat.tables import combat_entries  # noqa: F401
from app.persistence.rooms.p3c_runtime import roll_requests, roll_results


def _foreign_key_map(table) -> dict[tuple[str, ...], tuple[str, tuple[str, ...], str | None]]:
    engine = create_engine("sqlite+pysqlite://")
    try:
        metadata.create_all(engine)
        rows = inspect(engine).get_foreign_keys(table.name)
        return {
            tuple(row["constrained_columns"]): (
                str(row["referred_table"]),
                tuple(row["referred_columns"]),
                (row.get("options") or {}).get("ondelete"),
            )
            for row in rows
        }
    finally:
        engine.dispose()


def test_create_all_roll_request_combat_target_matches_migration_fk() -> None:
    foreign_keys = _foreign_key_map(roll_requests)
    assert foreign_keys[("target_combat_entry_id",)] == (
        "combat_entries",
        ("id",),
        "CASCADE",
    )


def test_create_all_roll_result_combat_subject_matches_migration_fk() -> None:
    foreign_keys = _foreign_key_map(roll_results)
    assert foreign_keys[("subject_combat_entry_id",)] == (
        "combat_entries",
        ("id",),
        "CASCADE",
    )
