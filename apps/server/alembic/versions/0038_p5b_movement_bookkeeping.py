"""Add per-turn movement bookkeeping columns to combat_entries (P5-B).

Revision ID: 0038_p5b_movement_bookkeeping
Revises: 0037_p5a_combat_board_positions

Web-only tactical movement state: feet used this turn, diagonal steps used
this turn (5/10 alternating parity), the granted movement budget in feet, and
the paused-movement state reserved for P5-E reactions. Existing rows upgrade
to 0 / {}.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0038_p5b_movement_bookkeeping"
down_revision = "0037_p5a_combat_board_positions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "combat_entries",
        sa.Column("movement_used_feet", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "combat_entries",
        sa.Column(
            "movement_diagonal_steps_used", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "combat_entries",
        sa.Column("movement_budget_feet", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "combat_entries",
        sa.Column(
            "pending_movement_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
    )
    op.create_check_constraint(
        "ck_combat_entries_movement_used_feet",
        "combat_entries",
        "movement_used_feet >= 0",
    )
    op.create_check_constraint(
        "ck_combat_entries_movement_diagonal_steps_used",
        "combat_entries",
        "movement_diagonal_steps_used >= 0",
    )
    op.create_check_constraint(
        "ck_combat_entries_movement_budget_feet",
        "combat_entries",
        "movement_budget_feet >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_combat_entries_movement_budget_feet", "combat_entries", type_="check"
    )
    op.drop_constraint(
        "ck_combat_entries_movement_diagonal_steps_used", "combat_entries", type_="check"
    )
    op.drop_constraint(
        "ck_combat_entries_movement_used_feet", "combat_entries", type_="check"
    )
    op.drop_column("combat_entries", "pending_movement_state")
    op.drop_column("combat_entries", "movement_budget_feet")
    op.drop_column("combat_entries", "movement_diagonal_steps_used")
    op.drop_column("combat_entries", "movement_used_feet")
