from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.content.identity import parse_stable_key, reference_to_stable_key, require_pack_id


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
    "lineage",
    "item",
    "magic-school",
    "proficiency",
    "race",
    "race-variant",
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
    """Content reference supporting explicit StableKeys and legacy SRD URLs."""

    model_config = ConfigDict(extra="allow")

    key: str | None = None
    index: str | None = Field(default=None, min_length=1)
    name: str = Field(min_length=1)
    url: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def has_supported_identity(self) -> "APIReference":
        reference_to_stable_key(self.model_dump(exclude_none=True))
        if self.key is None and (self.index is None or self.url is None):
            raise ValueError("content reference requires explicit key or legacy index + url")
        return self


class IndexedNamedData(BaseModel):
    model_config = ConfigDict(extra="allow")

    index: str = Field(min_length=1)
    name: str = Field(min_length=1)
    url: str | None = Field(default=None, min_length=1)


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


class FeatureResourceCapacity(StrictModel):
    type: Literal["fixed", "proficiency_bonus"]
    value: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def fixed_capacity_requires_value(self) -> "FeatureResourceCapacity":
        if self.type == "fixed" and self.value is None:
            raise ValueError("fixed feature resource capacity requires value")
        if self.type != "fixed" and self.value is not None:
            raise ValueError("non-fixed feature resource capacity cannot include value")
        return self


class FeatureResourceDescriptor(StrictModel):
    capacity: FeatureResourceCapacity
    recharge: list[Literal["short_rest", "long_rest"]] = Field(min_length=1)

    @field_validator("recharge")
    @classmethod
    def recharge_values_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("feature resource recharge values must be unique")
        return value


class FeatureData(IndexedNamedData):
    level: int | None = Field(default=None, ge=1, le=20)
    class_: APIReference | None = Field(default=None, alias="class")
    subclass: APIReference | None = None
    minimum_character_level: int | None = Field(default=None, ge=1, le=20)
    resource: FeatureResourceDescriptor | None = None


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


class LineageData(IndexedNamedData):
    creature_type: str = Field(min_length=1)
    sizes: list[Literal["small", "medium"]] = Field(min_length=1)
    walking_speed: int = Field(gt=0)
    climb_speed: int | None = Field(default=None, gt=0)
    ability_score_patterns: list[list[int]] = Field(min_length=1)
    direct_create_languages: list[APIReference] = Field(default_factory=list)
    direct_create_additional_language_count: int = Field(default=0, ge=0)
    direct_legacy_skill_count: int = Field(default=0, ge=0)
    ancestral_legacy_movement_whitelist: list[Literal["climb", "fly", "swim"]] = Field(default_factory=list)
    features: list[APIReference] = Field(default_factory=list)

    @field_validator("sizes", "ancestral_legacy_movement_whitelist")
    @classmethod
    def lineage_values_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("lineage list values must be unique")
        return value

    @field_validator("ability_score_patterns")
    @classmethod
    def ability_patterns_are_supported(cls, value: list[list[int]]) -> list[list[int]]:
        for pattern in value:
            if pattern not in ([2, 1], [1, 1, 1]):
                raise ValueError("unsupported lineage ability score pattern")
        if len({tuple(pattern) for pattern in value}) != len(value):
            raise ValueError("lineage ability score patterns must be unique")
        return value


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


class RaceVariantReplacementRule(StrictModel):
    target_grant_id: str = Field(min_length=1, max_length=320)
    target_reference: APIReference
    action: Literal["remove"]
    replacement_group_id: str = Field(min_length=1, max_length=160)


class RaceVariantMovementGrant(StrictModel):
    mode: Literal["walk", "swim", "climb", "fly"]
    speed: int = Field(gt=0)


class RaceVariantSpellChoice(StrictModel):
    label: str = Field(min_length=1, max_length=240)
    class_: APIReference = Field(alias="class")
    level: int = Field(default=0, ge=0, le=9)
    choose: int = Field(default=1, ge=1)
    casting_ability: Literal[
        "strength",
        "dexterity",
        "constitution",
        "intelligence",
        "wisdom",
        "charisma",
    ]
    feature: APIReference


class RaceVariantReplacementOption(StrictModel):
    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    label: str = Field(min_length=1, max_length=240)
    keep_target: bool = False
    grants: list[APIReference] = Field(default_factory=list)
    movement: list[RaceVariantMovementGrant] = Field(default_factory=list)
    spell_choice: RaceVariantSpellChoice | None = None

    @model_validator(mode="after")
    def validate_option_shape(self) -> "RaceVariantReplacementOption":
        has_replacement = bool(self.grants or self.movement or self.spell_choice)
        if self.keep_target and has_replacement:
            raise ValueError("keep-target race variant option cannot add replacement mechanics")
        if not self.keep_target and not has_replacement:
            raise ValueError("replacement race variant option must add at least one mechanic")
        return self


class RaceVariantReplacementGroup(StrictModel):
    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    label: str = Field(min_length=1, max_length=240)
    choose: Literal[1] = 1
    options: list[RaceVariantReplacementOption] = Field(min_length=1)

    @model_validator(mode="after")
    def option_ids_are_unique(self) -> "RaceVariantReplacementGroup":
        ids = [option.id for option in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("race variant replacement option ids must be unique")
        return self


class RaceVariantData(IndexedNamedData):
    base_race_ref: APIReference
    replacement_rules: list[RaceVariantReplacementRule] = Field(min_length=1)
    replacement_groups: list[RaceVariantReplacementGroup] = Field(min_length=1)

    @model_validator(mode="after")
    def replacement_groups_cover_rules(self) -> "RaceVariantData":
        group_ids = [group.id for group in self.replacement_groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("race variant replacement group ids must be unique")
        known = set(group_ids)
        for rule in self.replacement_rules:
            if rule.replacement_group_id not in known:
                raise ValueError(
                    "race variant replacement rule references an unknown replacement group"
                )
        return self


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
    "lineage": LineageData,
    "item": ItemData,
    "magic-school": MagicSchoolData,
    "proficiency": ProficiencyData,
    "race": RaceData,
    "race-variant": RaceVariantData,
    "skill": SkillData,
    "spell": SpellData,
    "subclass": SubclassData,
    "subrace": SubraceData,
    "trait": TraitData,
    "weapon-property": WeaponPropertyData,
}


class ContentEntry(StrictModel):
    key: str = Field(min_length=5, max_length=320)
    index: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9.-]*$")
    name: str = Field(min_length=1)
    source: str = Field(min_length=1, max_length=120)
    ruleset: Literal["dnd5e-2014"]
    license: str | None = Field(default=None, min_length=1)
    provenance: dict[str, Any] | None = None
    source_label: str | None = Field(default=None, min_length=1)
    data: dict[str, Any]

    @model_validator(mode="after")
    def identity_is_consistent(self) -> "ContentEntry":
        parsed = parse_stable_key(self.key)
        require_pack_id(self.source)
        if parsed.source != self.source:
            raise ValueError("content entry key/source mismatch")
        if parsed.index != self.index:
            raise ValueError("content entry key/index mismatch")

        raw_variant = self.data.get("variant_of")
        if raw_variant is not None:
            if not isinstance(raw_variant, dict):
                raise ValueError("variant_of must be a content reference")
            target_key = reference_to_stable_key(raw_variant)
            if target_key is None:
                raise ValueError("variant_of must contain a stable content identity")
            target_kind = parse_stable_key(target_key).kind
            if target_kind != parsed.kind:
                raise ValueError(
                    f"variant_of must reference the same kind as {self.key}: "
                    f"expected {parsed.kind}, got {target_kind}"
                )
        return self


class ManifestLicense(StrictModel):
    spdx: str = Field(min_length=1)
    source: str = Field(min_length=1)
    license_url: str = Field(min_length=1)
    attribution: str = Field(min_length=1)


class ExtractionSource(StrictModel):
    repository: str = Field(min_length=1)
    commit: str = Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")
    license: str = Field(min_length=1)
    license_url: str = Field(min_length=1)


class ManifestCategory(StrictModel):
    name: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    kind: StableKind
    file: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*\.json$")
    upstream_file: str | None = Field(default=None, min_length=1)
    count: int = Field(ge=0)


class ScopeGuard(StrictModel):
    excluded_categories: list[str]
    deferred_to: str = Field(min_length=1)


class ContentManifest(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1)
    ruleset: Literal["dnd5e-2014"]
    version: str | None = Field(default=None, min_length=1)
    license: ManifestLicense | None = None
    extraction: ExtractionSource | None = None
    provenance: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    categories: list[ManifestCategory] = Field(min_length=1)
    total_entries: int = Field(ge=0)
    scope_guard: ScopeGuard | None = None

    @model_validator(mode="after")
    def validate_manifest(self) -> "ContentManifest":
        require_pack_id(self.id)
        for attribute in ("name", "kind", "file"):
            values = [getattr(category, attribute) for category in self.categories]
            if len(values) != len(set(values)):
                raise ValueError(f"manifest category {attribute} values must be unique")
        if self.total_entries != sum(category.count for category in self.categories):
            raise ValueError("manifest total_entries does not match category counts")

        if self.id == "srd5.1":
            if self.license is None or self.extraction is None or self.scope_guard is None:
                raise ValueError(
                    "legacy srd5.1 manifest must retain license, extraction, and scope_guard"
                )
            required = {"monsters", "beasts"}
            if not required.issubset(set(self.scope_guard.excluded_categories)):
                raise ValueError("P0 scope guard must exclude monsters and beasts")
            if self.scope_guard.deferred_to != "P4-A":
                raise ValueError("srd5.1 scope guard must remain deferred to P4-A")
        return self
