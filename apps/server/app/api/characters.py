from __future__ import annotations

from collections import Counter
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_character_repository
from app.api.errors import APIError
from app.domain.character.schemas import (
    ActiveInfusion,
    CharacterState,
    ConditionState,
    HitDie,
    InventoryEntry,
    PersistedCharacter,
    PreparedSpellSelection,
    ResourceCounter,
    SpellStoringItemState,
)
from app.domain.character.validation import CharacterValidationError
from app.domain.character_builder.versions import CharacterVersionDetail, CharacterVersionSummary
from app.domain.rules.character_sheet import CharacterSheetDTO, build_character_sheet
from app.persistence.characters import (
    CharacterNotFoundError,
    CharacterRepository,
    CharacterVersionNotFoundError,
    StaleBuildVersionError,
)

router = APIRouter(prefix="/api/characters", tags=["characters"])


class CharacterListClassItem(BaseModel):
    """Presentation identity for one class in the workshop list."""

    model_config = ConfigDict(extra="forbid")

    class_ref: str = Field(min_length=1, max_length=240)
    name: str = Field(min_length=1, max_length=240)
    level: int = Field(ge=1, le=20)


class CharacterListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    level: int = Field(ge=1, le=20)
    # Keep the canonical summary for backward compatibility. M02-D clients use
    # classes[] StableKeys to resolve locale-specific presentation instead.
    class_summary: str
    classes: tuple[CharacterListClassItem, ...] = ()
    version_no: int = Field(ge=1)


class CharacterStatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version_id: UUID | None = None
    current_hp: int | None = Field(default=None, ge=0)
    temporary_hp: int | None = Field(default=None, ge=0)
    conditions: list[ConditionState] | None = None
    prepared_spell_entry_ids: list[str] | None = None
    prepared_spells: list[PreparedSpellSelection] | None = None
    spell_slots: dict[int, ResourceCounter] | None = None
    resources: dict[str, ResourceCounter] | None = None
    hit_dice_state: dict[HitDie, int] | None = None
    inventory_state: list[InventoryEntry] | None = None
    active_infusions: list[ActiveInfusion] | None = None
    feature_modes: dict[str, str] | None = None
    spell_storing_item: SpellStoringItemState | None = None


def _class_entries(
    character: PersistedCharacter,
    repository: CharacterRepository,
) -> tuple[CharacterListClassItem, ...]:
    counts = Counter(character.build.class_progression)
    order = tuple(dict.fromkeys(character.build.class_progression))
    return tuple(
        CharacterListClassItem(
            class_ref=class_ref,
            name=repository.registry.get(class_ref).name,
            level=counts[class_ref],
        )
        for class_ref in order
    )


def _class_summary(character: PersistedCharacter, repository: CharacterRepository) -> str:
    return " / ".join(
        f"{entry.name} {entry.level}"
        for entry in _class_entries(character, repository)
    )


def _canonicalize_prepared_patch(
    character: PersistedCharacter,
    changes: dict[str, object],
) -> None:
    """Keep P0 legacy patches readable without letting them bypass P1 limits.

    P1+ Builds own prepared state in ``prepared_spells``. A stale P0 client may
    still send spellbook entry ids; translate that complete spellbook selection
    into canonical selections and clear the legacy field before validation.
    Direct canonical patches also clear any previously persisted legacy ids so
    two prepared-state representations cannot continue to diverge.
    """

    if "prepared_spells" in changes:
        changes["prepared_spell_entry_ids"] = []
        return
    if "prepared_spell_entry_ids" not in changes or not character.build.spellcasting_profiles:
        return

    raw_entry_ids = changes["prepared_spell_entry_ids"]
    if not isinstance(raw_entry_ids, list):
        raise CharacterValidationError("prepared_spell_entry_ids patch must be a list")

    access_by_id = {entry.entry_id: entry for entry in character.build.spell_access_entries}
    spellbook_profiles = {
        (profile.source_type, profile.source_key): profile
        for profile in character.build.spellcasting_profiles
        if profile.access_model == "spellbook"
    }
    profile_by_id = {
        profile.profile_id: profile for profile in character.build.spellcasting_profiles
    }
    translated: list[PreparedSpellSelection] = [
        selection
        for selection in character.state.prepared_spells
        if (
            selection.source_profile_id in profile_by_id
            and profile_by_id[selection.source_profile_id].access_model != "spellbook"
        )
    ]

    for entry_id in raw_entry_ids:
        if not isinstance(entry_id, str):
            raise CharacterValidationError("prepared spell entry ids must be strings")
        access = access_by_id.get(entry_id)
        if access is None or access.access_type != "spellbook":
            raise CharacterValidationError(
                f"prepared spell entry does not exist or is not spellbook access: {entry_id}"
            )
        profile = spellbook_profiles.get((access.source_type, access.source_key))
        if profile is None:
            raise CharacterValidationError(
                f"spellbook prepared entry has no canonical source profile: {entry_id}"
            )
        translated.append(
            PreparedSpellSelection(
                spell_key=access.spell_key,
                source_profile_id=profile.profile_id,
                source_access_entry_id=access.entry_id,
            )
        )

    changes["prepared_spells"] = translated
    changes["prepared_spell_entry_ids"] = []


def _list_item(
    character: PersistedCharacter,
    repository: CharacterRepository,
) -> CharacterListItem:
    return CharacterListItem(
        id=character.id,
        name=character.name,
        level=character.build.character_level,
        class_summary=_class_summary(character, repository),
        classes=_class_entries(character, repository),
        version_no=character.version_no,
    )


@router.get("", response_model=list[CharacterListItem])
def list_characters(
    archived: bool = False,
    repository: CharacterRepository = Depends(get_character_repository),
) -> list[CharacterListItem]:
    """List active characters, or the archived ones when `archived=true`."""

    return [
        _list_item(character, repository)
        for character in repository.list_characters(archived=archived)
    ]


@router.post("/{character_id}/archive", response_model=CharacterListItem)
def archive_character(
    character_id: UUID,
    repository: CharacterRepository = Depends(get_character_repository),
) -> CharacterListItem:
    return _list_item(repository.set_archived(character_id, True), repository)


@router.post("/{character_id}/unarchive", response_model=CharacterListItem)
def unarchive_character(
    character_id: UUID,
    repository: CharacterRepository = Depends(get_character_repository),
) -> CharacterListItem:
    return _list_item(repository.set_archived(character_id, False), repository)


@router.delete("/{character_id}", status_code=204)
def delete_character(
    character_id: UUID,
    repository: CharacterRepository = Depends(get_character_repository),
) -> None:
    """Permanently delete an archived character, versions and state included."""

    repository.delete_character(character_id)


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
    nullable_state_fields = {"spell_storing_item"}
    if any(
        value is None
        for key, value in changes.items()
        if key not in nullable_state_fields
    ):
        raise CharacterValidationError("state patch fields cannot be null")

    expected_current_version_id = changes.pop(
        "expected_current_version_id",
        character.current_version_id,
    )
    if expected_current_version_id != character.current_version_id:
        stale = StaleBuildVersionError(
            character_id,
            expected_current_version_id,
            character.current_version_id,
        )
        raise APIError(409, "stale_build_version", str(stale))

    _canonicalize_prepared_patch(character, changes)
    candidate = CharacterState.model_validate(
        {**character.state.model_dump(mode="python"), **changes}
    )
    try:
        updated = repository.save_state(
            character_id,
            candidate,
            expected_current_version_id=expected_current_version_id,
        )
    except StaleBuildVersionError as exc:
        raise APIError(409, "stale_build_version", str(exc)) from exc
    return build_character_sheet(updated, repository.registry)
