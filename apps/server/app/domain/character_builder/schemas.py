from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.domain.character.schemas import NumericOverride


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


class BuilderChoiceSelection(StrictModel):
    choice_id: str = Field(min_length=1, max_length=240)
    selected_option_ids: tuple[str, ...] = ()
    source_ref: str | None = Field(default=None, max_length=240)
    provenance_path: str | None = Field(default=None, max_length=320)

    @field_validator("selected_option_ids")
    @classmethod
    def option_ids_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("selected_option_ids must be unique")
        if any(not item.strip() for item in value):
            raise ValueError("selected_option_ids cannot contain blank values")
        return value


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


class BuilderDraftPayload(StrictModel):
    basic: BuilderBasicInput | None = None
    target_level: int | None = Field(default=None, ge=1, le=20)
    race_selection: BuilderReferenceSelection | None = None
    subrace_selection: BuilderReferenceSelection | None = None
    background_selection: BuilderReferenceSelection | None = None
    alignment_selection: BuilderReferenceSelection | None = None
    ability_generation: BuilderAbilityGenerationInput | None = None
    level_choices: tuple[dict[str, JsonValue], ...] = ()
    choice_selections: dict[str, BuilderChoiceSelection] = Field(default_factory=dict)
    spell_choices: dict[str, JsonValue] = Field(default_factory=dict)
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
        return self


class BuilderDraftPayloadPatch(StrictModel):
    basic: BuilderBasicInput | None = None
    target_level: int | None = Field(default=None, ge=1, le=20)
    race_selection: BuilderReferenceSelection | None = None
    subrace_selection: BuilderReferenceSelection | None = None
    background_selection: BuilderReferenceSelection | None = None
    alignment_selection: BuilderReferenceSelection | None = None
    ability_generation: BuilderAbilityGenerationInput | None = None
    level_choices: tuple[dict[str, JsonValue], ...] | None = None
    choice_selections: dict[str, BuilderChoiceSelection] | None = None
    spell_choices: dict[str, JsonValue] | None = None
    starting_equipment_choices: dict[str, JsonValue] | None = None
    roleplay_profile: dict[str, JsonValue] | None = None
    numeric_overrides: tuple[NumericOverride, ...] | None = None
    initial_state_seed: dict[str, JsonValue] | None = None


def validate_draft_source_combination(
    mode: BuilderMode,
    character_id: UUID | None,
    base_version_id: UUID | None,
) -> None:
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


class BuilderAbilityScoreSummary(StrictModel):
    ability: str
    base: int
    permanent_bonus: int
    resolved: int
    effective: int
    overridden: bool = False


class BuilderResolvedSummary(StrictModel):
    name: str | None
    target_level: int | None
    race_name: str | None = None
    subrace_name: str | None = None
    background_name: str | None = None
    alignment_name: str | None = None
    selected_reference_count: int = Field(ge=0)
    choice_selection_count: int = Field(ge=0)
    grants: tuple[BuilderGrantSummary, ...] = ()
    ability_scores: tuple[BuilderAbilityScoreSummary, ...] = ()


class BuilderView(StrictModel):
    draft: BuilderDraft
    resolved_summary: BuilderResolvedSummary
    choices: tuple[BuilderChoice, ...]
    validation: BuilderValidationResult
