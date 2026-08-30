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
    with op.batch_alter_table("character_versions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "version_kind",
                sa.String(length=32),
                server_default=sa.text("'legacy'"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("parent_version_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column("superseded_by_version_id", sa.Uuid(), nullable=True)
        )
        batch_op.add_column(sa.Column("change_note", sa.String(length=500), nullable=True))
        batch_op.create_foreign_key(
            "fk_character_versions_parent_version_id",
            "character_versions",
            ["parent_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_character_versions_superseded_by_version_id",
            "character_versions",
            ["superseded_by_version_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("character_build_drafts") as batch_op:
        batch_op.add_column(sa.Column("confirmed_character_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_character_build_drafts_confirmed_character_id",
            "characters",
            ["confirmed_character_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_character_build_drafts_confirmed_character_id",
            ["confirmed_character_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("character_build_drafts") as batch_op:
        batch_op.drop_index("ix_character_build_drafts_confirmed_character_id")
        batch_op.drop_constraint(
            "fk_character_build_drafts_confirmed_character_id",
            type_="foreignkey",
        )
        batch_op.drop_column("confirmed_at")
        batch_op.drop_column("confirmed_character_id")

    with op.batch_alter_table("character_versions") as batch_op:
        batch_op.drop_constraint(
            "fk_character_versions_superseded_by_version_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_character_versions_parent_version_id",
            type_="foreignkey",
        )
        batch_op.drop_column("change_note")
        batch_op.drop_column("superseded_by_version_id")
        batch_op.drop_column("parent_version_id")
        batch_op.drop_column("version_kind")
