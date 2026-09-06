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


class _EnvelopeFields(StrictModel):
    ruleset: str = Field(min_length=1)
    content_requirements: list[PackRequirement]
    stable_key_refs_summary: int = Field(ge=0)
    source_character_id: UUID
    source_export_id: UUID
    source_app: SourceApp
    exported_at: datetime


class LegacyM03Envelope(_EnvelopeFields):
    schema_version: Literal["unstable"] = "unstable"
    # M03 reserved `locked` before a locked version existed. Keep accepting it
    # only on the legacy parser so previously produced files remain readable.
    schema_status: Literal["unstable", "locked"] = "unstable"


class CharacterExportV1Envelope(_EnvelopeFields):
    schema_version: Literal["1"] = "1"
    schema_status: Literal["locked"] = "locked"
    export_type: Literal["character"] = "character"


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


class LegacyM03CharacterExport(StrictModel):
    envelope: LegacyM03Envelope
    payload: ExportPayload


class CharacterExportV1(StrictModel):
    envelope: CharacterExportV1Envelope
    payload: ExportPayload


ParsedCharacterExport = LegacyM03CharacterExport | CharacterExportV1


def parse_character_export(payload: Any) -> ParsedCharacterExport:
    """Parse either the frozen M03 unstable envelope or locked v1."""

    schema_version = None
    if isinstance(payload, dict):
        envelope = payload.get("envelope")
        if isinstance(envelope, dict):
            schema_version = envelope.get("schema_version")
    if schema_version == "unstable":
        return LegacyM03CharacterExport.model_validate(payload)
    return CharacterExportV1.model_validate(payload)


def normalize_character_export(document: ParsedCharacterExport) -> CharacterExportV1:
    """Normalize every accepted Character JSON document to the locked v1 DTO."""

    if isinstance(document, CharacterExportV1):
        return document
    envelope = document.envelope.model_dump(
        exclude={"schema_version", "schema_status"}
    )
    return CharacterExportV1(
        envelope=CharacterExportV1Envelope(**envelope),
        payload=document.payload,
    )


# Compatibility names used by the committed M03 fixture corpus and older
# direct service/tests. Keep both aliases on the same legacy schema; new
# production export code must use CharacterExportV1/CharacterExportV1Envelope.
CharacterExport = LegacyM03CharacterExport
Envelope = LegacyM03Envelope
