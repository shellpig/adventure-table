from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api import characters as core_characters
from app.api.character_export import export_character as core_export_character
from app.api.character_import import MAX_CHARACTER_IMPORT_BYTES, _parse_document
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_room_workspace_service
from app.domain.character.schemas import PersistedCharacter
from app.domain.character_builder.versions import CharacterVersionDetail, CharacterVersionSummary
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.workspace import RoomCharacterWorkspaceService, RoomWorkspaceScopeError
from app.interop.character_import import CharacterImportError, CharacterImportResult
from app.domain.rules.character_sheet import CharacterSheetDTO


router = APIRouter(prefix="/api/rooms/{room_id}/characters", tags=["room-characters"])


class LegacyCharacterDataStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_count: int = Field(ge=0)
    draft_count: int = Field(ge=0)
    available: bool


class LegacyCharacterDataClaimResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claimed_character_count: int = Field(ge=0)
    claimed_draft_count: int = Field(ge=0)


def _scope_error(exc: RoomWorkspaceScopeError) -> APIError:
    return APIError(404, "room_resource_not_found", "Room character resource was not found")


def _require_character(service: RoomCharacterWorkspaceService, room_id: UUID, character_id: UUID) -> None:
    try:
        service.require_character(room_id, character_id)
    except RoomWorkspaceScopeError as exc:
        raise _scope_error(exc) from exc


def _set_archived(
    service: RoomCharacterWorkspaceService,
    room_id: UUID,
    character_id: UUID,
    archived: bool,
) -> core_characters.CharacterListItem:
    try:
        character = service.set_character_archived(room_id, character_id, archived)
    except RoomWorkspaceScopeError as exc:
        raise _scope_error(exc) from exc
    return core_characters._list_item(character, service.character_repository)


def _require_owner(context: RoomAccessContext) -> None:
    if context.authority is not RoomAccessAuthority.OWNER:
        raise APIError(403, "room_owner_required", "Owner authority is required")


@router.get("", response_model=list[core_characters.CharacterListItem])
def list_characters(
    room_id: UUID,
    archived: bool = False,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> list[core_characters.CharacterListItem]:
    return [
        core_characters._list_item(character, service.character_repository)
        for character in service.list_characters(room_id, archived=archived)
    ]


@router.get("/legacy", response_model=LegacyCharacterDataStatus)
def legacy_character_data_status(
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> LegacyCharacterDataStatus:
    _require_owner(context)
    counts = service.workspace_repository.legacy_counts()
    return LegacyCharacterDataStatus(
        character_count=counts.characters,
        draft_count=counts.drafts,
        available=(counts.characters + counts.drafts) > 0,
    )


@router.post("/legacy/claim", response_model=LegacyCharacterDataClaimResult)
def claim_legacy_character_data(
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> LegacyCharacterDataClaimResult:
    _require_owner(context)
    counts = service.workspace_repository.claim_all_unscoped(context.room_id)
    return LegacyCharacterDataClaimResult(
        claimed_character_count=counts.characters,
        claimed_draft_count=counts.drafts,
    )


@router.get("/{character_id}", response_model=PersistedCharacter)
def get_character(
    room_id: UUID,
    character_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> PersistedCharacter:
    _require_character(service, room_id, character_id)
    return core_characters.get_character(character_id, service.character_repository)


@router.get("/{character_id}/sheet", response_model=CharacterSheetDTO)
def get_character_sheet(
    room_id: UUID,
    character_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> CharacterSheetDTO:
    _require_character(service, room_id, character_id)
    return core_characters.get_character_sheet(character_id, service.character_repository)


@router.patch("/{character_id}/state", response_model=CharacterSheetDTO)
def patch_character_state(
    room_id: UUID,
    character_id: UUID,
    patch: core_characters.CharacterStatePatch,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> CharacterSheetDTO:
    _require_character(service, room_id, character_id)
    return core_characters.patch_character_state(character_id, patch, service.character_repository)


@router.post("/{character_id}/archive", response_model=core_characters.CharacterListItem)
def archive_character(
    room_id: UUID,
    character_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> core_characters.CharacterListItem:
    return _set_archived(service, room_id, character_id, True)


@router.post("/{character_id}/unarchive", response_model=core_characters.CharacterListItem)
def unarchive_character(
    room_id: UUID,
    character_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> core_characters.CharacterListItem:
    return _set_archived(service, room_id, character_id, False)


@router.delete("/{character_id}", status_code=204)
def delete_character(
    room_id: UUID,
    character_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> None:
    _require_character(service, room_id, character_id)
    _require_owner(context)
    core_characters.delete_character(character_id, service.character_repository)


@router.get("/{character_id}/versions", response_model=list[CharacterVersionSummary])
def list_character_versions(
    room_id: UUID,
    character_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> list[CharacterVersionSummary]:
    _require_character(service, room_id, character_id)
    return core_characters.list_character_versions(character_id, service.character_repository)


@router.get("/{character_id}/versions/{version_no}", response_model=CharacterVersionDetail)
def get_character_version(
    room_id: UUID,
    character_id: UUID,
    version_no: int,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> CharacterVersionDetail:
    _require_character(service, room_id, character_id)
    return core_characters.get_character_version(character_id, version_no, service.character_repository)


@router.get("/{character_id}/export")
def export_character(
    room_id: UUID,
    character_id: UUID,
    request: Request,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> Response:
    _require_character(service, room_id, character_id)
    return core_export_character(character_id, request, service.character_repository)


@router.post("/import", response_model=CharacterImportResult)
async def import_character(
    room_id: UUID,
    request: Request,
    response: Response,
    dry_run: bool = False,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: RoomCharacterWorkspaceService = Depends(get_room_workspace_service),
) -> CharacterImportResult:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type and content_type != "application/json":
        raise APIError(415, "invalid_envelope_shape", "character import accepts application/json only")
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_CHARACTER_IMPORT_BYTES:
                raise APIError(413, "payload_too_large", "character import exceeds the 5 MB limit", params={"max_bytes": MAX_CHARACTER_IMPORT_BYTES})
        except ValueError:
            pass
    document = _parse_document(await request.body())
    try:
        result = service.preview_import(document) if dry_run else service.import_character(room_id, document)
    except CharacterImportError as exc:
        raise APIError(exc.status_code, exc.code, exc.message, params=exc.params) from exc
    response.status_code = 200 if dry_run else 201
    return result
