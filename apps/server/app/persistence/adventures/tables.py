from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    Uuid,
    func,
)

from app.db import metadata


adventure_definitions = Table(
    "adventure_definitions",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("room_id", Uuid(), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(160), nullable=False),
    Column("summary", Text(), nullable=True),
    Column("ruleset", String(64), nullable=False, server_default="dnd5e-2014"),
    Column("status", String(16), nullable=False, server_default="draft"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "status IN ('draft', 'finalized', 'archived')",
        name="ck_adventure_definitions_status",
    ),
)
Index("ix_adventure_definitions_room_id", adventure_definitions.c.room_id)


adventure_entries = Table(
    "adventure_entries",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column(
        "adventure_id",
        Uuid(),
        ForeignKey("adventure_definitions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "parent_entry_id",
        Uuid(),
        ForeignKey("adventure_entries.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("kind", String(32), nullable=False),
    Column("title", String(200), nullable=True),
    Column("body", Text(), nullable=True),
    Column("data_json", JSON(), nullable=False),
    Column("visibility", String(16), nullable=False, server_default="public"),
    Column("sort_order", Integer(), nullable=False, server_default="0"),
    Column("provenance_json", JSON(), nullable=True),
    Column("source_ref_json", JSON(), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "kind IN ('section', 'scene', 'npc', 'item', 'monster_ref', 'quest', 'secret', "
        "'dm_note', 'suggested_check', 'map', 'lore', 'other')",
        name="ck_adventure_entries_kind",
    ),
    CheckConstraint(
        "visibility IN ('public', 'dm_only')",
        name="ck_adventure_entries_visibility",
    ),
)
Index("ix_adventure_entries_adventure_id", adventure_entries.c.adventure_id)
Index("ix_adventure_entries_parent_entry_id", adventure_entries.c.parent_entry_id)


adventure_entry_assets = Table(
    "adventure_entry_assets",
    metadata,
    Column(
        "adventure_entry_id",
        Uuid(),
        ForeignKey("adventure_entries.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column(
        "asset_id",
        Uuid(),
        ForeignKey("room_assets.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
    ),
    Column("role", String(16), nullable=False),
    Column("sort_order", Integer(), nullable=False, server_default="0"),
    CheckConstraint(
        "role IN ('image', 'map', 'source', 'attachment')",
        name="ck_adventure_entry_assets_role",
    ),
)


campaign_adventure_links = Table(
    "campaign_adventure_links",
    metadata,
    Column(
        "campaign_id",
        Uuid(),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column(
        "adventure_id",
        Uuid(),
        ForeignKey("adventure_definitions.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
    ),
    Column("sort_order", Integer(), nullable=False, server_default="0"),
    Column("attached_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
