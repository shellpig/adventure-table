from __future__ import annotations

from datetime import datetime
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.domain.adventures.payloads import (
    AdventureEntryPayload,
    AdventureEntryPayloadError,
    parse_entry_payload,
)
from app.domain.adventures.schemas import AdventureEntryKind
from app.domain.rooms.schemas import StrictModel
from app.persistence.adventure_imports.repository import (
    StoredAdventureImport,
    StoredAdventureImportDraft,
    StoredAdventureImportSource,
)

ImportStatus = Literal["source", "drafting", "review", "finalized", "cancelled"]
SourceKind = Literal["paste", "txt", "markdown", "pdf", "docx", "url"]
DraftProvenance = Literal[
    "source_document",
    "user_explicit",
    "user_approximation",
    "ai_generated",
]
WarningLevel = Literal["info", "warning", "blocking"]


class DraftSourceRef(StrictModel):
    source_id: UUID
    locator: str | None = None


class DraftEntry(StrictModel):
    entry_id: str = Field(min_length=1)
    entry_kind: AdventureEntryKind
    payload: AdventureEntryPayload
    parent_entry_id: str | None = None
    provenance: DraftProvenance = "source_document"
    source_ref: DraftSourceRef | None = None
    note: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _parse_dict_payload(cls, data: object) -> object:
        if isinstance(data, dict):
            entry_kind = data.get("entry_kind")
            payload = data.get("payload")
            if isinstance(entry_kind, str) and isinstance(payload, dict):
                try:
                    payload_parsed = parse_entry_payload(entry_kind, payload)
                    data = dict(data)
                    data["payload"] = payload_parsed
                except AdventureEntryPayloadError as exc:
                    raise ValueError(str(exc)) from exc
        return data

    @model_validator(mode="after")
    def _check_payload_kind(self) -> Self:
        if self.payload.kind != self.entry_kind:
            raise ValueError(
                f"payload kind '{self.payload.kind}' does not match entry_kind '{self.entry_kind}'"
            )
        return self


class DraftWarning(StrictModel):
    warning_id: str = Field(min_length=1)
    level: WarningLevel
    code: str
    message: str
    entry_id: str | None = None
    source_id: UUID | None = None


class DraftQuestion(StrictModel):
    question_id: str = Field(min_length=1)
    message: str
    entry_id: str | None = None
    answer: str | None = None


def validate_draft_warnings(warnings: list[DraftWarning]) -> list[DraftWarning]:
    seen: set[str] = set()
    for w in warnings:
        if w.warning_id in seen:
            raise ValueError(f"Duplicate warning_id: {w.warning_id}")
        seen.add(w.warning_id)
    return warnings


class ImportDraft(StrictModel):
    schema_version: Literal[1] = 1
    entries: list[DraftEntry] = Field(default_factory=list)
    questions: list[DraftQuestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        entry_ids: set[str] = set()
        for entry in self.entries:
            if entry.entry_id in entry_ids:
                raise ValueError(f"Duplicate entry_id: {entry.entry_id}")
            entry_ids.add(entry.entry_id)

        for entry in self.entries:
            if entry.parent_entry_id is not None:
                if entry.parent_entry_id == entry.entry_id:
                    raise ValueError(
                        f"Entry {entry.entry_id} cannot reference itself as parent_entry_id"
                    )
                if entry.parent_entry_id not in entry_ids:
                    raise ValueError(
                        f"Entry {entry.entry_id} references non-existent parent_entry_id {entry.parent_entry_id}"
                    )

        question_ids: set[str] = set()
        for q in self.questions:
            if q.question_id in question_ids:
                raise ValueError(f"Duplicate question_id: {q.question_id}")
            question_ids.add(q.question_id)

        return self


class AdventureImport(StrictModel):
    id: UUID
    room_id: UUID
    name: str
    status: ImportStatus
    target_adventure_id: UUID | None
    revision: int
    created_at: datetime
    updated_at: datetime


class AdventureImportSource(StrictModel):
    id: UUID
    import_id: UUID
    asset_id: UUID | None
    source_kind: SourceKind
    source_url: str | None
    metadata_json: dict[str, object]
    sha256: str
    text_length: int
    created_at: datetime


class SourceChunk(StrictModel):
    source_id: UUID
    offset: int
    text: str
    total_length: int
    next_offset: int | None


class AdventureImportDraft(StrictModel):
    import_id: UUID
    draft: ImportDraft
    warnings: list[DraftWarning] = Field(default_factory=list)
    revision: int
    updated_at: datetime

    @field_validator("warnings")
    @classmethod
    def _validate_warnings(cls, warnings: list[DraftWarning]) -> list[DraftWarning]:
        return validate_draft_warnings(warnings)


def adventure_import_from_stored(stored: StoredAdventureImport) -> AdventureImport:
    return AdventureImport(
        id=stored.id,
        room_id=stored.room_id,
        name=stored.name,
        status=cast(ImportStatus, stored.status),
        target_adventure_id=stored.target_adventure_id,
        revision=stored.revision,
        created_at=stored.created_at,
        updated_at=stored.updated_at,
    )


def adventure_import_source_from_stored(
    stored: StoredAdventureImportSource,
) -> AdventureImportSource:
    return AdventureImportSource(
        id=stored.id,
        import_id=stored.import_id,
        asset_id=stored.asset_id,
        source_kind=cast(SourceKind, stored.source_kind),
        source_url=stored.source_url,
        metadata_json=stored.metadata_json,
        sha256=stored.sha256,
        text_length=stored.text_length,
        created_at=stored.created_at,
    )


def adventure_import_draft_from_stored(
    stored: StoredAdventureImportDraft,
) -> AdventureImportDraft:
    draft = ImportDraft.model_validate(stored.draft_json)
    warnings = [DraftWarning.model_validate(w) for w in stored.warnings_json]
    return AdventureImportDraft(
        import_id=stored.import_id,
        draft=draft,
        warnings=warnings,
        revision=stored.revision,
        updated_at=stored.updated_at,
    )


__all__ = [
    "AdventureImport",
    "AdventureImportDraft",
    "AdventureImportSource",
    "DraftEntry",
    "DraftProvenance",
    "DraftQuestion",
    "DraftSourceRef",
    "DraftWarning",
    "ImportDraft",
    "ImportStatus",
    "SourceChunk",
    "SourceKind",
    "WarningLevel",
    "adventure_import_draft_from_stored",
    "adventure_import_from_stored",
    "adventure_import_source_from_stored",
    "validate_draft_warnings",
]
