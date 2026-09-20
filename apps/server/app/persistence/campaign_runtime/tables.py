from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
)

from app.db import metadata


campaign_world_entries = Table(
    "campaign_world_entries",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("campaign_id", Uuid(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("title", String(200), nullable=True),
    Column("body", Text(), nullable=True),
    Column("state_json", JSON(), nullable=False),
    Column("dm_notes", Text(), nullable=True),
    Column("visibility", String(16), nullable=False, server_default="public"),
    Column("needs_review", Boolean(), nullable=False, server_default=false()),
    Column(
        "source_adventure_entry_id",
        Uuid(),
        ForeignKey("adventure_entries.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("provenance_json", JSON(), nullable=True),
    Column("revision", BigInteger(), nullable=False, server_default="1"),
    Column("created_by_actor_kind", String(16), nullable=False),
    Column("created_by_actor_id", Uuid(), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("archived_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "kind IN ('scene', 'npc', 'item', 'quest', 'fact', 'secret', 'hazard', 'other')",
        name="ck_campaign_world_entries_kind",
    ),
    CheckConstraint(
        "visibility IN ('public', 'dm_only', 'character')",
        name="ck_campaign_world_entries_visibility",
    ),
    CheckConstraint(
        "revision > 0",
        name="ck_campaign_world_entries_revision_positive",
    ),
)
Index("ix_campaign_world_entries_campaign_id", campaign_world_entries.c.campaign_id)
Index(
    "ix_campaign_world_entries_source_adventure_entry_id",
    campaign_world_entries.c.source_adventure_entry_id,
)


campaign_world_entry_characters = Table(
    "campaign_world_entry_characters",
    metadata,
    Column(
        "world_entry_id",
        Uuid(),
        ForeignKey("campaign_world_entries.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column(
        "character_id",
        Uuid(),
        ForeignKey("characters.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index(
    "ix_campaign_world_entry_characters_character_id",
    campaign_world_entry_characters.c.character_id,
)


campaign_adventure_overrides = Table(
    "campaign_adventure_overrides",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("campaign_id", Uuid(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column(
        "adventure_entry_id",
        Uuid(),
        ForeignKey("adventure_entries.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("state_json", JSON(), nullable=False),
    Column("note", Text(), nullable=True),
    Column("needs_review", Boolean(), nullable=False, server_default=false()),
    Column("revision", BigInteger(), nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "campaign_id",
        "adventure_entry_id",
        name="uq_campaign_adventure_overrides_campaign_entry",
    ),
    CheckConstraint(
        "revision > 0",
        name="ck_campaign_adventure_overrides_revision_positive",
    ),
)
Index(
    "ix_campaign_adventure_overrides_campaign_id",
    campaign_adventure_overrides.c.campaign_id,
)
Index(
    "ix_campaign_adventure_overrides_adventure_entry_id",
    campaign_adventure_overrides.c.adventure_entry_id,
)


campaign_runtime_context = Table(
    "campaign_runtime_context",
    metadata,
    Column(
        "campaign_id",
        Uuid(),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column(
        "current_adventure_scene_entry_id",
        Uuid(),
        ForeignKey("adventure_entries.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "current_runtime_scene_entry_id",
        Uuid(),
        ForeignKey("campaign_world_entries.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("current_situation", Text(), nullable=True),
    Column("revision", BigInteger(), nullable=False, server_default="1"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "NOT (current_adventure_scene_entry_id IS NOT NULL AND current_runtime_scene_entry_id IS NOT NULL)",
        name="ck_campaign_runtime_context_single_scene",
    ),
    CheckConstraint(
        "revision > 0",
        name="ck_campaign_runtime_context_revision_positive",
    ),
)
Index(
    "ix_campaign_runtime_context_current_adventure_scene_entry_id",
    campaign_runtime_context.c.current_adventure_scene_entry_id,
)
Index(
    "ix_campaign_runtime_context_current_runtime_scene_entry_id",
    campaign_runtime_context.c.current_runtime_scene_entry_id,
)


campaign_world_mutations = Table(
    "campaign_world_mutations",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("campaign_id", Uuid(), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("idempotency_key", String(160), nullable=False),
    Column("action_kind", String(64), nullable=False),
    Column("target_id", Uuid(), nullable=True),
    Column("command_payload", JSON(), nullable=False),
    Column("result_payload", JSON(), nullable=False),
    Column("created_by_actor_kind", String(16), nullable=False),
    Column("created_by_actor_id", Uuid(), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "campaign_id",
        "idempotency_key",
        name="uq_campaign_world_mutations_idempotency",
    ),
)
Index("ix_campaign_world_mutations_campaign_id", campaign_world_mutations.c.campaign_id)
