from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    UniqueConstraint,
)

from app.persistence.rooms.tables import (
    active_character_session_leases,
    session_participants,
    sessions,
)


def _fk_ondelete(table, column_name: str) -> str | None:
    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        if [column.name for column in constraint.columns] == [column_name]:
            return constraint.ondelete
    raise AssertionError(f"missing FK for {table.name}.{column_name}")


def _check_sql(table) -> set[str]:
    return {
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_p2e_session_schema_matches_history_contract() -> None:
    assert list(sessions.c.keys()) == [
        "id",
        "campaign_id",
        "status",
        "dm_seat_id",
        "dm_controller_kind",
        "dm_controller_access_session_id",
        "started_at",
        "ended_at",
        "created_at",
    ]
    assert _fk_ondelete(sessions, "campaign_id") == "RESTRICT"
    assert _fk_ondelete(sessions, "dm_seat_id") == "RESTRICT"
    assert _fk_ondelete(sessions, "dm_controller_access_session_id") == "RESTRICT"
    checks = _check_sql(sessions)
    assert any(all(status in sql for status in ("active", "ended", "abandoned")) for sql in checks)
    assert any("dm_controller_access_session_id" in sql and "human" in sql for sql in checks)


def test_p2e_participant_schema_keeps_non_null_seat_history() -> None:
    assert list(session_participants.c.keys()) == [
        "id",
        "session_id",
        "seat_id",
        "role_snapshot",
        "controller_kind_at_join",
        "controller_access_session_id_at_join",
        "active_character_id",
        "joined_at",
        "left_at",
    ]
    assert session_participants.c.seat_id.nullable is False
    assert _fk_ondelete(session_participants, "session_id") == "CASCADE"
    assert _fk_ondelete(session_participants, "seat_id") == "RESTRICT"
    assert _fk_ondelete(session_participants, "controller_access_session_id_at_join") == "RESTRICT"
    assert _fk_ondelete(session_participants, "active_character_id") == "RESTRICT"
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in session_participants.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("session_id", "seat_id") in unique_columns
    assert ("session_id", "active_character_id") in unique_columns
    checks = _check_sql(session_participants)
    assert any(all(role in sql for role in ("dm", "player", "spectator")) for sql in checks)
    assert any("active_character_id" in sql and "player" in sql for sql in checks)


def test_p2e_active_character_lease_uses_character_primary_key() -> None:
    primary_key = next(
        constraint
        for constraint in active_character_session_leases.constraints
        if isinstance(constraint, PrimaryKeyConstraint)
    )
    assert tuple(column.name for column in primary_key.columns) == ("character_id",)
    assert _fk_ondelete(active_character_session_leases, "character_id") == "RESTRICT"
    assert _fk_ondelete(active_character_session_leases, "session_id") == "CASCADE"
    assert _fk_ondelete(active_character_session_leases, "participant_id") == "CASCADE"
    assert active_character_session_leases.c.participant_id.unique is True
