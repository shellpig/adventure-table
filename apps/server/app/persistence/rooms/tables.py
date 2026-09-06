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
    Uuid,
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


__all__ = ["room_access_sessions", "rooms"]
