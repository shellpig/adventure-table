from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.domain.rooms.schemas import StrictModel

MonsterSourceKind = Literal["builtin", "custom"]


class MonsterLibrarySummaryView(StrictModel):
    ref: str
    name: str
    names: dict[str, str] = Field(default_factory=dict)
    name_is_custom: bool = False
    source_kind: MonsterSourceKind
    source_key: str | None = None
    size: str | None = None
    type: str | None = None
    alignment: str | None = None
    armor_class: int | None = None
    max_hp: int | None = None
    challenge_rating: float | None = None
    archived_at: datetime | None = None
    revision: int | None = None


class MonsterLibraryDetailView(StrictModel):
    ref: str
    name: str
    names: dict[str, str] = Field(default_factory=dict)
    name_is_custom: bool = False
    source_kind: MonsterSourceKind
    source_key: str | None = None
    rules: dict[str, object]
    presentation: dict[str, object] = Field(default_factory=dict)
    revision: int | None = None
    archived_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CustomMonsterTraitInput(StrictModel):
    name: str = Field(min_length=1)
    desc: str | None = None
    description: str | None = None
    attack_bonus: int | None = None
    damage: list[dict[str, object]] | None = None
    dc: dict[str, object] | None = None
    usage: dict[str, object] | None = None
    spellcasting: dict[str, object] | None = None
    desc_is_english: bool | None = None
    is_english_source: bool | None = None
    names: dict[str, str] | None = None


class CustomMonsterActionInput(StrictModel):
    name: str = Field(min_length=1)
    names: dict[str, str] | None = None
    desc: str | None = None
    description: str | None = None
    kind: Literal["attack", "save", "utility", "other"] | None = None
    attack_kind: Literal[
        "melee_weapon",
        "ranged_weapon",
        "melee_spell",
        "ranged_spell",
        "melee",
        "ranged",
    ] | None = None
    attack_bonus: int | None = None
    target: str | None = None
    range_normal: int | None = Field(default=None, ge=0)
    range_long: int | None = Field(default=None, ge=0)
    reach: int | None = Field(default=None, ge=0)
    damage_dice: str | None = None
    damage_type: str | None = None
    damage_parts: list[dict[str, object]] | None = None
    save_ability: str | None = None
    save_dc: int | None = Field(default=None, ge=0)
    automation_level: Literal["structured", "partial", "dm_adjudication"] | None = None


class CreateCustomMonsterInput(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    armor_class: int = Field(ge=0)
    max_hp: int = Field(ge=1)
    speed: dict[str, str] | str = Field(default_factory=lambda: {"walk": "30 ft."})
    size: str = Field(default="medium")
    type: str = Field(default="humanoid")
    alignment: str = Field(default="unaligned")
    hit_dice: str | None = None
    hit_points_roll: str | None = None
    ability_scores: dict[str, int] | None = None
    proficiencies: list[dict[str, object]] | None = None
    damage_vulnerabilities: list[str] | None = None
    damage_resistances: list[str] | None = None
    damage_immunities: list[str] | None = None
    condition_immunities: list[dict[str, object] | str] | None = None
    senses: dict[str, object] | None = None
    languages: str | None = None
    challenge_rating: float = Field(default=0.0, ge=0)
    xp: int = Field(default=0, ge=0)
    traits: list[CustomMonsterTraitInput] | None = None
    actions: list[CustomMonsterActionInput] | None = None
    bonus_actions: list[CustomMonsterActionInput] | None = None
    reactions: list[CustomMonsterActionInput] | None = None
    legendary_actions: list[CustomMonsterActionInput] | None = None
    description: str | None = None


class CreateCustomMonsterFromContentInput(StrictModel):
    content_key: str = Field(min_length=1)
    name: str | None = None


class CopyCustomMonsterInput(StrictModel):
    expected_revision: int = Field(gt=0)
    name: str | None = None


class PatchCustomMonsterInput(StrictModel):
    expected_revision: int = Field(gt=0)
    name: str | None = None
    armor_class: int | None = Field(default=None, ge=0)
    max_hp: int | None = Field(default=None, ge=1)
    speed: dict[str, str] | str | None = None
    size: str | None = None
    type: str | None = None
    alignment: str | None = None
    ability_scores: dict[str, int] | None = None
    proficiencies: list[dict[str, object]] | None = None
    damage_vulnerabilities: list[str] | None = None
    damage_resistances: list[str] | None = None
    damage_immunities: list[str] | None = None
    condition_immunities: list[dict[str, object] | str] | None = None
    senses: dict[str, object] | None = None
    languages: str | None = None
    challenge_rating: float | None = Field(default=None, ge=0)
    xp: int | None = Field(default=None, ge=0)
    traits: list[CustomMonsterTraitInput] | None = None
    actions: list[CustomMonsterActionInput] | None = None
    bonus_actions: list[CustomMonsterActionInput] | None = None
    reactions: list[CustomMonsterActionInput] | None = None
    legendary_actions: list[CustomMonsterActionInput] | None = None
    description: str | None = None


class ArchiveCustomMonsterInput(StrictModel):
    expected_revision: int = Field(gt=0)


class CreateCustomMonsterFromInstanceInput(StrictModel):
    instance_id: UUID
    name: str | None = None


class MonsterLibraryListToolInput(StrictModel):
    query: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class MonsterLibraryGetToolInput(StrictModel):
    ref: str = Field(min_length=1)
