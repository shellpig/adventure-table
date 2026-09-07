from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from app.persistence.rooms.tables import campaign_roster_entries, campaigns, rooms


def _check_sql(table) -> set[str]:
    return {
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _fk_ondelete(table, column_name: str) -> str | None:
    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        if [column.name for column in constraint.columns] == [column_name]:
            return constraint.ondelete
    raise AssertionError(f"missing FK for {table.name}.{column_name}")


def test_p2c_campaign_schema_matches_contract() -> None:
    assert list(campaigns.c.keys()) == [
        "id",
        "room_id",
        "name",
        "ruleset",
        "status",
        "created_at",
        "updated_at",
    ]
    assert _fk_ondelete(campaigns, "room_id") == "CASCADE"
    assert any(
        all(status in sql for status in ("draft", "active", "completed", "archived"))
        for sql in _check_sql(campaigns)
    )

    assert rooms.c.active_campaign_id.nullable is True
    assert _fk_ondelete(rooms, "active_campaign_id") == "SET NULL"


def test_p2c_roster_schema_is_reference_only_and_protects_history() -> None:
    assert list(campaign_roster_entries.c.keys()) == [
        "campaign_id",
        "character_id",
        "status",
        "added_at",
        "updated_at",
    ]
    assert [column.name for column in campaign_roster_entries.primary_key.columns] == [
        "campaign_id",
        "character_id",
    ]
    assert _fk_ondelete(campaign_roster_entries, "campaign_id") == "CASCADE"
    assert _fk_ondelete(campaign_roster_entries, "character_id") == "RESTRICT"
    assert not any(
        name in campaign_roster_entries.c
        for name in ("state_payload", "build_payload", "inventory", "hp")
    )
    assert any(
        all(status in sql for status in ("active", "inactive", "retired", "dead"))
        for sql in _check_sql(campaign_roster_entries)
    )
