from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_adventure_service
from app.domain.adventures.schemas import (
    AdventureArchivedError,
    AdventureAttachedError,
    AdventureDefinition,
    AdventureDefinitionCreate,
    AdventureDefinitionPatch,
    AdventureEntry,
    AdventureEntryAssetLink,
    AdventureEntryAssetNotFoundError,
    AdventureEntryCreate,
    AdventureEntryNotFoundError,
    AdventureEntryParentError,
    AdventureEntryPatch,
    AdventureEntryPayloadError,
    AdventureEntryReorder,
    AdventureForbiddenError,
    AdventureNotFoundError,
    AdventureStatusError,
)
from app.domain.adventures.service import AdventureService
from app.domain.rooms.schemas import RoomAccessContext

router = APIRouter(prefix="/api/rooms/{room_id}/adventures", tags=["room-adventures"])


def _map_adventure_error(exc: Exception) -> APIError:
    if isinstance(exc, (AdventureNotFoundError, AdventureForbiddenError)):
        return APIError(404, "adventure_not_found", str(exc))
    if isinstance(exc, AdventureEntryNotFoundError):
        return APIError(404, "adventure_entry_not_found", str(exc))
    if isinstance(exc, AdventureEntryAssetNotFoundError):
        return APIError(404, "adventure_entry_asset_not_found", str(exc))
    if isinstance(exc, AdventureArchivedError):
        return APIError(409, "adventure_archived", str(exc))
    if isinstance(exc, AdventureStatusError):
        return APIError(409, "adventure_status_conflict", str(exc))
    if isinstance(exc, AdventureAttachedError):
        return APIError(409, "adventure_attached_use_archive", str(exc))
    if isinstance(exc, AdventureEntryPayloadError):
        return APIError(400, "adventure_entry_payload_invalid", str(exc))
    if isinstance(exc, AdventureEntryParentError):
        return APIError(400, "adventure_entry_parent_invalid", str(exc))
    raise exc


@router.get("", response_model=list[AdventureDefinition])
def list_adventures(
    room_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> list[AdventureDefinition]:
    try:
        return service.list_definitions(context, room_id=room_id)
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


@router.post("", response_model=AdventureDefinition, status_code=status.HTTP_201_CREATED)
def create_adventure(
    room_id: UUID,
    payload: AdventureDefinitionCreate,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> AdventureDefinition:
    try:
        return service.create_definition(context, room_id=room_id, payload=payload)
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


@router.get("/{adventure_id}", response_model=AdventureDefinition)
def get_adventure(
    room_id: UUID,
    adventure_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> AdventureDefinition:
    try:
        return service.get_definition(context, room_id=room_id, adventure_id=adventure_id)
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


@router.patch("/{adventure_id}", response_model=AdventureDefinition)
def patch_adventure(
    room_id: UUID,
    adventure_id: UUID,
    payload: AdventureDefinitionPatch,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> AdventureDefinition:
    try:
        return service.patch_definition(
            context, room_id=room_id, adventure_id=adventure_id, payload=payload
        )
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


@router.delete("/{adventure_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_adventure(
    room_id: UUID,
    adventure_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> Response:
    try:
        service.delete_definition(context, room_id=room_id, adventure_id=adventure_id)
    except Exception as exc:
        raise _map_adventure_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{adventure_id}/finalize", response_model=AdventureDefinition)
def finalize_adventure(
    room_id: UUID,
    adventure_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> AdventureDefinition:
    try:
        return service.finalize(context, room_id=room_id, adventure_id=adventure_id)
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


@router.post("/{adventure_id}/archive", response_model=AdventureDefinition)
def archive_adventure(
    room_id: UUID,
    adventure_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> AdventureDefinition:
    try:
        return service.archive(context, room_id=room_id, adventure_id=adventure_id)
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


@router.get("/{adventure_id}/entries", response_model=list[AdventureEntry])
def list_entries(
    room_id: UUID,
    adventure_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> list[AdventureEntry]:
    try:
        return service.list_entries(context, room_id=room_id, adventure_id=adventure_id)
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


@router.post(
    "/{adventure_id}/entries",
    response_model=AdventureEntry,
    status_code=status.HTTP_201_CREATED,
)
def create_entry(
    room_id: UUID,
    adventure_id: UUID,
    payload: AdventureEntryCreate,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> AdventureEntry:
    try:
        return service.create_entry(
            context, room_id=room_id, adventure_id=adventure_id, payload=payload
        )
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


@router.post(
    "/{adventure_id}/entries/reorder",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reorder_entries(
    room_id: UUID,
    adventure_id: UUID,
    payload: AdventureEntryReorder,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> Response:
    try:
        service.reorder_entries(
            context, room_id=room_id, adventure_id=adventure_id, payload=payload
        )
    except Exception as exc:
        raise _map_adventure_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{adventure_id}/entries/{entry_id}", response_model=AdventureEntry)
def get_entry(
    room_id: UUID,
    adventure_id: UUID,
    entry_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> AdventureEntry:
    try:
        return service.get_entry(
            context, room_id=room_id, adventure_id=adventure_id, entry_id=entry_id
        )
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


@router.patch("/{adventure_id}/entries/{entry_id}", response_model=AdventureEntry)
def patch_entry(
    room_id: UUID,
    adventure_id: UUID,
    entry_id: UUID,
    payload: AdventureEntryPatch,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> AdventureEntry:
    try:
        return service.patch_entry(
            context,
            room_id=room_id,
            adventure_id=adventure_id,
            entry_id=entry_id,
            payload=payload,
        )
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


@router.delete(
    "/{adventure_id}/entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_entry(
    room_id: UUID,
    adventure_id: UUID,
    entry_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> Response:
    try:
        service.delete_entry(
            context, room_id=room_id, adventure_id=adventure_id, entry_id=entry_id
        )
    except Exception as exc:
        raise _map_adventure_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{adventure_id}/entries/{entry_id}/assets",
    response_model=AdventureEntry,
)
def link_entry_asset(
    room_id: UUID,
    adventure_id: UUID,
    entry_id: UUID,
    payload: AdventureEntryAssetLink,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> AdventureEntry:
    try:
        return service.link_entry_asset(
            context,
            room_id=room_id,
            adventure_id=adventure_id,
            entry_id=entry_id,
            payload=payload,
        )
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


@router.delete(
    "/{adventure_id}/entries/{entry_id}/assets/{asset_id}",
    response_model=AdventureEntry,
)
def unlink_entry_asset(
    room_id: UUID,
    adventure_id: UUID,
    entry_id: UUID,
    asset_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AdventureService = Depends(get_adventure_service),
) -> AdventureEntry:
    try:
        return service.unlink_entry_asset(
            context,
            room_id=room_id,
            adventure_id=adventure_id,
            entry_id=entry_id,
            asset_id=asset_id,
        )
    except Exception as exc:
        raise _map_adventure_error(exc) from exc


__all__ = ["router"]
