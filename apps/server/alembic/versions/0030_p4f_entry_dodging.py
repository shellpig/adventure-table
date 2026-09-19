"""Add dodging column to combat_entries table.

Revision ID: 0030_p4f_entry_dodging
Revises: 0029_p4f_roll_request_auto_fail
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0030_p4f_entry_dodging"
down_revision = "0029_p4f_roll_request_auto_fail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("combat_entries") as batch:
        batch.add_column(
            sa.Column("dodging", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("combat_entries") as batch:
        batch.drop_column("dodging")
