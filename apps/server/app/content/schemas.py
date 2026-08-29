from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


StableKind = Literal[
    "ability",
    "alignment",
    "background",
    "class",
    "condition",
    "damage-type",
    "equipment-category",
    "equipment",
    "feat",
    "feature",
    "language",
    "level",
    "item",
    "magic-school",
    "proficiency",
    "race",
    "skill",
    "spell",
    "subclass",
    "subrace",
    "trait",
    "weapon-property",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class APIReference(BaseModel):
    model_config = ConfigDict(extra="allow")

    index: str = Field(min_length=1)
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)


class IndexedNamedData(BaseModel):
    model_config = ConfigDict(extra="allow")

    index: str = Field(min_length=1)
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)


class AbilityData(IndexedNamedData):
    full_name: str = Field(min_length=1)


class AlignmentData(IndexedNamedData):
    abbreviation: str = Field(min_length=1)


class BackgroundData(IndexedNamedData):
    starting_proficiencies: list[APIReference]
    starting_equipment: list[dict[str, Any]]


class ClassData(IndexedNamedData):
    hit_die: Literal[6, 8, 10, 12]
    saving_throws: list[APIReference]
    subclasses: list[APIReference]


class ConditionData(IndexedNamedData):
    desc: list[str]


class DamageTypeData(IndexedNamedData):
    desc: list[str]


class EquipmentCategoryData(IndexedNamedData):
    equipment: list[APIReference]


class Money(BaseModel):
    model_config = ConfigDict(extra="allow")

    quantity: float
    unit: Literal["cp", "sp", "ep", "gp", "pp"]


class EquipmentData(IndexedNamedData):
    equipment_category: APIReference
    cost: Money


class FeatData(IndexedNamedData):
    desc: list[str]


class FeatureData(IndexedNamedData):
    level: int | None = Field(default=None, ge=1, le=20)
    class_: APIReference | None = Field(default=None, alias="class")
    subclass: APIReference | None = None


class LanguageData(IndexedNamedData):
    type: str = Field(min_length=1)


class LevelData(IndexedNamedData):
    name: str | None = None
    level: int = Field(ge=1, le=20)
    prof_bonus: int | None = Field(default=None, ge=2, le=6)
    features: list[APIReference]
    class_: APIReference = Field(alias="class")
    subclass: APIReference | None = None

    @model_validator(mode="after")
    def validate_level_variant(self) -> "LevelData":
        if self.subclass is None and self.prof_bonus is None:
            raise ValueError("class level records must include prof_bonus")
        return self


class ItemData(IndexedNamedData):
    equipment_category: APIReference
    rarity: dict[str, Any]
    variant: bool
    desc: list[str]


class MagicSchoolData(IndexedNamedData):
    desc: str = Field(min_length=1)


class ProficiencyData(IndexedNamedData):
    type: str = Field(min_length=1)


class RaceData(IndexedNamedData):
    speed: int = Field(gt=0)
    ability_bonuses: list[dict[str, Any]]
    languages: list[APIReference]
    traits: list[APIReference]
    subraces: list[APIReference]


class SkillData(IndexedNamedData):
    desc: list[str]
    ability_score: APIReference


class SpellData(IndexedNamedData):
    desc: list[str]
    components: list[Literal["V", "S", "M"]]
    ritual: bool
    concentration: bool
    level: int = Field(ge=0, le=9)
    school: APIReference
    classes: list[APIReference]
    subclasses: list[APIReference]

    @field_validator("components")
    @classmethod
    def components_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("spell components must be unique")
        return value


class SubclassData(IndexedNamedData):
    class_: APIReference = Field(alias="class")
    subclass_flavor: str = Field(min_length=1)


class SubraceData(IndexedNamedData):
    race: APIReference


class TraitData(IndexedNamedData):
    races: list[APIReference]
    subraces: list[APIReference]


class WeaponPropertyData(IndexedNamedData):
    desc: list[str]


DATA_MODELS: dict[str, type[IndexedNamedData]] = {
    "ability": AbilityData,
    "alignment": AlignmentData,
    "background": BackgroundData,
    "class": ClassData,
    "condition": ConditionData,
    "damage-type": DamageTypeData,
    "equipment-category": EquipmentCategoryData,
    "equipment": EquipmentData,
    "feat": FeatData,
    "feature": FeatureData,
    "language": LanguageData,
    "level": LevelData,
    "item": ItemData,
    "magic-school": MagicSchoolData,
    "proficiency": ProficiencyData,
    "race": RaceData,
    "skill": SkillData,
    "spell": SpellData,
    "subclass": SubclassData,
    "subrace": SubraceData,
    "trait": TraitData,
    "weapon-property": WeaponPropertyData,
}


class ContentEntry(StrictModel):
    key: str = Field(pattern=r"^srd5\.1:[a-z0-9-]+:[a-z0-9-]+$")
    index: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1)
    source: Literal["srd5.1"]
    ruleset: Literal["dnd5e-2014"]
    license: Literal["CC-BY-4.0"]
    data: dict[str, Any]


class ManifestLicense(StrictModel):
    spdx: Literal["CC-BY-4.0"]
    source: str = Field(min_length=1)
    license_url: str = Field(min_length=1)
    attribution: str = Field(min_length=1)


class ExtractionSource(StrictModel):
    repository: str = Field(min_length=1)
    commit: str = Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")
    license: Literal["MIT"]
    license_url: str = Field(min_length=1)


class ManifestCategory(StrictModel):
    name: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    kind: StableKind
    file: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*\.json$")
    upstream_file: str = Field(min_length=1)
    count: int = Field(ge=0)


class ScopeGuard(StrictModel):
    excluded_categories: list[str]
    deferred_to: Literal["P4-A"]

    @model_validator(mode="after")
    def require_monster_deferral(self) -> "ScopeGuard":
        required = {"monsters", "beasts"}
        if not required.issubset(set(self.excluded_categories)):
            raise ValueError("P0 scope guard must exclude monsters and beasts")
        return self


class ContentManifest(StrictModel):
    id: Literal["srd5.1"]
    name: str = Field(min_length=1)
    ruleset: Literal["dnd5e-2014"]
    license: ManifestLicense
    extraction: ExtractionSource
    categories: list[ManifestCategory] = Field(min_length=1)
    total_entries: int = Field(ge=0)
    scope_guard: ScopeGuard

    @model_validator(mode="after")
    def categories_are_unique(self) -> "ContentManifest":
        for attribute in ("name", "kind", "file"):
            values = [getattr(category, attribute) for category in self.categories]
            if len(values) != len(set(values)):
                raise ValueError(f"manifest category {attribute} values must be unique")
        if self.total_entries != sum(category.count for category in self.categories):
            raise ValueError("manifest total_entries does not match category counts")
        return self
