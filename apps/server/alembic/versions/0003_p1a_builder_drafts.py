"""P1-A Builder Draft persistence.

Revision ID: 0003_p1a_builder_drafts
Revises: 0002_p0c_character_core
Create Date: 2026-08-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003_p1a_builder_drafts"
down_revision: Union[str, Sequence[str], None] = "0002_p0c_character_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

payload_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "character_build_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("character_id", sa.Uuid(), nullable=True),
        sa.Column("base_version_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("draft_payload", payload_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"],
            ["character_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_character_build_drafts_character_id",
        "character_build_drafts",
        ["character_id"],
        unique=False,
    )
    op.create_index(
        "ix_character_build_drafts_base_version_id",
        "character_build_drafts",
        ["base_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_character_build_drafts_base_version_id",
        table_name="character_build_drafts",
    )
    op.drop_index(
        "ix_character_build_drafts_character_id",
        table_name="character_build_drafts",
    )
    op.drop_table("character_build_drafts")
