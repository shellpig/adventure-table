"""P5-B B1: 0038 movement-bookkeeping migration against PostgreSQL.

Covers the migration contract for 0038_p5b_movement_bookkeeping:
- upgrade from 0037 backfills the four new columns on existing rows
  (0 / 0 / 0 / {}),
- new rows inserted without the columns get server defaults,
- the nonnegative CHECK constraints reject bad writes,
- downgrade to 0037 removes the columns and keeps existing data.
"""

from __future__ import annotations

import os
from uuid import uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from test_p5a_postgres_migration import (
    _config,
    _reset,
    _seed_p6_snapshot,
)


POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
pytestmark = [
    pytest.mark.xdist_group("postgres"),
    pytest.mark.skipif(
        not POSTGRES_URL,
        reason="P4_POSTGRES_URL is only supplied by the P4 PostgreSQL job",
    ),
]

P5B_PARENT = "0037_p5a_combat_board_positions"
P5B_REVISION = "0038_p5b_movement_bookkeeping"

NEW_COLUMNS = (
    "movement_used_feet",
    "movement_diagonal_steps_used",
    "movement_budget_feet",
    "pending_movement_state",
)


def _column_names(connection, table: str) -> set[str]:
    return set(
        connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :table"
            ),
            {"table": table},
        ).scalars()
    )


def test_p5b_postgres_migration() -> None:
    _reset()
    config = _config()
    command.upgrade(config, P5B_PARENT)
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.begin() as connection:
            seeded = _seed_p6_snapshot(connection)
            campaign_id = seeded["campaign_id"]
            session_id = seeded["session_id"]

            combat_id = uuid4()
            monster_id = uuid4()
            entry_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO combats (id, campaign_id, started_session_id, mode, status) "
                    "VALUES (:combat_id, :campaign_id, :session_id, 'tactical', 'initiative_pending')"
                ),
                {"combat_id": combat_id, "campaign_id": campaign_id, "session_id": session_id},
            )
            connection.execute(
                text(
                    "INSERT INTO monster_instances (id, campaign_id, name, rules_snapshot, current_hp, "
                    "conditions, effects, combat_status, visibility, resources) "
                    "VALUES (:monster_id, :campaign_id, 'Goblin', '{}', 7, '[]', '[]', 'active', 'public', '{}')"
                ),
                {"monster_id": monster_id, "campaign_id": campaign_id},
            )
            # At 0037 the movement columns do not exist yet.
            assert not (set(NEW_COLUMNS) & _column_names(connection, "combat_entries"))
            connection.execute(
                text(
                    "INSERT INTO combat_entries (id, combat_id, subject_kind, monster_instance_id, "
                    "display_name, status, ready_state, pending_reaction_state) "
                    "VALUES (:entry_id, :combat_id, 'monster', :monster_id, 'Goblin', 'active', '{}', '{}')"
                ),
                {"entry_id": entry_id, "combat_id": combat_id, "monster_id": monster_id},
            )

        command.upgrade(config, "heads")
        with engine.begin() as connection:
            names = _column_names(connection, "combat_entries")
            for column in NEW_COLUMNS:
                assert column in names, column

            # Existing rows are backfilled with 0 / 0 / 0 / {}.
            row = connection.execute(
                text(
                    "SELECT movement_used_feet, movement_diagonal_steps_used, "
                    "movement_budget_feet, pending_movement_state "
                    "FROM combat_entries WHERE id = :entry_id"
                ),
                {"entry_id": entry_id},
            ).one()
            assert tuple(row) == (0, 0, 0, {})

            # New rows inserted without the columns get server defaults.
            fresh_id = uuid4()
            fresh_monster_id = uuid4()
            connection.execute(
                text(
                    "INSERT INTO monster_instances (id, campaign_id, name, rules_snapshot, current_hp, "
                    "conditions, effects, combat_status, visibility, resources) "
                    "VALUES (:monster_id, :campaign_id, 'Orc', '{}', 15, '[]', '[]', 'active', 'public', '{}')"
                ),
                {"monster_id": fresh_monster_id, "campaign_id": campaign_id},
            )
            connection.execute(
                text(
                    "INSERT INTO combat_entries (id, combat_id, subject_kind, monster_instance_id, "
                    "display_name, status, ready_state, pending_reaction_state) "
                    "VALUES (:entry_id, :combat_id, 'monster', :monster_id, 'Orc', 'active', '{}', '{}')"
                ),
                {"entry_id": fresh_id, "combat_id": combat_id, "monster_id": fresh_monster_id},
            )
            row = connection.execute(
                text(
                    "SELECT movement_used_feet, movement_diagonal_steps_used, "
                    "movement_budget_feet, pending_movement_state "
                    "FROM combat_entries WHERE id = :entry_id"
                ),
                {"entry_id": fresh_id},
            ).one()
            assert tuple(row) == (0, 0, 0, {})

            # The nonnegative CHECK constraints reject bad writes.
            for column, bad_value in (
                ("movement_used_feet", -5),
                ("movement_diagonal_steps_used", -1),
                ("movement_budget_feet", -30),
            ):
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        connection.execute(
                            text(f"UPDATE combat_entries SET {column} = :bad WHERE id = :entry_id"),
                            {"bad": bad_value, "entry_id": entry_id},
                        )

        # Downgrade to 0037 removes the columns and keeps existing rows.
        command.downgrade(config, P5B_PARENT)
        with engine.begin() as connection:
            assert not (set(NEW_COLUMNS) & _column_names(connection, "combat_entries"))
            count = connection.execute(
                text("SELECT COUNT(*) FROM combat_entries WHERE combat_id = :combat_id"),
                {"combat_id": combat_id},
            ).scalar()
            assert count == 2
    finally:
        engine.dispose()
