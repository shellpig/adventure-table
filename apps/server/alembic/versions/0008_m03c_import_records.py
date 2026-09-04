"""Add Character import provenance records.

Revision ID: 0008_m03c_import_records
Revises: 0007_m03b_builder_provenance
Create Date: 2026-09-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_m03c_import_records"
down_revision: Union[str, Sequence[str], None] = "0007_m03b_builder_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "character_import_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.Uuid(), nullable=True),
        sa.Column("draft_id", sa.Uuid(), nullable=True),
        sa.Column("source_character_id", sa.Uuid(), nullable=False),
        sa.Column("source_export_id", sa.Uuid(), nullable=False),
        sa.Column("landing_mode", sa.String(length=32), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "character_id IS NULL OR draft_id IS NULL",
            name="ck_character_import_records_single_target",
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["character_build_drafts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_character_import_records_source_character_id",
        "character_import_records",
        ["source_character_id"],
        unique=False,
    )
    op.create_index(
        "ix_character_import_records_source_export_id",
        "character_import_records",
        ["source_export_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_character_import_records_source_export_id",
        table_name="character_import_records",
    )
    op.drop_index(
        "ix_character_import_records_source_character_id",
        table_name="character_import_records",
    )
    op.drop_table("character_import_records")
