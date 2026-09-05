from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.content.registry import ContentRegistry
from app.domain.character.schemas import (
    CharacterBuild,
    CharacterState,
    InventoryEntry,
    PreparedSpellSelection,
)
from app.domain.character.validation import derive_hit_dice_totals, validate_state_against_build
from app.domain.character_builder.reconciliation import StateReconciliationPreview
from app.domain.character_builder.schemas import (
    BuilderIssue,
    BuilderResolvedSummary,
)
from app.domain.rules.abilities import ABILITY_NAMES, ability_modifier, effective_ability_score
from app.domain.rules.artificer_dto import ArtificerSummaryDTO, build_artificer_summary
from app.domain.rules.feature_resources import initial_feature_resource_state
from app.domain.rules.hit_points import calculate_max_hp
from app.domain.rules.m01m_ancestry import initial_feature_modes
from app.domain.rules.proficiency import proficiency_bonus, total_character_level
from app.domain.rules.skills import all_skill_modifiers, all_skill_proficiencies
from app.domain.rules.spellcasting import initial_spell_resource_state


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuilderEquipmentSummary(StrictModel):
    entry_id: str = Field(min_length=1, max_length=120)
    item_ref: str = Field(min_length=1, max_length=240)
    name: str = Field(min_length=1, max_length=240)
    quantity: int = Field(ge=1)
    source_ref: str = Field(min_length=1, max_length=240)


class BuilderReviewDerivedStats(StrictModel):
    ability_modifiers: dict[str, int]
    proficiency_bonus: int = Field(ge=2, le=6)
    skill_modifiers: dict[str, int]
    skill_proficiencies: tuple[str, ...] = ()
    artificer: ArtificerSummaryDTO | None = None


class BuilderReviewDTO(StrictModel):
    draft_id: UUID
    resolved_summary: BuilderResolvedSummary
    build_candidate: CharacterBuild | None = None
    initial_state: CharacterState | None = None
    reconciliation: StateReconciliationPreview | None = None
    derived_stats: BuilderReviewDerivedStats | None = None
    starting_equipment: tuple[BuilderEquipmentSummary, ...] = ()
    issues: tuple[BuilderIssue, ...]
    can_confirm: bool
    non_standard_count: int = Field(ge=0)


class BuilderConfirmResult(StrictModel):
    character_id: UUID
    current_version_id: UUID
    version_no: int = Field(ge=1)
    character_path: str


def build_review_derived_stats(
    build: CharacterBuild,
    registry: ContentRegistry,
    *,
    state: CharacterState | None = None,
) -> BuilderReviewDerivedStats:
    level = total_character_level(build)
    return BuilderReviewDerivedStats(
        ability_modifiers={
            ability: ability_modifier(effective_ability_score(build, ability))
            for ability in ABILITY_NAMES
        },
        proficiency_bonus=proficiency_bonus(level),
        skill_modifiers=all_skill_modifiers(build, registry),
        skill_proficiencies=all_skill_proficiencies(build, registry),
        artificer=build_artificer_summary(build, state, registry),
    )


def build_initial_character_state(
    build: CharacterBuild,
    registry: ContentRegistry,
    *,
    prepared_spells: tuple[PreparedSpellSelection, ...] = (),
    initial_state_seed: dict[str, object] | None = None,
) -> CharacterState:
    spell_slots, spell_resources = initial_spell_resource_state(build)
    resources = dict(spell_resources)
    resources.update(initial_feature_resource_state(build, registry))
    state = CharacterState(
        current_hp=calculate_max_hp(build),
        temporary_hp=0,
        conditions=[],
        prepared_spell_entry_ids=[],
        prepared_spells=list(prepared_spells),
        spell_slots=spell_slots,
        resources=resources,
        hit_dice_state=derive_hit_dice_totals(build, registry),
        inventory_state=[
            InventoryEntry(
                entry_id=f"inventory:{entry.entry_id}",
                item_ref=entry.item_ref,
                quantity=entry.quantity,
                equipped=False,
                carried=True,
            )
            for entry in build.starting_equipment
        ],
        feature_modes=initial_feature_modes(
            build,
            registry,
            initial_state_seed,
        ),
    )
    validate_state_against_build(state, build, registry)
    return state