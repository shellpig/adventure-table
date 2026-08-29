"""P1-F character creation/version metadata and draft confirmation.

Revision ID: 0004_p1f_character_creation
Revises: 0003_p1a_builder_drafts
Create Date: 2026-08-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_p1f_character_creation"
down_revision: Union[str, Sequence[str], None] = "0003_p1a_builder_drafts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "character_versions",
        sa.Column(
            "version_kind",
            sa.String(length=32),
            server_default=sa.text("'legacy'"),
            nullable=False,
        ),
    )
    op.add_column(
        "character_versions",
        sa.Column("parent_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "character_versions",
        sa.Column("superseded_by_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "character_versions",
        sa.Column("change_note", sa.String(length=500), nullable=True),
    )
    op.create_foreign_key(
        "fk_character_versions_parent_version_id",
        "character_versions",
        "character_versions",
        ["parent_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_character_versions_superseded_by_version_id",
        "character_versions",
        "character_versions",
        ["superseded_by_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "character_build_drafts",
        sa.Column("confirmed_character_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "character_build_drafts",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_character_build_drafts_confirmed_character_id",
        "character_build_drafts",
        "characters",
        ["confirmed_character_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_character_build_drafts_confirmed_character_id",
        "character_build_drafts",
        ["confirmed_character_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_character_build_drafts_confirmed_character_id",
        table_name="character_build_drafts",
    )
    op.drop_constraint(
        "fk_character_build_drafts_confirmed_character_id",
        "character_build_drafts",
        type_="foreignkey",
    )
    op.drop_column("character_build_drafts", "confirmed_at")
    op.drop_column("character_build_drafts", "confirmed_character_id")

    op.drop_constraint(
        "fk_character_versions_superseded_by_version_id",
        "character_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_character_versions_parent_version_id",
        "character_versions",
        type_="foreignkey",
    )
    op.drop_column("character_versions", "change_note")
    op.drop_column("character_versions", "superseded_by_version_id")
    op.drop_column("character_versions", "parent_version_id")
    op.drop_column("character_versions", "version_kind")
