"""Add concentration pointer to monster_instances.

Revision ID: 0026_p4e_monster_concentration
Revises: 0025_p4c_core_resolution
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0026_p4e_monster_concentration"
down_revision = "0025_p4c_core_resolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("monster_instances") as batch:
        batch.add_column(sa.Column("concentration", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("monster_instances") as batch:
        batch.drop_column("concentration")
