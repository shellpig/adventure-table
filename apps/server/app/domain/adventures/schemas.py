from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.domain.adventures.payloads import (
    AdventureEntryPayload,
    AdventureEntryPayloadError,
)
from app.domain.rooms.schemas import StrictModel

AdventureStatus = Literal["draft", "finalized", "archived"]

AdventureEntryKind = Literal[
    "section",
    "scene",
    "npc",
    "item",
    "monster_ref",
    "quest",
    "secret",
    "dm_note",
    "suggested_check",
    "map",
    "lore",
    "other",
]

AdventureEntryVisibility = Literal["public", "dm_only"]


class AdventureDefinition(StrictModel):
    id: UUID
    room_id: UUID
    name: str
    summary: str | None
    ruleset: str
    status: AdventureStatus
    created_at: datetime
    updated_at: datetime


class AdventureEntry(StrictModel):
    id: UUID
    adventure_id: UUID
    parent_entry_id: UUID | None
    kind: AdventureEntryKind
    title: str | None
    body: str | None
    data: AdventureEntryPayload
    visibility: AdventureEntryVisibility
    sort_order: int
    provenance: dict[str, object] | None = None
    source_ref: dict[str, object] | None = None
    created_at: datetime
    updated_at: datetime


class AdventureDefinitionCreate(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    summary: str | None = None
    ruleset: str = Field(default="dnd5e-2014", min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized


class AdventureDefinitionPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    summary: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is not None:
            normalized = value.strip()
            if not normalized:
                raise ValueError("name cannot be blank")
            return normalized
        return None

    @model_validator(mode="after")
    def validate_at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be set")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class AdventureEntryCreate(StrictModel):
    kind: AdventureEntryKind
    title: str | None = Field(default=None, max_length=200)
    body: str | None = None
    data: dict[str, object] = Field(default_factory=dict)
    visibility: AdventureEntryVisibility = "public"
    parent_entry_id: UUID | None = None
    sort_order: int | None = None


class AdventureEntryPatch(StrictModel):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = None
    data: dict[str, object] | None = None
    visibility: AdventureEntryVisibility | None = None
    parent_entry_id: UUID | None = None

    @model_validator(mode="after")
    def validate_at_least_one_field(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be set")
        if "visibility" in self.model_fields_set and self.visibility is None:
            raise ValueError("visibility cannot be null")
        if "data" in self.model_fields_set and self.data is None:
            raise ValueError("data cannot be null")
        return self


class AdventureEntryReorder(StrictModel):
    entry_ids: tuple[UUID, ...] = Field(min_length=1)


class AdventureNotFoundError(Exception):
    pass


class AdventureForbiddenError(Exception):
    pass


class AdventureEntryNotFoundError(Exception):
    pass


class AdventureArchivedError(Exception):
    pass


class AdventureEntryParentError(Exception):
    pass


__all__ = [
    "AdventureArchivedError",
    "AdventureDefinition",
    "AdventureDefinitionCreate",
    "AdventureDefinitionPatch",
    "AdventureEntry",
    "AdventureEntryCreate",
    "AdventureEntryKind",
    "AdventureEntryNotFoundError",
    "AdventureEntryParentError",
    "AdventureEntryPatch",
    "AdventureEntryPayloadError",
    "AdventureEntryReorder",
    "AdventureEntryVisibility",
    "AdventureForbiddenError",
    "AdventureNotFoundError",
    "AdventureStatus",
]
