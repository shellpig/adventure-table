"""Add optimistic concurrency revision to Character Current State.

Revision ID: 0015_character_state_revision
Revises: 0009_p2a_character_head
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0015_character_state_revision"
down_revision: str | None = "0009_p2a_character_head"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "character_states",
        sa.Column(
            "state_revision",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    op.drop_column("character_states", "state_revision")
