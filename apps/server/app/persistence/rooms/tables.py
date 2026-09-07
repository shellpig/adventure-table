from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
)

from app.db import metadata


rooms = Table(
    "rooms",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("code", String(10), nullable=False, unique=True),
    Column("name", String(120), nullable=False),
    Column("password_salt", LargeBinary(32), nullable=False),
    Column("password_hash", LargeBinary(64), nullable=False),
    Column("owner_key_hash", LargeBinary(32), nullable=False),
    Column("dm_key_hash", LargeBinary(32), nullable=False),
    Column(
        "active_campaign_id",
        Uuid(),
        ForeignKey(
            "campaigns.id",
            name="fk_rooms_active_campaign_id_campaigns",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

room_access_sessions = Table(
    "room_access_sessions",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("room_id", Uuid(), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
    Column("authority", String(16), nullable=False),
    Column("token_hash", LargeBinary(32), nullable=False, unique=True),
    Column("display_name", String(100), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "authority IN ('member', 'dm', 'owner')",
        name="ck_room_access_sessions_authority",
    ),
)
Index("ix_room_access_sessions_room_id", room_access_sessions.c.room_id)

room_characters = Table(
    "room_characters",
    metadata,
    Column("room_id", Uuid(), ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "character_id",
        Uuid(),
        ForeignKey("characters.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("character_id", name="uq_room_characters_character_id"),
)
Index("ix_room_characters_room_id", room_characters.c.room_id)

room_builder_drafts = Table(
    "room_builder_drafts",
    metadata,
    Column("room_id", Uuid(), ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "draft_id",
        Uuid(),
        ForeignKey("character_build_drafts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("draft_id", name="uq_room_builder_drafts_draft_id"),
)
Index("ix_room_builder_drafts_room_id", room_builder_drafts.c.room_id)

campaigns = Table(
    "campaigns",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("room_id", Uuid(), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(120), nullable=False),
    Column("ruleset", String(80), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "status IN ('draft', 'active', 'completed', 'archived')",
        name="ck_campaigns_status",
    ),
)
Index("ix_campaigns_room_id", campaigns.c.room_id)

campaign_roster_entries = Table(
    "campaign_roster_entries",
    metadata,
    Column(
        "campaign_id",
        Uuid(),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "character_id",
        Uuid(),
        ForeignKey("characters.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("status", String(16), nullable=False),
    Column("added_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "status IN ('active', 'inactive', 'retired', 'dead')",
        name="ck_campaign_roster_entries_status",
    ),
)
Index(
    "ix_campaign_roster_entries_character_id",
    campaign_roster_entries.c.character_id,
)


__all__ = [
    "campaign_roster_entries",
    "campaigns",
    "room_access_sessions",
    "room_builder_drafts",
    "room_characters",
    "rooms",
]
