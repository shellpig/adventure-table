from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.campaign_runtime.payloads import (
    CampaignRuntimeError,
    RuntimeEntryKind,
    RuntimeStatePayload,
    RuntimeVisibility,
    dump_runtime_payload,
    parse_runtime_payload,
)
from app.domain.rooms.schemas import StrictModel


class RuntimeEntryVisibilityError(CampaignRuntimeError, ValueError):
    """Raised when visibility and character recipient IDs violate invariants."""


class RuntimeEntryValidationError(CampaignRuntimeError, ValueError):
    """Raised when entry creation or patch validation fails."""


def validate_runtime_visibility_recipients(
    visibility: RuntimeVisibility,
    character_recipient_ids: Sequence[UUID],
) -> None:
    if len(set(character_recipient_ids)) != len(character_recipient_ids):
        raise RuntimeEntryVisibilityError("Character recipients must be unique")
    if visibility == "character":
        if not character_recipient_ids:
            raise RuntimeEntryVisibilityError(
                "Character visibility requires at least one character recipient"
            )
    elif visibility in ("public", "dm_only"):
        if character_recipient_ids:
            raise RuntimeEntryVisibilityError(
                f"{visibility} visibility must not have character recipients"
            )
    else:
        raise RuntimeEntryVisibilityError(f"Unknown visibility: {visibility}")


def validate_entry_quick_add_minima(
    kind: RuntimeEntryKind,
    title: str | None,
    body: str | None,
) -> None:
    title_nonblank = bool(title and title.strip())
    body_nonblank = bool(body and body.strip())

    if kind == "npc":
        if not title_nonblank:
            raise RuntimeEntryValidationError("NPC requires a nonblank title")
    elif kind == "fact":
        if not body_nonblank:
            raise RuntimeEntryValidationError("Fact requires a nonblank body")
    elif kind == "scene":
        if not (title_nonblank or body_nonblank):
            raise RuntimeEntryValidationError("Scene requires at least a nonblank title or body")


class RuntimeWorldEntry(StrictModel):
    id: UUID
    campaign_id: UUID
    kind: RuntimeEntryKind
    title: str | None = None
    body: str | None = None
    state: RuntimeStatePayload
    dm_notes: str | None = None
    visibility: RuntimeVisibility = "public"
    needs_review: bool = False
    source_adventure_entry_id: UUID | None = None
    provenance_json: dict[str, object] | None = None
    revision: int = Field(default=1, ge=1)
    created_by_actor_kind: str
    created_by_actor_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    character_recipient_ids: tuple[UUID, ...] = ()

    @property
    def state_json(self) -> dict[str, object]:
        return dump_runtime_payload(self.state)

    @model_validator(mode="before")
    @classmethod
    def _pre_validate(cls, data: object) -> object:
        if isinstance(data, dict):
            if "state" in data and "state_json" in data:
                raise ValueError("Cannot specify both 'state' and 'state_json'")
            data = dict(data)
            if "state" not in data and "state_json" in data:
                state_json = data.pop("state_json")
                kind = data.get("kind")
                if not isinstance(kind, str):
                    raise ValueError("kind must be specified to parse state_json")
                if not isinstance(state_json, dict):
                    raise ValueError("state_json must be a dictionary")
                data["state"] = parse_runtime_payload(kind, state_json)
        return data

    @model_validator(mode="after")
    def _validate_entry(self) -> Self:
        validate_runtime_visibility_recipients(self.visibility, self.character_recipient_ids)
        return self


class RuntimeWorldEntryCreate(StrictModel):
    kind: RuntimeEntryKind
    title: str | None = Field(default=None, max_length=200)
    body: str | None = None
    state: dict[str, object] = Field(default_factory=dict)
    visibility: RuntimeVisibility = "public"
    character_recipient_ids: tuple[UUID, ...] = ()
    dm_notes: str | None = None
    source_adventure_entry_id: UUID | None = None
    provenance_json: dict[str, object] | None = None
    needs_review: bool = False

    @model_validator(mode="after")
    def _validate_create(self) -> Self:
        validate_entry_quick_add_minima(self.kind, self.title, self.body)
        validate_runtime_visibility_recipients(self.visibility, self.character_recipient_ids)
        parsed = parse_runtime_payload(self.kind, self.state)
        self.state = dump_runtime_payload(parsed)
        return self


class RuntimeWorldEntryPatch(StrictModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=200)
    body: str | None = None
    state: dict[str, object] | None = None
    visibility: RuntimeVisibility | None = None
    character_recipient_ids: tuple[UUID, ...] | None = None
    dm_notes: str | None = None
    source_adventure_entry_id: UUID | None = None
    provenance_json: dict[str, object] | None = None
    needs_review: bool | None = None

    @model_validator(mode="after")
    def _validate_patch(self) -> Self:
        patch_fields = self.model_fields_set - {"expected_revision"}
        if not patch_fields:
            raise ValueError("at least one patch field must be set")
        if "visibility" in self.model_fields_set and self.visibility is None:
            raise ValueError("visibility cannot be null")
        if "state" in self.model_fields_set and self.state is None:
            raise ValueError("state cannot be null")
        if (
            "character_recipient_ids" in self.model_fields_set
            and self.character_recipient_ids is None
        ):
            raise ValueError("character_recipient_ids cannot be null")
        if "needs_review" in self.model_fields_set and self.needs_review is None:
            raise ValueError("needs_review cannot be null")

        if (
            "visibility" in self.model_fields_set
            and "character_recipient_ids" in self.model_fields_set
        ):
            if self.visibility is not None and self.character_recipient_ids is not None:
                validate_runtime_visibility_recipients(
                    self.visibility, self.character_recipient_ids
                )

        return self


class RuntimeWorldEntryDmView(StrictModel):
    id: UUID
    campaign_id: UUID
    kind: RuntimeEntryKind
    title: str | None = None
    body: str | None = None
    state: RuntimeStatePayload
    visibility: RuntimeVisibility
    dm_notes: str | None = None
    needs_review: bool = False
    source_adventure_entry_id: UUID | None = None
    provenance_json: dict[str, object] | None = None
    character_recipient_ids: tuple[UUID, ...] = ()
    revision: int = Field(ge=1)
    created_by_actor_kind: str
    created_by_actor_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class RuntimeWorldEntryPlayerView(StrictModel):
    id: UUID
    campaign_id: UUID
    kind: RuntimeEntryKind
    title: str | None = None
    body: str | None = None
    state: RuntimeStatePayload
    visibility: RuntimeVisibility
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


__all__ = [
    "CampaignRuntimeError",
    "RuntimeEntryValidationError",
    "RuntimeEntryVisibilityError",
    "RuntimeWorldEntry",
    "RuntimeWorldEntryCreate",
    "RuntimeWorldEntryDmView",
    "RuntimeWorldEntryPatch",
    "RuntimeWorldEntryPlayerView",
    "validate_entry_quick_add_minima",
    "validate_runtime_visibility_recipients",
]
