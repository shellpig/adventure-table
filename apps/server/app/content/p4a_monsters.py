from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from app.content.schemas import APIReference, StrictModel


class MonsterSpeedData(StrictModel):
    walk: str | None = None
    burrow: str | None = None
    climb: str | None = None
    fly: str | None = None
    swim: str | None = None
    hover: bool | None = None


class MonsterSenseData(StrictModel):
    passive_perception: int = Field(ge=0)
    blindsight: str | None = None
    darkvision: str | None = None
    tremorsense: str | None = None
    truesight: str | None = None


class MonsterProficiencyData(StrictModel):
    value: int
    proficiency: APIReference


class MonsterArmorClassData(StrictModel):
    type: str = Field(min_length=1)
    value: int = Field(ge=0)
    armor: list[APIReference] | None = None
    condition: APIReference | None = None
    spell: APIReference | None = None
    desc: str | None = None


class MonsterUsageData(StrictModel):
    type: str = Field(min_length=1)
    dice: str | None = None
    min_value: int | None = None
    times: int | None = Field(default=None, ge=0)
    rest_types: list[str] | None = None


class MonsterDifficultyClassData(StrictModel):
    dc_type: APIReference
    dc_value: int = Field(ge=0)
    success_type: str = Field(min_length=1)


class MonsterDamageData(StrictModel):
    damage_type: APIReference
    damage_dice: str = Field(min_length=1)


class MonsterActionItemData(StrictModel):
    action_name: str = Field(min_length=1)
    count: int | str
    type: str = Field(min_length=1)


class MonsterAttackData(StrictModel):
    name: str = Field(min_length=1)
    dc: MonsterDifficultyClassData
    damage: list[MonsterDamageData] | None = None


class MonsterActionData(StrictModel):
    name: str = Field(min_length=1)
    desc: str
    attack_bonus: int | None = None
    dc: MonsterDifficultyClassData | None = None
    usage: MonsterUsageData | None = None
    multiattack_type: str | None = None
    actions: list[MonsterActionItemData] | None = None
    action_options: dict[str, Any] | None = None
    attacks: list[MonsterAttackData] | None = None
    options: dict[str, Any] | None = None
    damage: list[MonsterDamageData | dict[str, Any]] | None = None


class MonsterLegendaryActionData(StrictModel):
    name: str = Field(min_length=1)
    desc: str
    attack_bonus: int | None = None
    damage: list[MonsterDamageData] | None = None
    dc: MonsterDifficultyClassData | None = None


class MonsterReactionData(StrictModel):
    name: str = Field(min_length=1)
    desc: str
    dc: MonsterDifficultyClassData | None = None


class MonsterSpellUsageData(StrictModel):
    type: str = Field(min_length=1)
    times: int | None = Field(default=None, ge=0)


class MonsterSpellData(StrictModel):
    name: str = Field(min_length=1)
    level: int = Field(ge=0, le=9)
    url: str = Field(min_length=1)
    usage: MonsterSpellUsageData | None = None
    notes: str | None = None


class MonsterSpellcastingData(StrictModel):
    ability: APIReference
    components_required: list[str]
    spells: list[MonsterSpellData]
    level: int | None = Field(default=None, ge=0)
    dc: int | None = Field(default=None, ge=0)
    modifier: int | None = None
    school: str | None = None
    slots: dict[str, int] | None = None


class MonsterSpecialAbilityData(StrictModel):
    name: str = Field(min_length=1)
    desc: str
    attack_bonus: int | None = None
    damage: list[MonsterDamageData] | None = None
    dc: MonsterDifficultyClassData | None = None
    usage: MonsterUsageData | None = None
    spellcasting: MonsterSpellcastingData | None = None


class MonsterData(StrictModel):
    index: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9.-]*$")
    name: str = Field(min_length=1)
    desc: str | None = None
    size: str = Field(min_length=1)
    type: str = Field(min_length=1)
    subtype: str | None = None
    alignment: str = Field(min_length=1)
    armor_class: list[MonsterArmorClassData] = Field(min_length=1)
    hit_points: int = Field(ge=0)
    hit_dice: str = Field(min_length=1)
    hit_points_roll: str = Field(min_length=1)
    speed: MonsterSpeedData
    strength: int = Field(ge=1)
    dexterity: int = Field(ge=1)
    constitution: int = Field(ge=1)
    intelligence: int = Field(ge=1)
    wisdom: int = Field(ge=1)
    charisma: int = Field(ge=1)
    proficiencies: list[MonsterProficiencyData]
    damage_vulnerabilities: list[str]
    damage_resistances: list[str]
    damage_immunities: list[str]
    condition_immunities: list[APIReference]
    senses: MonsterSenseData
    languages: str
    challenge_rating: float = Field(ge=0)
    proficiency_bonus: int | None = Field(default=None, ge=0)
    xp: int = Field(ge=0)
    special_abilities: list[MonsterSpecialAbilityData] | None = None
    actions: list[MonsterActionData] | None = None
    legendary_actions: list[MonsterLegendaryActionData] | None = None
    reactions: list[MonsterReactionData] | None = None
    forms: list[APIReference] | None = None
    image: str | None = None
    url: str = Field(min_length=1)

    @field_validator(
        "damage_vulnerabilities",
        "damage_resistances",
        "damage_immunities",
    )
    @classmethod
    def damage_traits_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("monster damage trait values must be unique")
        return value

    @property
    def is_beast(self) -> bool:
        return self.type.casefold() == "beast"
