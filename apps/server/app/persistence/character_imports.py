from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String, Table, Uuid, func

from app.db import metadata


ImportLandingMode = Literal["character", "draft", "draft_with_history_loss"]


character_import_records = Table(
    "character_import_records",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "character_id",
        Uuid(as_uuid=True),
        ForeignKey("characters.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "draft_id",
        Uuid(as_uuid=True),
        ForeignKey("character_build_drafts.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("source_character_id", Uuid(as_uuid=True), nullable=False),
    Column("source_export_id", Uuid(as_uuid=True), nullable=False),
    Column("landing_mode", String(32), nullable=False),
    Column("imported_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "character_id IS NULL OR draft_id IS NULL",
        name="ck_character_import_records_single_target",
    ),
)

Index(
    "ix_character_import_records_source_character_id",
    character_import_records.c.source_character_id,
)
Index(
    "ix_character_import_records_source_export_id",
    character_import_records.c.source_export_id,
)


__all__ = ["ImportLandingMode", "character_import_records"]
