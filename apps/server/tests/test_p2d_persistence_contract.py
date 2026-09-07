from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.persistence.rooms.tables import campaign_seats


def _check_sql() -> set[str]:
    return {
        str(constraint.sqltext)
        for constraint in campaign_seats.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _fk_ondelete(column_name: str) -> str | None:
    for constraint in campaign_seats.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        if [column.name for column in constraint.columns] == [column_name]:
            return constraint.ondelete
    raise AssertionError(f"missing FK for campaign_seats.{column_name}")


def test_p2d_campaign_seat_schema_matches_contract() -> None:
    assert list(campaign_seats.c.keys()) == [
        "id",
        "campaign_id",
        "role",
        "label",
        "controller_kind",
        "controller_access_session_id",
        "selected_character_id",
        "archived_at",
        "created_at",
        "updated_at",
    ]
    assert _fk_ondelete("campaign_id") == "CASCADE"
    assert _fk_ondelete("controller_access_session_id") == "SET NULL"
    assert _fk_ondelete("selected_character_id") == "SET NULL"

    checks = _check_sql()
    assert any(all(role in sql for role in ("dm", "player", "spectator")) for sql in checks)
    assert any(all(kind in sql for kind in ("human", "ai", "none")) for sql in checks)
    assert any("controller_access_session_id" in sql and "human" in sql for sql in checks)
    assert any("selected_character_id" in sql and "player" in sql for sql in checks)


def test_p2d_controller_can_repeat_but_character_selection_is_unique_per_campaign() -> None:
    assert not campaign_seats.c.controller_access_session_id.unique
    assert campaign_seats.c.archived_at.nullable is True
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in campaign_seats.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("campaign_id", "selected_character_id") in unique_columns
