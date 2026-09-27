"""Add the Disengage flag to combat_entries (P5-E).

Revision ID: 0039_p5e_disengaged
Revises: 0038_p5b_movement_bookkeeping

Web-only tactical flag: whether the entry used Disengage this turn.
Opportunity-attack auto-detection skips a mover that disengaged. Written
alongside ``dodging`` on Disengage, cleared by the same turn resets.
Existing rows upgrade to false.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0039_p5e_disengaged"
down_revision = "0038_p5b_movement_bookkeeping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "combat_entries",
        sa.Column("disengaged", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("combat_entries", "disengaged")
