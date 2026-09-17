"""Add reveal_state column to monster_instances.

Revision ID: 0028_p4f_monster_reveal_state
Revises: 0027_p4f_monster_outcome
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0028_p4f_monster_reveal_state"
down_revision = "0027_p4f_monster_outcome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("monster_instances") as batch:
        batch.add_column(
            sa.Column("reveal_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
        )


def downgrade() -> None:
    with op.batch_alter_table("monster_instances") as batch:
        batch.drop_column("reveal_state")
