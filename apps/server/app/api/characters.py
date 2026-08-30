from __future__ import annotations

from collections import Counter
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_character_repository
from app.api.errors import APIError
from app.domain.character.schemas import (
    CharacterState,
    ConditionState,
    HitDie,
    InventoryEntry,
    PersistedCharacter,
    PreparedSpellSelection,
    ResourceCounter,
)
from app.domain.character.validation import CharacterValidationError
from app.domain.character_builder.versions import CharacterVersionDetail, CharacterVersionSummary
from app.domain.rules.character_sheet import CharacterSheetDTO, build_character_sheet
from app.persistence.characters import (
    CharacterNotFoundError,
    CharacterRepository,
    CharacterVersionNotFoundError,
)

router = APIRouter(prefix="/api/characters", tags=["characters"])


class CharacterListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    level: int = Field(ge=1, le=20)
    class_summary: str
    version_no: int = Field(ge=1)


class CharacterStatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_hp: int | None = Field(default=None, ge=0)
    temporary_hp: int | None = Field(default=None, ge=0)
    conditions: list[ConditionState] | None = None
    prepared_spell_entry_ids: list[str] | None = None
    prepared_spells: list[PreparedSpellSelection] | None = None
    spell_slots: dict[int, ResourceCounter] | None = None
    resources: dict[str, ResourceCounter] | None = None
    hit_dice_state: dict[HitDie, int] | None = None
    inventory_state: list[InventoryEntry] | None = None


def _class_summary(character: PersistedCharacter, repository: CharacterRepository) -> str:
    counts = Counter(character.build.class_progression)
    order = tuple(dict.fromkeys(character.build.class_progression))
    parts: list[str] = []
    for class_ref in order:
        entry = repository.registry.get(class_ref)
        parts.append(f"{entry.name} {counts[class_ref]}")
    return " / ".join(parts)


@router.get("", response_model=list[CharacterListItem])
def list_characters(
    repository: CharacterRepository = Depends(get_character_repository),
) -> list[CharacterListItem]:
    return [
        CharacterListItem(
            id=character.id,
            name=character.name,
            level=character.build.character_level,
            class_summary=_class_summary(character, repository),
            version_no=character.version_no,
        )
        for character in repository.list_characters()
    ]


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


@router.get("/{character_id}/versions", response_model=list[CharacterVersionSummary])
def list_character_versions(
    character_id: UUID,
    repository: CharacterRepository = Depends(get_character_repository),
) -> list[CharacterVersionSummary]:
    try:
        return list(repository.list_versions(character_id))
    except CharacterNotFoundError as exc:
        raise APIError(404, "character_not_found", f"character not found: {exc}") from exc


@router.get("/{character_id}/versions/{version_no}", response_model=CharacterVersionDetail)
def get_character_version(
    character_id: UUID,
    version_no: int,
    repository: CharacterRepository = Depends(get_character_repository),
) -> CharacterVersionDetail:
    try:
        return repository.load_version(character_id, version_no)
    except CharacterNotFoundError as exc:
        raise APIError(404, "character_not_found", f"character not found: {exc}") from exc
    except CharacterVersionNotFoundError as exc:
        raise APIError(404, "character_version_not_found", str(exc)) from exc


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
