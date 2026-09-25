"""Add acting controller columns to session_events.

Revision ID: 0034_m06b_event_actor_stamp
Revises: 0033_p6e_adventure_imports
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0034_m06b_event_actor_stamp"
down_revision = "0033_p6e_adventure_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_events",
        sa.Column("acting_ai_controller_grant_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "session_events",
        sa.Column("acting_grant_generation", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("session_events", "acting_grant_generation")
    op.drop_column("session_events", "acting_ai_controller_grant_id")
