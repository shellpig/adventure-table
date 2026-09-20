from __future__ import annotations

from typing import Annotated, Literal
from pydantic import Field, TypeAdapter, ValidationError

from app.domain.rooms.schemas import StrictModel


class AdventureEntryPayloadError(Exception):
    pass


class SectionPayload(StrictModel):
    kind: Literal["section"] = "section"


class ScenePayload(StrictModel):
    kind: Literal["scene"] = "scene"
    read_aloud: str | None = None
    dm_summary: str | None = None
    exits: tuple[str, ...] = ()


class NpcPayload(StrictModel):
    kind: Literal["npc"] = "npc"
    role: str | None = None
    disposition: Literal["friendly", "neutral", "hostile", "unknown"] = "unknown"
    monster_template_ref: str | None = None


class ItemPayload(StrictModel):
    kind: Literal["item"] = "item"
    rarity: str | None = None
    value_gp: int | None = Field(default=None, ge=0)
    is_magic: bool = False


class MonsterRefPayload(StrictModel):
    kind: Literal["monster_ref"] = "monster_ref"
    monster_template_ref: str = Field(min_length=1)
    count: int = Field(default=1, ge=1)
    notes: str | None = None


class QuestPayload(StrictModel):
    kind: Literal["quest"] = "quest"
    objective: str = Field(min_length=1)
    reward: str | None = None


class SecretPayload(StrictModel):
    kind: Literal["secret"] = "secret"
    reveal_condition: str | None = None


class DmNotePayload(StrictModel):
    kind: Literal["dm_note"] = "dm_note"


class SuggestedCheckPayload(StrictModel):
    kind: Literal["suggested_check"] = "suggested_check"
    ability: Literal["str", "dex", "con", "int", "wis", "cha"]
    skill: str | None = None
    dc: int = Field(ge=1, le=40)
    on_success: str | None = None
    on_failure: str | None = None


class MapPayload(StrictModel):
    kind: Literal["map"] = "map"
    caption: str | None = None
    region_labels: tuple[str, ...] = ()


class LorePayload(StrictModel):
    kind: Literal["lore"] = "lore"
    topic: str | None = None


class OtherPayload(StrictModel):
    kind: Literal["other"] = "other"
    data: dict[str, str | int | bool] = Field(default_factory=dict)


AdventureEntryPayload = Annotated[
    SectionPayload
    | ScenePayload
    | NpcPayload
    | ItemPayload
    | MonsterRefPayload
    | QuestPayload
    | SecretPayload
    | DmNotePayload
    | SuggestedCheckPayload
    | MapPayload
    | LorePayload
    | OtherPayload,
    Field(discriminator="kind"),
]

_ENTRY_PAYLOAD_ADAPTER: TypeAdapter[AdventureEntryPayload] = TypeAdapter(AdventureEntryPayload)

KNOWN_ENTRY_KINDS: frozenset[str] = frozenset(
    {
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
    }
)


def parse_entry_payload(kind: str, data_json: dict[str, object]) -> AdventureEntryPayload:
    if not isinstance(data_json, dict):
        raise AdventureEntryPayloadError("Entry data must be a dictionary")
    if "kind" in data_json and data_json["kind"] != kind:
        raise AdventureEntryPayloadError(
            f"Payload kind '{data_json['kind']}' does not match entry kind '{kind}'"
        )
    if kind not in KNOWN_ENTRY_KINDS:
        raise AdventureEntryPayloadError(f"Unknown entry kind: {kind}")

    payload_dict = dict(data_json)
    payload_dict["kind"] = kind
    try:
        return _ENTRY_PAYLOAD_ADAPTER.validate_python(payload_dict)
    except ValidationError as exc:
        raise AdventureEntryPayloadError(str(exc)) from exc


def dump_entry_payload(payload: AdventureEntryPayload) -> dict[str, object]:
    return payload.model_dump(mode="json")


__all__ = [
    "AdventureEntryPayload",
    "AdventureEntryPayloadError",
    "DmNotePayload",
    "ItemPayload",
    "KNOWN_ENTRY_KINDS",
    "LorePayload",
    "MapPayload",
    "MonsterRefPayload",
    "NpcPayload",
    "OtherPayload",
    "QuestPayload",
    "ScenePayload",
    "SectionPayload",
    "SecretPayload",
    "SuggestedCheckPayload",
    "dump_entry_payload",
    "parse_entry_payload",
]
