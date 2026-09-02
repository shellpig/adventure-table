from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.content.identity import parse_stable_key, require_pack_id


StableKey = str
SpellAccessType = Literal["known", "spellbook", "always_prepared", "granted"]
SpellcastingAccessModel = Literal["known", "prepared", "spellbook"]
SpellResourcePoolType = Literal["normal_multiclass_slots", "pact_magic"]
SourceType = Literal["class", "subclass", "feature", "feat", "race", "lineage", "background", "other"]
RestType = Literal["short_rest", "long_rest"]
HitDie = Literal["d6", "d8", "d10", "d12"]
LegacyMovementMode = Literal["climb", "fly", "swim"]
LineageSize = Literal["small", "medium"]
ArcaneArmorPart = Literal["armor", "boots", "helmet", "special_weapon"]
FeatureGrantKind = Literal["choice", "optional_feature", "nested_choice", "retraining"]


def require_stable_key(value: str, *, kinds: set[str] | None = None) -> str:
    parse_stable_key(value, kinds=kinds)
    return value


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MutableModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AbilityScores(FrozenModel):
    strength: int = Field(ge=1, le=30)
    dexterity: int = Field(ge=1, le=30)
    constitution: int = Field(ge=1, le=30)
    intelligence: int = Field(ge=1, le=30)
    wisdom: int = Field(ge=1, le=30)
    charisma: int = Field(ge=1, le=30)


class SubclassSelection(FrozenModel):
    class_ref: StableKey
    subclass_ref: StableKey

    @field_validator("class_ref")
    @classmethod
    def class_ref_is_class(cls, value: str) -> str:
        return require_stable_key(value, kinds={"class"})

    @field_validator("subclass_ref")
    @classmethod
    def subclass_ref_is_subclass(cls, value: str) -> str:
        return require_stable_key(value, kinds={"subclass"})


class SpellAccessEntry(FrozenModel):
    entry_id: str = Field(min_length=1, max_length=120)
    spell_key: StableKey
    source_type: SourceType
    source_key: StableKey
    access_type: SpellAccessType
    casting_ability: str | None = Field(default=None, max_length=40)
    uses_per_rest: int | None = Field(default=None, ge=1)
    rest_type: RestType | None = None

    @field_validator("spell_key")
    @classmethod
    def spell_key_is_spell(cls, value: str) -> str:
        return require_stable_key(value, kinds={"spell"})

    @field_validator("source_key")
    @classmethod
    def source_key_is_stable(cls, value: str) -> str:
        return require_stable_key(value)

    @model_validator(mode="after")
    def usage_metadata_is_consistent(self) -> "SpellAccessEntry":
        if (self.uses_per_rest is None) != (self.rest_type is None):
            raise ValueError("spell access uses_per_rest and rest_type must be declared together")
        return self


class SpellcastingProfile(FrozenModel):
    """Build-persistent identity and eligibility contract for one spell source."""

    profile_id: str = Field(min_length=1, max_length=240)
    source_type: SourceType
    source_key: StableKey
    class_ref: StableKey
    ability: str = Field(min_length=1, max_length=40)
    access_model: SpellcastingAccessModel
    resource_pool_type: SpellResourcePoolType
    max_spell_level: int = Field(ge=0, le=9)
    prepared_limit: int | None = Field(default=None, ge=0)

    @field_validator("source_key")
    @classmethod
    def source_key_is_stable(cls, value: str) -> str:
        return require_stable_key(value)

    @field_validator("class_ref")
    @classmethod
    def class_ref_is_class(cls, value: str) -> str:
        return require_stable_key(value, kinds={"class"})


class SpellSlotCapacity(FrozenModel):
    level: int = Field(ge=1, le=9)
    capacity: int = Field(ge=0)


class SpellResourcePool(FrozenModel):
    """Build-derived spell resource capacity, separate from live used/remaining state."""

    pool_id: str = Field(min_length=1, max_length=240)
    pool_type: SpellResourcePoolType
    source_profile_id: str | None = Field(default=None, min_length=1, max_length=240)
    slots: tuple[SpellSlotCapacity, ...] = ()

    @model_validator(mode="after")
    def slot_levels_are_unique(self) -> "SpellResourcePool":
        levels = [slot.level for slot in self.slots]
        if len(levels) != len(set(levels)):
            raise ValueError("spell resource pool slot levels must be unique")
        return self


class PreparedSpellSelection(FrozenModel):
    """A live prepared spell with source identity independent of Build access rows."""

    spell_key: StableKey
    source_profile_id: str = Field(min_length=1, max_length=240)
    source_access_entry_id: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("spell_key")
    @classmethod
    def spell_key_is_spell(cls, value: str) -> str:
        return require_stable_key(value, kinds={"spell"})


class StartingEquipmentEntry(FrozenModel):
    entry_id: str = Field(min_length=1, max_length=120)
    item_ref: StableKey
    quantity: int = Field(ge=1)

    @field_validator("item_ref")
    @classmethod
    def item_ref_is_item(cls, value: str) -> str:
        return require_stable_key(value, kinds={"equipment", "item"})


class NumericOverride(FrozenModel):
    key: str = Field(min_length=1, max_length=160)
    value: float


class RoleplayProfile(FrozenModel):
    appearance: str | None = None
    biography: str | None = None
    personality_traits: tuple[str, ...] = ()
    ideals: tuple[str, ...] = ()
    bonds: tuple[str, ...] = ()
    flaws: tuple[str, ...] = ()
    custom_fields: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class AncestralLegacySelection(FrozenModel):
    retained_skill_refs: tuple[StableKey, ...] = ()
    retained_movement_modes: tuple[LegacyMovementMode, ...] = ()

    @field_validator("retained_skill_refs")
    @classmethod
    def retained_skills_are_valid_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(require_stable_key(item, kinds={"skill"}) for item in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("ancestral legacy skill refs must be unique")
        return normalized

    @field_validator("retained_movement_modes")
    @classmethod
    def movement_modes_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("ancestral legacy movement modes must be unique")
        return value


class FeatureGrantSource(FrozenModel):
    """Build-persistent provenance for one selected/granted feature."""

    feature_ref: StableKey
    source_ref: StableKey
    grant_kind: FeatureGrantKind

    @field_validator("feature_ref")
    @classmethod
    def feature_ref_is_feature(cls, value: str) -> str:
        return require_stable_key(value, kinds={"feature"})

    @field_validator("source_ref")
    @classmethod
    def source_ref_is_stable(cls, value: str) -> str:
        return require_stable_key(value)


class CharacterBuild(FrozenModel):
    ruleset: str = Field(default="dnd5e-2014", min_length=1)
    content_sources: tuple[str, ...] = ("srd5.1",)
    race_ref: StableKey
    race_variant_ref: StableKey | None = None
    subrace_ref: StableKey | None = None
    lineage_ref: StableKey | None = None
    ancestral_origin_ref: StableKey | None = None
    ancestral_legacy: AncestralLegacySelection | None = None
    size: LineageSize | None = None
    background_ref: StableKey | None = None
    alignment_ref: StableKey | None = None
    character_level: int = Field(ge=1, le=20)
    class_progression: tuple[StableKey, ...]
    subclasses: tuple[SubclassSelection, ...] = ()
    ability_scores: AbilityScores
    proficiencies: tuple[StableKey, ...] = ()
    saving_throw_proficiencies: tuple[StableKey, ...] = ()
    skill_choices: tuple[StableKey, ...] = ()
    skill_expertise_refs: tuple[StableKey, ...] = ()
    language_refs: tuple[StableKey, ...] = ()
    feature_refs: tuple[StableKey, ...] = ()
    feature_grant_sources: tuple[FeatureGrantSource, ...] = ()
    feat_refs: tuple[StableKey, ...] = ()
    infusion_refs: tuple[StableKey, ...] = ()
    walking_speed: int | None = Field(default=None, ge=0)
    swim_speed: int | None = Field(default=None, ge=0)
    climb_speed: int | None = Field(default=None, ge=0)
    fly_speed: int | None = Field(default=None, ge=0)
    spellcasting_profiles: tuple[SpellcastingProfile, ...] = ()
    spell_access_entries: tuple[SpellAccessEntry, ...] = ()
    spell_resource_pools: tuple[SpellResourcePool, ...] = ()
    hp_progression: tuple[int, ...]
    starting_equipment: tuple[StartingEquipmentEntry, ...] = ()
    roleplay_profile: RoleplayProfile = RoleplayProfile()
    numeric_overrides: tuple[NumericOverride, ...] = ()

    @field_validator("content_sources")
    @classmethod
    def content_sources_are_pack_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("content_sources must be unique")
        for source in value:
            require_pack_id(source)
        return value

    @field_validator("race_ref")
    @classmethod
    def race_ref_is_race(cls, value: str) -> str:
        return require_stable_key(value, kinds={"race"})

    @field_validator("race_variant_ref")
    @classmethod
    def race_variant_ref_is_variant(cls, value: str | None) -> str | None:
        return None if value is None else require_stable_key(value, kinds={"race-variant"})

    @field_validator("subrace_ref")
    @classmethod
    def subrace_ref_is_subrace(cls, value: str | None) -> str | None:
        return None if value is None else require_stable_key(value, kinds={"subrace"})

    @field_validator("lineage_ref")
    @classmethod
    def lineage_ref_is_lineage(cls, value: str | None) -> str | None:
        return None if value is None else require_stable_key(value, kinds={"lineage"})

    @field_validator("ancestral_origin_ref")
    @classmethod
    def ancestral_origin_ref_is_race(cls, value: str | None) -> str | None:
        return None if value is None else require_stable_key(value, kinds={"race"})

    @field_validator("background_ref")
    @classmethod
    def background_ref_is_background(cls, value: str | None) -> str | None:
        return None if value is None else require_stable_key(value, kinds={"background"})

    @field_validator("alignment_ref")
    @classmethod
    def alignment_ref_is_alignment(cls, value: str | None) -> str | None:
        return None if value is None else require_stable_key(value, kinds={"alignment"})

    @field_validator("class_progression")
    @classmethod
    def class_progression_refs_are_classes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("class_progression cannot be empty")
        return tuple(require_stable_key(item, kinds={"class"}) for item in value)

    @field_validator("proficiencies")
    @classmethod
    def proficiency_refs_are_proficiencies(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(require_stable_key(item, kinds={"proficiency"}) for item in value)

    @field_validator("saving_throw_proficiencies")
    @classmethod
    def save_refs_are_abilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(require_stable_key(item, kinds={"ability"}) for item in value)

    @field_validator("skill_choices")
    @classmethod
    def skill_refs_are_skills(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(require_stable_key(item, kinds={"skill"}) for item in value)

    @field_validator("skill_expertise_refs")
    @classmethod
    def expertise_refs_are_unique_skills(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(require_stable_key(item, kinds={"skill"}) for item in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("skill expertise refs must be unique")
        return normalized

    @field_validator("language_refs")
    @classmethod
    def language_refs_are_languages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(require_stable_key(item, kinds={"language"}) for item in value)

    @field_validator("feature_refs")
    @classmethod
    def feature_refs_are_features(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(require_stable_key(item, kinds={"feature"}) for item in value)

    @field_validator("feat_refs")
    @classmethod
    def feat_refs_are_feats(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(require_stable_key(item, kinds={"feat"}) for item in value)

    @field_validator("infusion_refs")
    @classmethod
    def infusion_refs_are_infusions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(require_stable_key(item, kinds={"infusion"}) for item in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("infusion_refs must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_build_shape(self) -> "CharacterBuild":
        if self.character_level != len(self.class_progression):
            raise ValueError("character_level must equal len(class_progression)")
        if len(self.hp_progression) != self.character_level:
            raise ValueError("hp_progression must align 1:1 with class_progression")
        if any(value <= 0 for value in self.hp_progression):
            raise ValueError("hp_progression entries must be positive")
        if any(skill_ref not in self.skill_choices for skill_ref in self.skill_expertise_refs):
            raise ValueError("skill expertise requires the corresponding skill proficiency")
        if self.lineage_ref is None:
            if self.ancestral_origin_ref is not None or self.ancestral_legacy is not None or self.size is not None:
                raise ValueError("lineage-only fields require lineage_ref")
        elif self.ancestral_legacy is None or self.size is None:
            raise ValueError("lineage_ref requires ancestral_legacy and size")

        progression_classes = set(self.class_progression)
        subclass_classes: set[str] = set()
        for selection in self.subclasses:
            if selection.class_ref not in progression_classes:
                raise ValueError("subclass class_ref must exist in class_progression")
            if selection.class_ref in subclass_classes:
                raise ValueError("only one subclass selection per class is allowed")
            subclass_classes.add(selection.class_ref)

        feature_ref_set = set(self.feature_refs)
        feature_source_refs = [entry.feature_ref for entry in self.feature_grant_sources]
        if len(feature_source_refs) != len(set(feature_source_refs)):
            raise ValueError("feature grant provenance must be unique per feature_ref")
        if any(feature_ref not in feature_ref_set for feature_ref in feature_source_refs):
            raise ValueError("feature grant provenance must reference a feature in feature_refs")

        profile_ids = [profile.profile_id for profile in self.spellcasting_profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("spellcasting profile_id values must be unique")
        for profile in self.spellcasting_profiles:
            if profile.class_ref not in progression_classes:
                raise ValueError("spellcasting profile class_ref must exist in class_progression")

        spell_entry_ids = [entry.entry_id for entry in self.spell_access_entries]
        if len(spell_entry_ids) != len(set(spell_entry_ids)):
            raise ValueError("spell access entry_id values must be unique")

        pool_ids = [pool.pool_id for pool in self.spell_resource_pools]
        if len(pool_ids) != len(set(pool_ids)):
            raise ValueError("spell resource pool_id values must be unique")
        profile_id_set = set(profile_ids)
        for pool in self.spell_resource_pools:
            if pool.source_profile_id is not None and pool.source_profile_id not in profile_id_set:
                raise ValueError("spell resource pool source_profile_id must exist in spellcasting_profiles")

        equipment_entry_ids = [entry.entry_id for entry in self.starting_equipment]
        if len(equipment_entry_ids) != len(set(equipment_entry_ids)):
            raise ValueError("starting equipment entry_id values must be unique")

        override_keys = [entry.key for entry in self.numeric_overrides]
        if len(override_keys) != len(set(override_keys)):
            raise ValueError("numeric override keys must be unique")
        return self


class ConditionState(FrozenModel):
    condition_ref: StableKey
    note: str | None = None

    @field_validator("condition_ref")
    @classmethod
    def condition_ref_is_condition(cls, value: str) -> str:
        return require_stable_key(value, kinds={"condition"})


class ResourceCounter(FrozenModel):
    used: int = Field(ge=0)
    remaining: int = Field(ge=0)


class InventoryEntry(FrozenModel):
    entry_id: str = Field(min_length=1, max_length=120)
    item_ref: StableKey
    quantity: int = Field(ge=1)
    equipped: bool = False
    carried: bool = True

    @field_validator("item_ref")
    @classmethod
    def item_ref_is_item(cls, value: str) -> str:
        return require_stable_key(value, kinds={"equipment", "item"})


class ActiveInfusion(FrozenModel):
    inventory_entry_id: str = Field(min_length=1, max_length=120)
    infusion_ref: StableKey
    resource: ResourceCounter | None = None
    arcane_armor_part: ArcaneArmorPart | None = None

    @field_validator("infusion_ref")
    @classmethod
    def infusion_ref_is_infusion(cls, value: str) -> str:
        return require_stable_key(value, kinds={"infusion"})


class SpellStoringItemState(FrozenModel):
    inventory_entry_id: str = Field(min_length=1, max_length=120)
    spell_ref: StableKey
    remaining_uses: int = Field(ge=0)

    @field_validator("spell_ref")
    @classmethod
    def spell_ref_is_spell(cls, value: str) -> str:
        return require_stable_key(value, kinds={"spell"})


class CharacterState(MutableModel):
    current_hp: int = Field(ge=0)
    temporary_hp: int = Field(default=0, ge=0)
    conditions: list[ConditionState] = Field(default_factory=list)
    prepared_spell_entry_ids: list[str] = Field(default_factory=list)
    prepared_spells: list[PreparedSpellSelection] = Field(default_factory=list)
    spell_slots: dict[int, ResourceCounter] = Field(default_factory=dict)
    resources: dict[str, ResourceCounter] = Field(default_factory=dict)
    hit_dice_state: dict[HitDie, int] = Field(default_factory=dict)
    inventory_state: list[InventoryEntry] = Field(default_factory=list)
    active_infusions: list[ActiveInfusion] = Field(default_factory=list)
    feature_modes: dict[str, str] = Field(default_factory=dict)
    spell_storing_item: SpellStoringItemState | None = None

    @field_validator("prepared_spell_entry_ids")
    @classmethod
    def prepared_ids_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("prepared_spell_entry_ids must be unique")
        return value

    @field_validator("prepared_spells")
    @classmethod
    def prepared_spells_are_unique(cls, value: list[PreparedSpellSelection]) -> list[PreparedSpellSelection]:
        identities = [(item.source_profile_id, item.spell_key) for item in value]
        if len(identities) != len(set(identities)):
            raise ValueError("prepared spells must be unique per source profile")
        return value

    @field_validator("spell_slots")
    @classmethod
    def spell_slot_levels_are_valid(cls, value: dict[int, ResourceCounter]) -> dict[int, ResourceCounter]:
        if any(level < 1 or level > 9 for level in value):
            raise ValueError("spell slot level must be between 1 and 9")
        return value

    @model_validator(mode="after")
    def validate_state_shape(self) -> "CharacterState":
        inventory_ids = [entry.entry_id for entry in self.inventory_state]
        if len(inventory_ids) != len(set(inventory_ids)):
            raise ValueError("inventory entry_id values must be unique")
        if any(not key.strip() for key in self.resources):
            raise ValueError("resource keys cannot be blank")
        infusion_targets = [entry.inventory_entry_id for entry in self.active_infusions]
        if len(infusion_targets) != len(set(infusion_targets)):
            raise ValueError("an inventory item can have at most one active infusion")
        armor_parts = [
            entry.arcane_armor_part
            for entry in self.active_infusions
            if entry.arcane_armor_part is not None
        ]
        if len(armor_parts) != len(set(armor_parts)):
            raise ValueError("each arcane armor part can host at most one active infusion")
        if any(not key.strip() or not value.strip() for key, value in self.feature_modes.items()):
            raise ValueError("feature mode keys and values cannot be blank")
        return self


class PersistedCharacter(FrozenModel):
    id: UUID
    name: str
    ruleset: str
    current_version_id: UUID
    version_no: int
    build: CharacterBuild
    state: CharacterState
    archived_at: datetime | None = None