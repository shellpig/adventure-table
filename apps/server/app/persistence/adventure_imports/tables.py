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
    UniqueConstraint,
    Uuid,
    func,
)

from app.db import metadata


adventure_imports = Table(
    "adventure_imports",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("room_id", Uuid(), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(200), nullable=False),
    Column("status", String(16), nullable=False, server_default="source"),
    Column(
        "target_adventure_id",
        Uuid(),
        ForeignKey("adventure_definitions.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("revision", Integer(), nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "status IN ('source', 'drafting', 'review', 'finalized', 'cancelled')",
        name="ck_adventure_imports_status",
    ),
)
Index("ix_adventure_imports_room_id", adventure_imports.c.room_id)


adventure_import_sources = Table(
    "adventure_import_sources",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column(
        "import_id",
        Uuid(),
        ForeignKey("adventure_imports.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "asset_id",
        Uuid(),
        ForeignKey("room_assets.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("source_kind", String(16), nullable=False),
    Column("source_url", Text(), nullable=True),
    Column("normalized_text", Text(), nullable=False),
    Column("metadata_json", JSON(), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "source_kind IN ('paste', 'txt', 'markdown', 'pdf', 'docx', 'url')",
        name="ck_adventure_import_sources_source_kind",
    ),
    UniqueConstraint(
        "import_id",
        "sha256",
        name="uq_adventure_import_sources_import_sha256",
    ),
)
Index("ix_adventure_import_sources_import_id", adventure_import_sources.c.import_id)


adventure_import_drafts = Table(
    "adventure_import_drafts",
    metadata,
    Column(
        "import_id",
        Uuid(),
        ForeignKey("adventure_imports.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    ),
    Column("draft_json", JSON(), nullable=False),
    Column("warnings_json", JSON(), nullable=False),
    Column("revision", Integer(), nullable=False, server_default="0"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
