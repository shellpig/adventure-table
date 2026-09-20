from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Uuid,
    func,
)

from app.db import metadata


room_assets = Table(
    "room_assets",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("room_id", Uuid(), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("storage_key", String(512), nullable=False, unique=True),
    Column("original_filename", String(255), nullable=False),
    Column("mime_type", String(127), nullable=False),
    Column("size_bytes", BigInteger(), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("visibility", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "kind IN ('image', 'source_document')",
        name="ck_room_assets_kind",
    ),
    CheckConstraint(
        "visibility IN ('room', 'dm_only')",
        name="ck_room_assets_visibility",
    ),
)
Index("ix_room_assets_room_id", room_assets.c.room_id)
