from __future__ import annotations

from app.persistence.combat.tables import combat_entries
from app.persistence.rooms.p3c_runtime import roll_requests, roll_results


def _single_fk(column):
    foreign_keys = tuple(column.foreign_keys)
    assert len(foreign_keys) == 1
    return foreign_keys[0]


def test_roll_request_combat_target_metadata_matches_migration_fk() -> None:
    foreign_key = _single_fk(roll_requests.c.target_combat_entry_id)
    assert foreign_key.target_fullname == f"{combat_entries.name}.id"
    assert foreign_key.ondelete == "CASCADE"


def test_roll_result_combat_subject_metadata_matches_migration_fk() -> None:
    foreign_key = _single_fk(roll_results.c.subject_combat_entry_id)
    assert foreign_key.target_fullname == f"{combat_entries.name}.id"
    assert foreign_key.ondelete == "CASCADE"
