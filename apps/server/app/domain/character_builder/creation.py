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
from app.domain.character_builder.schemas import (
    BuilderIssue,
    BuilderResolvedSummary,
)
from app.domain.rules.hit_points import calculate_max_hp
from app.domain.rules.spellcasting import initial_spell_resource_state


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BuilderEquipmentSummary(StrictModel):
    entry_id: str = Field(min_length=1, max_length=120)
    item_ref: str = Field(min_length=1, max_length=240)
    name: str = Field(min_length=1, max_length=240)
    quantity: int = Field(ge=1)
    source_ref: str = Field(min_length=1, max_length=240)


class BuilderReviewDTO(StrictModel):
    draft_id: UUID
    resolved_summary: BuilderResolvedSummary
    build_candidate: CharacterBuild | None = None
    initial_state: CharacterState | None = None
    starting_equipment: tuple[BuilderEquipmentSummary, ...] = ()
    issues: tuple[BuilderIssue, ...]
    can_confirm: bool
    non_standard_count: int = Field(ge=0)


class BuilderConfirmResult(StrictModel):
    character_id: UUID
    current_version_id: UUID
    version_no: int = Field(ge=1)
    character_path: str


def build_initial_character_state(
    build: CharacterBuild,
    registry: ContentRegistry,
    *,
    prepared_spells: tuple[PreparedSpellSelection, ...] = (),
) -> CharacterState:
    spell_slots, resources = initial_spell_resource_state(build)
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
    )
    validate_state_against_build(state, build, registry)
    return state
