"""Add auto_fail column to roll_requests table.

Revision ID: 0029_p4f_roll_request_auto_fail
Revises: 0028_p4f_monster_reveal_state
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0029_p4f_roll_request_auto_fail"
down_revision = "0028_p4f_monster_reveal_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("roll_requests") as batch:
        batch.add_column(
            sa.Column("auto_fail", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("roll_requests") as batch:
        batch.drop_column("auto_fail")
