"""Character archive state for workshop lifecycle.

Revision ID: 0006_character_archive
Revises: 0005_p1g_character_versions
Create Date: 2026-08-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_character_archive"
down_revision: Union[str, Sequence[str], None] = "0005_p1g_character_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable timestamp rather than a status flag: it answers "is this
    # archived" and "since when" with one column, and existing rows are
    # correctly active without a backfill.
    with op.batch_alter_table("characters") as batch_op:
        batch_op.add_column(
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("characters") as batch_op:
        batch_op.drop_column("archived_at")
