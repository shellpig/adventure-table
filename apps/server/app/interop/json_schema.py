from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionKind(StrEnum):
    LEGACY = "legacy"
    CREATE = "create"
    LEVEL_UP = "level_up"
    BUILD_EDIT = "build_edit"
    CORRECTION = "correction"


class PackRequirement(StrictModel):
    pack: str = Field(min_length=1)
    version: str = Field(min_length=1)


class SourceApp(StrictModel):
    name: Literal["adventure-table"] = "adventure-table"
    channel: Literal["web", "standalone"]
    commit: str | None = None
    build: str | None = None


class Envelope(StrictModel):
    schema_version: Literal["unstable"] = "unstable"
    schema_status: Literal["unstable", "locked"] = "unstable"
    ruleset: str = Field(min_length=1)
    content_requirements: list[PackRequirement]
    stable_key_refs_summary: int = Field(ge=0)
    source_character_id: UUID
    source_export_id: UUID
    source_app: SourceApp
    exported_at: datetime


class ExportedVersion(StrictModel):
    version_no: int = Field(ge=1)
    version_kind: VersionKind
    parent_version_no: int | None = Field(default=None, ge=1)
    superseded_by_version_no: int | None = Field(default=None, ge=1)
    change_note: str | None = None
    build_payload: dict[str, Any]
    builder_provenance: dict[str, Any] | None = None
    created_at: datetime


class ExportedCharacter(StrictModel):
    name: str = Field(min_length=1)
    ruleset: str = Field(min_length=1)


class ExportedState(StrictModel):
    state_payload: dict[str, Any]


class ExportPayload(StrictModel):
    character: ExportedCharacter
    current_version_no: int = Field(ge=1)
    versions: list[ExportedVersion]
    current_state: ExportedState


class CharacterExport(StrictModel):
    envelope: Envelope
    payload: ExportPayload
