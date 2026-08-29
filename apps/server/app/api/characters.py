from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_character_repository
from app.domain.character.schemas import (
    CharacterState,
    ConditionState,
    HitDie,
    InventoryEntry,
    PersistedCharacter,
    ResourceCounter,
)
from app.domain.character.validation import CharacterValidationError
from app.domain.rules.character_sheet import CharacterSheetDTO, build_character_sheet
from app.persistence.characters import CharacterRepository

router = APIRouter(prefix="/api/characters", tags=["characters"])


class CharacterStatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_hp: int | None = Field(default=None, ge=0)
    temporary_hp: int | None = Field(default=None, ge=0)
    conditions: list[ConditionState] | None = None
    prepared_spell_entry_ids: list[str] | None = None
    spell_slots: dict[int, ResourceCounter] | None = None
    resources: dict[str, ResourceCounter] | None = None
    hit_dice_state: dict[HitDie, int] | None = None
    inventory_state: list[InventoryEntry] | None = None


@router.get("/{character_id}", response_model=PersistedCharacter)
def get_character(
    character_id: UUID,
    repository: CharacterRepository = Depends(get_character_repository),
) -> PersistedCharacter:
    return repository.load_character(character_id)


@router.get("/{character_id}/sheet", response_model=CharacterSheetDTO)
def get_character_sheet(
    character_id: UUID,
    repository: CharacterRepository = Depends(get_character_repository),
) -> CharacterSheetDTO:
    character = repository.load_character(character_id)
    return build_character_sheet(character, repository.registry)


@router.patch("/{character_id}/state", response_model=CharacterSheetDTO)
def patch_character_state(
    character_id: UUID,
    patch: CharacterStatePatch,
    repository: CharacterRepository = Depends(get_character_repository),
) -> CharacterSheetDTO:
    character = repository.load_character(character_id)
    changes = patch.model_dump(exclude_unset=True, mode="python")
    if any(value is None for value in changes.values()):
        raise CharacterValidationError("state patch fields cannot be null")
    candidate = CharacterState.model_validate(
        {**character.state.model_dump(mode="python"), **changes}
    )
    updated = repository.save_state(character_id, candidate)
    return build_character_sheet(updated, repository.registry)
