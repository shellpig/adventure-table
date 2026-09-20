"""Create P6-A room_assets and adventure tables.

Revision ID: 0031_p6a_room_assets_adventures
Revises: 0030_p4f_entry_dodging
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0031_p6a_room_assets_adventures"
down_revision = "0030_p4f_entry_dodging"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "room_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=127), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "kind IN ('image', 'source_document')",
            name="ck_room_assets_kind",
        ),
        sa.CheckConstraint(
            "visibility IN ('room', 'dm_only')",
            name="ck_room_assets_visibility",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_room_assets_storage_key"),
    )
    op.create_index(
        "ix_room_assets_room_id",
        "room_assets",
        ["room_id"],
        unique=False,
    )

    op.create_table(
        "adventure_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "ruleset",
            sa.String(length=64),
            nullable=False,
            server_default="dnd5e-2014",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
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
            "status IN ('draft', 'finalized', 'archived')",
            name="ck_adventure_definitions_status",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_adventure_definitions_room_id",
        "adventure_definitions",
        ["room_id"],
        unique=False,
    )

    op.create_table(
        "adventure_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("adventure_id", sa.Uuid(), nullable=False),
        sa.Column("parent_entry_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column(
            "visibility",
            sa.String(length=16),
            nullable=False,
            server_default="public",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("provenance_json", sa.JSON(), nullable=True),
        sa.Column("source_ref_json", sa.JSON(), nullable=True),
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
            "kind IN ('section', 'scene', 'npc', 'item', 'monster_ref', 'quest', 'secret', "
            "'dm_note', 'suggested_check', 'map', 'lore', 'other')",
            name="ck_adventure_entries_kind",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'dm_only')",
            name="ck_adventure_entries_visibility",
        ),
        sa.ForeignKeyConstraint(
            ["adventure_id"], ["adventure_definitions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_entry_id"], ["adventure_entries.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_adventure_entries_adventure_id",
        "adventure_entries",
        ["adventure_id"],
        unique=False,
    )
    op.create_index(
        "ix_adventure_entries_parent_entry_id",
        "adventure_entries",
        ["parent_entry_id"],
        unique=False,
    )

    op.create_table(
        "adventure_entry_assets",
        sa.Column("adventure_entry_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.CheckConstraint(
            "role IN ('image', 'map', 'source', 'attachment')",
            name="ck_adventure_entry_assets_role",
        ),
        sa.ForeignKeyConstraint(
            ["adventure_entry_id"],
            ["adventure_entries.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["room_assets.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("adventure_entry_id", "asset_id"),
    )

    op.create_table(
        "campaign_adventure_links",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("adventure_id", sa.Uuid(), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "attached_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["adventure_id"],
            ["adventure_definitions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("campaign_id", "adventure_id"),
    )


def downgrade() -> None:
    op.drop_table("campaign_adventure_links")
    op.drop_table("adventure_entry_assets")
    op.drop_index(
        "ix_adventure_entries_parent_entry_id",
        table_name="adventure_entries",
    )
    op.drop_index(
        "ix_adventure_entries_adventure_id",
        table_name="adventure_entries",
    )
    op.drop_table("adventure_entries")
    op.drop_index(
        "ix_adventure_definitions_room_id",
        table_name="adventure_definitions",
    )
    op.drop_table("adventure_definitions")
    op.drop_index(
        "ix_room_assets_room_id",
        table_name="room_assets",
    )
    op.drop_table("room_assets")
