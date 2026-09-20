from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, TypeAdapter, ValidationError, field_validator, model_validator

from app.domain.rooms.schemas import StrictModel


class CampaignRuntimeError(Exception):
    """Base exception for campaign runtime domain."""


class RuntimeEntryPayloadError(CampaignRuntimeError, ValueError):
    """Raised when runtime entry state payload is invalid."""


RuntimeEntryKind = Literal[
    "scene",
    "npc",
    "item",
    "quest",
    "fact",
    "secret",
    "hazard",
    "other",
]

KNOWN_RUNTIME_ENTRY_KINDS: frozenset[str] = frozenset(
    {
        "scene",
        "npc",
        "item",
        "quest",
        "fact",
        "secret",
        "hazard",
        "other",
    }
)

RuntimeVisibility = Literal["public", "dm_only", "character"]

KNOWN_RUNTIME_VISIBILITIES: frozenset[str] = frozenset(
    {
        "public",
        "dm_only",
        "character",
    }
)

RuntimeItemHolderKind = Literal["scene", "npc", "character", "party", "unknown"]

KNOWN_ITEM_HOLDER_KINDS: frozenset[str] = frozenset(
    {
        "scene",
        "npc",
        "character",
        "party",
        "unknown",
    }
)


class RuntimeItemHolderRef(StrictModel):
    kind: RuntimeItemHolderKind
    target_id: UUID | None = None

    @model_validator(mode="after")
    def _validate_target_id(self) -> Self:
        if self.kind in {"scene", "npc", "character"}:
            if self.target_id is None:
                raise ValueError(f"target_id is required for holder kind '{self.kind}'")
        elif self.target_id is not None:
            raise ValueError(f"target_id must not be set for holder kind '{self.kind}'")
        return self


class RuntimeScenePayload(StrictModel):
    kind: Literal["scene"] = "scene"


class RuntimeNpcPayload(StrictModel):
    kind: Literal["npc"] = "npc"
    monster_instance_id: UUID | None = None
    monster_template_ref: str | None = None

    @field_validator("monster_template_ref")
    @classmethod
    def _validate_monster_template_ref(cls, value: str | None) -> str | None:
        if value is not None:
            normalized = value.strip()
            if not normalized:
                raise ValueError("monster_template_ref cannot be blank")
            return normalized
        return None


class RuntimeItemPayload(StrictModel):
    kind: Literal["item"] = "item"
    holder_ref: RuntimeItemHolderRef | None = None


class RuntimeQuestPayload(StrictModel):
    kind: Literal["quest"] = "quest"


class RuntimeFactPayload(StrictModel):
    kind: Literal["fact"] = "fact"


class RuntimeSecretPayload(StrictModel):
    kind: Literal["secret"] = "secret"


class RuntimeHazardPayload(StrictModel):
    kind: Literal["hazard"] = "hazard"


class RuntimeOtherPayload(StrictModel):
    kind: Literal["other"] = "other"
    data: dict[str, str | int | float | bool] = Field(default_factory=dict)


RuntimeStatePayload = Annotated[
    RuntimeScenePayload
    | RuntimeNpcPayload
    | RuntimeItemPayload
    | RuntimeQuestPayload
    | RuntimeFactPayload
    | RuntimeSecretPayload
    | RuntimeHazardPayload
    | RuntimeOtherPayload,
    Field(discriminator="kind"),
]

RuntimeEntryPayload = RuntimeStatePayload

_PAYLOAD_ADAPTER: TypeAdapter[RuntimeStatePayload] = TypeAdapter(RuntimeStatePayload)


def parse_runtime_payload(kind: str, data_json: dict[str, object]) -> RuntimeStatePayload:
    if not isinstance(data_json, dict):
        raise RuntimeEntryPayloadError("Payload data must be a dictionary")
    if "kind" in data_json and data_json["kind"] != kind:
        raise RuntimeEntryPayloadError(
            f"Payload kind '{data_json['kind']}' does not match entry kind '{kind}'"
        )
    if kind not in KNOWN_RUNTIME_ENTRY_KINDS:
        raise RuntimeEntryPayloadError(f"Unknown runtime entry kind: {kind}")

    payload_dict = dict(data_json)
    payload_dict["kind"] = kind
    try:
        return _PAYLOAD_ADAPTER.validate_python(payload_dict)
    except ValidationError as exc:
        raise RuntimeEntryPayloadError(str(exc)) from exc


def dump_runtime_payload(payload: RuntimeStatePayload) -> dict[str, object]:
    return payload.model_dump(mode="json")


__all__ = [
    "CampaignRuntimeError",
    "KNOWN_ITEM_HOLDER_KINDS",
    "KNOWN_RUNTIME_ENTRY_KINDS",
    "KNOWN_RUNTIME_VISIBILITIES",
    "RuntimeEntryKind",
    "RuntimeEntryPayload",
    "RuntimeEntryPayloadError",
    "RuntimeFactPayload",
    "RuntimeHazardPayload",
    "RuntimeItemHolderKind",
    "RuntimeItemHolderRef",
    "RuntimeItemPayload",
    "RuntimeNpcPayload",
    "RuntimeOtherPayload",
    "RuntimeQuestPayload",
    "RuntimeScenePayload",
    "RuntimeSecretPayload",
    "RuntimeStatePayload",
    "RuntimeVisibility",
    "dump_runtime_payload",
    "parse_runtime_payload",
]
