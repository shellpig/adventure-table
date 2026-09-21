"""Create P6-B campaign world runtime tables.

Revision ID: 0032_p6b_campaign_world_runtime
Revises: 0031_p6a_room_assets_adventures
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0032_p6b_campaign_world_runtime"
down_revision = "0031_p6a_room_assets_adventures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_world_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("dm_notes", sa.Text(), nullable=True),
        sa.Column(
            "visibility",
            sa.String(length=16),
            nullable=False,
            server_default="public",
        ),
        sa.Column(
            "needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("source_adventure_entry_id", sa.Uuid(), nullable=True),
        sa.Column("provenance_json", sa.JSON(), nullable=True),
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("created_by_actor_kind", sa.String(length=16), nullable=False),
        sa.Column("created_by_actor_id", sa.Uuid(), nullable=True),
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
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('scene', 'npc', 'item', 'quest', 'fact', 'secret', 'hazard', 'other')",
            name="ck_campaign_world_entries_kind",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'dm_only', 'character')",
            name="ck_campaign_world_entries_visibility",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_campaign_world_entries_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_adventure_entry_id"],
            ["adventure_entries.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_campaign_world_entries_campaign_id",
        "campaign_world_entries",
        ["campaign_id"],
        unique=False,
    )
    op.create_index(
        "ix_campaign_world_entries_source_adventure_entry_id",
        "campaign_world_entries",
        ["source_adventure_entry_id"],
        unique=False,
    )

    op.create_table(
        "campaign_world_entry_characters",
        sa.Column("world_entry_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["world_entry_id"],
            ["campaign_world_entries.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("world_entry_id", "character_id"),
    )
    op.create_index(
        "ix_campaign_world_entry_characters_character_id",
        "campaign_world_entry_characters",
        ["character_id"],
        unique=False,
    )

    op.create_table(
        "campaign_adventure_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("adventure_entry_id", sa.Uuid(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
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
            "revision > 0",
            name="ck_campaign_adventure_overrides_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["adventure_entry_id"],
            ["adventure_entries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "adventure_entry_id",
            name="uq_campaign_adventure_overrides_campaign_entry",
        ),
    )
    op.create_index(
        "ix_campaign_adventure_overrides_campaign_id",
        "campaign_adventure_overrides",
        ["campaign_id"],
        unique=False,
    )
    op.create_index(
        "ix_campaign_adventure_overrides_adventure_entry_id",
        "campaign_adventure_overrides",
        ["adventure_entry_id"],
        unique=False,
    )

    op.create_table(
        "campaign_runtime_context",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("current_adventure_scene_entry_id", sa.Uuid(), nullable=True),
        sa.Column("current_runtime_scene_entry_id", sa.Uuid(), nullable=True),
        sa.Column("current_situation", sa.Text(), nullable=True),
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
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
            "NOT (current_adventure_scene_entry_id IS NOT NULL AND current_runtime_scene_entry_id IS NOT NULL)",
            name="ck_campaign_runtime_context_single_scene",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_campaign_runtime_context_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["current_adventure_scene_entry_id"],
            ["adventure_entries.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["current_runtime_scene_entry_id"],
            ["campaign_world_entries.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("campaign_id"),
    )
    op.create_index(
        "ix_campaign_runtime_context_current_adventure_scene_entry_id",
        "campaign_runtime_context",
        ["current_adventure_scene_entry_id"],
        unique=False,
    )
    op.create_index(
        "ix_campaign_runtime_context_current_runtime_scene_entry_id",
        "campaign_runtime_context",
        ["current_runtime_scene_entry_id"],
        unique=False,
    )

    op.create_table(
        "campaign_world_mutations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("action_kind", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("command_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("created_by_actor_kind", sa.String(length=16), nullable=False),
        sa.Column("created_by_actor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "idempotency_key",
            name="uq_campaign_world_mutations_idempotency",
        ),
    )
    op.create_index(
        "ix_campaign_world_mutations_campaign_id",
        "campaign_world_mutations",
        ["campaign_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_campaign_world_mutations_campaign_id",
        table_name="campaign_world_mutations",
    )
    op.drop_table("campaign_world_mutations")

    op.drop_index(
        "ix_campaign_runtime_context_current_runtime_scene_entry_id",
        table_name="campaign_runtime_context",
    )
    op.drop_index(
        "ix_campaign_runtime_context_current_adventure_scene_entry_id",
        table_name="campaign_runtime_context",
    )
    op.drop_table("campaign_runtime_context")

    op.drop_index(
        "ix_campaign_adventure_overrides_adventure_entry_id",
        table_name="campaign_adventure_overrides",
    )
    op.drop_index(
        "ix_campaign_adventure_overrides_campaign_id",
        table_name="campaign_adventure_overrides",
    )
    op.drop_table("campaign_adventure_overrides")

    op.drop_index(
        "ix_campaign_world_entry_characters_character_id",
        table_name="campaign_world_entry_characters",
    )
    op.drop_table("campaign_world_entry_characters")

    op.drop_index(
        "ix_campaign_world_entries_source_adventure_entry_id",
        table_name="campaign_world_entries",
    )
    op.drop_index(
        "ix_campaign_world_entries_campaign_id",
        table_name="campaign_world_entries",
    )
    op.drop_table("campaign_world_entries")
