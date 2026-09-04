from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.domain.character.schemas import NumericOverride, require_stable_key


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuilderMode(StrEnum):
    CREATE = "create"
    LEVEL_UP = "level_up"
    BUILD_EDIT = "build_edit"
    CORRECTION = "correction"


class BuilderIssueSeverity(StrEnum):
    BLOCKING_ERROR = "blocking_error"
    WARNING = "warning"
    NON_STANDARD = "non_standard"


class BuilderOptionKind(StrEnum):
    REFERENCE = "reference"
    COUNTED_REFERENCE = "counted_reference"
    NESTED_CHOICE = "nested_choice"
    CATEGORY_FILTER = "category_filter"
    BRANCH = "branch"


class AbilityGenerationMethod(StrEnum):
    STANDARD_ARRAY = "standard_array"
    POINT_BUY = "point_buy"
    MANUAL = "manual"


class BuilderHPMethod(StrEnum):
    FIRST_LEVEL = "first_level"
    FIXED_AVERAGE = "fixed_average"
    MANUAL_ROLLED = "manual_rolled"


class BuilderSpellAccessModel(StrEnum):
    KNOWN = "known"
    PREPARED = "prepared"
    SPELLBOOK = "spellbook"


class BuilderSpellResourcePoolType(StrEnum):
    NORMAL_MULTICLASS_SLOTS = "normal_multiclass_slots"
    PACT_MAGIC = "pact_magic"


class BuilderBasicInput(StrictModel):
    name: str | None = Field(default=None, max_length=200)
    ruleset: str = Field(default="dnd5e-2014", min_length=1, max_length=80)

    @field_validator("ruleset")
    @classmethod
    def ruleset_is_supported(cls, value: str) -> str:
        if value != "dnd5e-2014":
            raise ValueError("P1 only supports dnd5e-2014")
        return value


class BuilderReferenceSelection(StrictModel):
    reference_id: str = Field(min_length=1, max_length=240)
    source_ref: str | None = Field(default=None, max_length=240)


class BuilderAbilityScores(StrictModel):
    strength: int = Field(ge=1, le=30)
    dexterity: int = Field(ge=1, le=30)
    constitution: int = Field(ge=1, le=30)
    intelligence: int = Field(ge=1, le=30)
    wisdom: int = Field(ge=1, le=30)
    charisma: int = Field(ge=1, le=30)

    def as_dict(self) -> dict[str, int]:
        return {
            "strength": self.strength,
            "dexterity": self.dexterity,
            "constitution": self.constitution,
            "intelligence": self.intelligence,
            "wisdom": self.wisdom,
            "charisma": self.charisma,
        }


class BuilderAbilityGenerationInput(StrictModel):
    method: AbilityGenerationMethod
    scores: BuilderAbilityScores
    provenance: str | None = Field(default=None, max_length=240)


class BuilderLevelChoice(StrictModel):
    character_level: int = Field(ge=1, le=20)
    class_ref: str = Field(min_length=1, max_length=240)
    hp_method: BuilderHPMethod
    hp_base_gain: int = Field(ge=1, le=12)
    subclass_ref: str | None = Field(default=None, max_length=240)

    @field_validator("class_ref")
    @classmethod
    def class_ref_is_class(cls, value: str) -> str:
        return require_stable_key(value, kinds={"class"})

    @field_validator("subclass_ref")
    @classmethod
    def subclass_ref_is_subclass(cls, value: str | None) -> str | None:
        return None if value is None else require_stable_key(value, kinds={"subclass"})


class BuilderChoiceSelection(StrictModel):
    choice_id: str = Field(min_length=1, max_length=240)
    selected_option_ids: tuple[str, ...] = ()
    source_ref: str | None = Field(default=None, max_length=240)
    provenance_path: str | None = Field(default=None, max_length=320)

    @field_validator("selected_option_ids")
    @classmethod
    def option_ids_are_non_blank(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("selected_option_ids cannot contain blank values")
        return value


class BuilderSpellChoiceInput(StrictModel):
    """Final spell selections for one deterministic spellcasting profile."""

    cantrip_keys: tuple[str, ...] = ()
    known_spell_keys: tuple[str, ...] = ()
    spellbook_spell_keys: tuple[str, ...] = ()
    prepared_spell_keys: tuple[str, ...] = ()

    @field_validator(
        "cantrip_keys",
        "known_spell_keys",
        "spellbook_spell_keys",
        "prepared_spell_keys",
    )
    @classmethod
    def spell_keys_are_valid_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(require_stable_key(item, kinds={"spell"}) for item in value)
        if len(normalized) != len(set(normalized)):
            raise ValueError("spell selections cannot contain duplicates")
        return normalized


class BuilderChoicePresentationItem(StrictModel):
    reference_id: str = Field(min_length=1, max_length=240)
    count: int = Field(default=1, ge=1)

    @field_validator("reference_id")
    @classmethod
    def reference_id_is_stable_key(cls, value: str) -> str:
        return require_stable_key(value)


class BuilderChoiceOption(StrictModel):
    option_id: str = Field(min_length=1, max_length=240)
    label: str = Field(min_length=1, max_length=240)
    kind: BuilderOptionKind
    reference_id: str | None = Field(default=None, max_length=240)
    count: int | None = Field(default=None, ge=1)
    category: str | None = Field(default=None, max_length=120)
    nested_choice_id: str | None = Field(default=None, max_length=240)
    branch_key: str | None = Field(default=None, max_length=160)
    disabled_reason: str | None = Field(default=None, max_length=500)
    disabled_reason_code: str | None = Field(default=None, max_length=160)
    disabled_reason_params: dict[str, JsonValue] = Field(default_factory=dict)
    hit_die_size: int | None = Field(default=None, ge=1, le=12)
    fixed_hp_gain: int | None = Field(default=None, ge=1, le=12)
    presentation_items: tuple[BuilderChoicePresentationItem, ...] = ()
    presentation_has_choice: bool = False
    # References this option grants outright when picked, on top of anything its
    # nested choices resolve to. A bundled option such as the Rogue's "one skill
    # and thieves' tools" carries the tools here: they are part of the branch,
    # not a second question.
    granted_reference_ids: tuple[str, ...] = ()


class BuilderChoice(StrictModel):
    choice_id: str = Field(min_length=1, max_length=240)
    label: str = Field(min_length=1, max_length=240)
    source_ref: str | None = Field(default=None, max_length=240)
    required: bool
    choose_count: int = Field(ge=0)
    option_source: str | None = Field(default=None, max_length=240)
    options: tuple[BuilderChoiceOption, ...] = ()
    selected_option_ids: tuple[str, ...] = ()
    disabled_reason: str | None = Field(default=None, max_length=500)
    disabled_reason_code: str | None = Field(default=None, max_length=160)
    disabled_reason_params: dict[str, JsonValue] = Field(default_factory=dict)
    allow_duplicates: bool = False


class BuilderDraftPayload(StrictModel):
    basic: BuilderBasicInput | None = None
    target_level: int | None = Field(default=None, ge=1, le=20)
    race_selection: BuilderReferenceSelection | None = None
    race_variant_selection: BuilderReferenceSelection | None = None
    subrace_selection: BuilderReferenceSelection | None = None
    lineage_selection: BuilderReferenceSelection | None = None
    background_selection: BuilderReferenceSelection | None = None
    alignment_selection: BuilderReferenceSelection | None = None
    ability_generation: BuilderAbilityGenerationInput | None = None
    level_choices: tuple[BuilderLevelChoice, ...] = ()
    choice_selections: dict[str, BuilderChoiceSelection] = Field(default_factory=dict)
    spell_choices: dict[str, BuilderSpellChoiceInput] = Field(default_factory=dict)
    starting_equipment_choices: dict[str, JsonValue] = Field(default_factory=dict)
    roleplay_profile: dict[str, JsonValue] = Field(default_factory=dict)
    numeric_overrides: tuple[NumericOverride, ...] = ()
    initial_state_seed: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def choice_selection_keys_match(self) -> "BuilderDraftPayload":
        for key, selection in self.choice_selections.items():
            if not key.strip():
                raise ValueError("choice_selections keys cannot be blank")
            if key != selection.choice_id:
                raise ValueError("choice_selections key must match the nested choice_id")
        if any(not key.strip() for key in self.spell_choices):
            raise ValueError("spell_choices profile ids cannot be blank")
        return self


class BuilderDraftPayloadPatch(StrictModel):
    basic: BuilderBasicInput | None = None
    target_level: int | None = Field(default=None, ge=1, le=20)
    race_selection: BuilderReferenceSelection | None = None
    race_variant_selection: BuilderReferenceSelection | None = None
    subrace_selection: BuilderReferenceSelection | None = None
    lineage_selection: BuilderReferenceSelection | None = None
    background_selection: BuilderReferenceSelection | None = None
    alignment_selection: BuilderReferenceSelection | None = None
    ability_generation: BuilderAbilityGenerationInput | None = None
    level_choices: tuple[BuilderLevelChoice, ...] | None = None
    choice_selections: dict[str, BuilderChoiceSelection] | None = None
    spell_choices: dict[str, BuilderSpellChoiceInput] | None = None
    starting_equipment_choices: dict[str, JsonValue] | None = None
    roleplay_profile: dict[str, JsonValue] | None = None
    numeric_overrides: tuple[NumericOverride, ...] | None = None
    initial_state_seed: dict[str, JsonValue] | None = None


def validate_draft_source_combination(mode: BuilderMode, character_id: UUID | None, base_version_id: UUID | None) -> None:
    if mode is BuilderMode.CREATE:
        if character_id is not None or base_version_id is not None:
            raise ValueError("create drafts cannot reference a character or base version")
        return
    if character_id is None or base_version_id is None:
        raise ValueError(f"{mode.value} drafts require character_id and base_version_id")


class BuilderDraftCreateInput(StrictModel):
    mode: BuilderMode = BuilderMode.CREATE
    character_id: UUID | None = None
    base_version_id: UUID | None = None
    draft_payload: BuilderDraftPayload = Field(default_factory=BuilderDraftPayload)

    @model_validator(mode="after")
    def source_combination_is_valid(self) -> "BuilderDraftCreateInput":
        validate_draft_source_combination(self.mode, self.character_id, self.base_version_id)
        return self


class BuilderDraftPatchInput(StrictModel):
    expected_revision: int = Field(ge=1)
    draft_payload: BuilderDraftPayloadPatch


class BuilderDraft(StrictModel):
    id: UUID
    mode: BuilderMode
    character_id: UUID | None = None
    base_version_id: UUID | None = None
    revision: int = Field(ge=1)
    draft_payload: BuilderDraftPayload
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def source_combination_is_valid(self) -> "BuilderDraft":
        validate_draft_source_combination(self.mode, self.character_id, self.base_version_id)
        return self


class BuilderIssue(StrictModel):
    code: str = Field(min_length=1, max_length=160)
    severity: BuilderIssueSeverity
    path: str = Field(min_length=1, max_length=320)
    message: str = Field(min_length=1, max_length=1000)
    message_params: dict[str, JsonValue] = Field(default_factory=dict)
    related_refs: tuple[str, ...] = ()


class BuilderValidationResult(StrictModel):
    issues: tuple[BuilderIssue, ...]
    can_confirm: bool
    non_standard_count: int = Field(ge=0)


class BuilderGrantSummary(StrictModel):
    label: str
    kind: str
    source_ref: str
    reference_id: str | None = None
    presentation_field: str | None = None


class BuilderAbilityScoreSummary(StrictModel):
    ability: str
    base: int
    permanent_bonus: int
    resolved: int
    effective: int
    overridden: bool = False


class BuilderProgressionNodeSummary(StrictModel):
    character_level: int = Field(ge=1, le=20)
    class_ref: str
    class_name: str
    class_level: int = Field(ge=1, le=20)
    starting_class: bool = False
    multiclass_entry: bool = False
    hit_die_size: int = Field(ge=1, le=12)
    fixed_hp_gain: int = Field(ge=1, le=12)
    hp_method: BuilderHPMethod
    hp_base_gain: int = Field(ge=1, le=12)
    subclass_required: bool = False
    subclass_ref: str | None = None
    subclass_name: str | None = None
    automatic_feature_refs: tuple[str, ...] = ()


class BuilderSpellOptionSummary(StrictModel):
    spell_key: str
    name: str
    level: int = Field(ge=0, le=9)


class BuilderSpellcastingProfileSummary(StrictModel):
    profile_id: str = Field(min_length=1, max_length=240)
    source_type: str
    source_key: str
    source_name: str
    class_ref: str
    ability: str
    access_model: BuilderSpellAccessModel
    class_level: int = Field(ge=1, le=20)
    max_spell_level: int = Field(ge=0, le=9)
    cantrip_count: int = Field(ge=0)
    known_spell_count: int = Field(ge=0)
    spellbook_count: int = Field(ge=0)
    prepared_limit: int | None = Field(default=None, ge=0)
    resource_pool_type: BuilderSpellResourcePoolType
    available_spells: tuple[BuilderSpellOptionSummary, ...] = ()
    selected_cantrip_keys: tuple[str, ...] = ()
    selected_known_spell_keys: tuple[str, ...] = ()
    selected_spellbook_spell_keys: tuple[str, ...] = ()
    selected_prepared_spell_keys: tuple[str, ...] = ()


class BuilderSpellSlotCapacity(StrictModel):
    level: int = Field(ge=1, le=9)
    count: int = Field(ge=0)


class BuilderSpellResourcePoolSummary(StrictModel):
    pool_id: str = Field(min_length=1, max_length=240)
    pool_type: BuilderSpellResourcePoolType
    source_profile_id: str | None = Field(default=None, max_length=240)
    slots: tuple[BuilderSpellSlotCapacity, ...] = ()


class BuilderResolvedSummary(StrictModel):
    name: str | None
    target_level: int | None
    race_name: str | None = None
    race_variant_name: str | None = None
    subrace_name: str | None = None
    lineage_name: str | None = None
    ancestral_origin_name: str | None = None
    background_name: str | None = None
    alignment_name: str | None = None
    starting_class_name: str | None = None
    class_summary: str | None = None
    selected_reference_count: int = Field(ge=0)
    choice_selection_count: int = Field(ge=0)
    grants: tuple[BuilderGrantSummary, ...] = ()
    ability_scores: tuple[BuilderAbilityScoreSummary, ...] = ()
    progression: tuple[BuilderProgressionNodeSummary, ...] = ()
    spellcasting_profiles: tuple[BuilderSpellcastingProfileSummary, ...] = ()
    spell_resource_pools: tuple[BuilderSpellResourcePoolSummary, ...] = ()


class BuilderView(StrictModel):
    draft: BuilderDraft
    resolved_summary: BuilderResolvedSummary
    choices: tuple[BuilderChoice, ...]
    validation: BuilderValidationResult
