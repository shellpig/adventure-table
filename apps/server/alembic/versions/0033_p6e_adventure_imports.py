"""Create P6-E adventure import tables.

Revision ID: 0033_p6e_adventure_imports
Revises: 0032_p6b_campaign_world_runtime
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0033_p6e_adventure_imports"
down_revision = "0032_p6b_campaign_world_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adventure_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="source",
        ),
        sa.Column("target_adventure_id", sa.Uuid(), nullable=True),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('source', 'drafting', 'review', 'finalized', 'cancelled')",
            name="ck_adventure_imports_status",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_adventure_id"],
            ["adventure_definitions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_adventure_imports_room_id",
        "adventure_imports",
        ["room_id"],
        unique=False,
    )

    op.create_table(
        "adventure_import_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=True),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source_kind IN ('paste', 'txt', 'markdown', 'pdf', 'docx', 'url')",
            name="ck_adventure_import_sources_source_kind",
        ),
        sa.ForeignKeyConstraint(
            ["import_id"], ["adventure_imports.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["room_assets.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "import_id",
            "sha256",
            name="uq_adventure_import_sources_import_sha256",
        ),
    )
    op.create_index(
        "ix_adventure_import_sources_import_id",
        "adventure_import_sources",
        ["import_id"],
        unique=False,
    )

    op.create_table(
        "adventure_import_drafts",
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("draft_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["import_id"], ["adventure_imports.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("import_id"),
    )


def downgrade() -> None:
    op.drop_table("adventure_import_drafts")
    op.drop_index(
        "ix_adventure_import_sources_import_id",
        table_name="adventure_import_sources",
    )
    op.drop_table("adventure_import_sources")
    op.drop_index(
        "ix_adventure_imports_room_id",
        table_name="adventure_imports",
    )
    op.drop_table("adventure_imports")
