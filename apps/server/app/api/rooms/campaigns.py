from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_campaign_service
from app.domain.rooms.campaigns import (
    Campaign,
    CampaignCreate,
    CampaignLifecycleError,
    CampaignNotFoundError,
    CampaignService,
    CampaignStatusPatch,
    CharacterNotInRoomError,
    RosterAdd,
    RosterEntry,
    RosterStatusPatch,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext


router = APIRouter(
    prefix="/api/rooms/{room_id}/campaigns",
    tags=["room-campaigns"],
)


def _require_owner(context: RoomAccessContext) -> None:
    if context.authority is not RoomAccessAuthority.OWNER:
        raise APIError(403, "room_owner_required", "Owner authority is required")


def _require_roster_authority(context: RoomAccessContext) -> None:
    if context.authority not in (RoomAccessAuthority.OWNER, RoomAccessAuthority.DM):
        raise APIError(
            403,
            "roster_authority_required",
            "Owner or DM authority is required",
        )


def _map_campaign_error(exc: Exception) -> APIError:
    if isinstance(exc, CampaignNotFoundError):
        return APIError(404, "campaign_not_found", "Campaign was not found")
    if isinstance(exc, CharacterNotInRoomError):
        return APIError(
            404,
            "character_not_in_room",
            "Character is not available in this Room Campaign",
        )
    if isinstance(exc, CampaignLifecycleError):
        return APIError(409, "campaign_lifecycle_conflict", str(exc))
    raise exc


@router.get("", response_model=list[Campaign])
def list_campaigns(
    room_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignService = Depends(get_campaign_service),
) -> list[Campaign]:
    return service.list_campaigns(room_id)


@router.post("", response_model=Campaign, status_code=status.HTTP_201_CREATED)
def create_campaign(
    room_id: UUID,
    payload: CampaignCreate,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignService = Depends(get_campaign_service),
) -> Campaign:
    _require_owner(context)
    return service.create_campaign(room_id, payload)


@router.get("/{campaign_id}", response_model=Campaign)
def get_campaign(
    room_id: UUID,
    campaign_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignService = Depends(get_campaign_service),
) -> Campaign:
    try:
        return service.get_campaign(room_id, campaign_id)
    except Exception as exc:
        raise _map_campaign_error(exc) from exc


@router.patch("/{campaign_id}/status", response_model=Campaign)
def set_campaign_status(
    room_id: UUID,
    campaign_id: UUID,
    payload: CampaignStatusPatch,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignService = Depends(get_campaign_service),
) -> Campaign:
    _require_owner(context)
    try:
        return service.set_status(room_id, campaign_id, payload.status)
    except Exception as exc:
        raise _map_campaign_error(exc) from exc


@router.post("/{campaign_id}/select", response_model=Campaign)
def select_campaign(
    room_id: UUID,
    campaign_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignService = Depends(get_campaign_service),
) -> Campaign:
    _require_owner(context)
    try:
        return service.select_campaign(room_id, campaign_id)
    except Exception as exc:
        raise _map_campaign_error(exc) from exc


@router.delete("/selection", status_code=status.HTTP_204_NO_CONTENT)
def clear_campaign_selection(
    room_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignService = Depends(get_campaign_service),
) -> Response:
    _require_owner(context)
    try:
        service.clear_selection(room_id)
    except Exception as exc:
        raise _map_campaign_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    room_id: UUID,
    campaign_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignService = Depends(get_campaign_service),
) -> Response:
    _require_owner(context)
    try:
        service.delete_draft(room_id, campaign_id)
    except Exception as exc:
        raise _map_campaign_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{campaign_id}/roster", response_model=list[RosterEntry])
def list_roster(
    room_id: UUID,
    campaign_id: UUID,
    _context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignService = Depends(get_campaign_service),
) -> list[RosterEntry]:
    try:
        return service.list_roster(room_id, campaign_id)
    except Exception as exc:
        raise _map_campaign_error(exc) from exc


@router.post(
    "/{campaign_id}/roster",
    response_model=RosterEntry,
    status_code=status.HTTP_201_CREATED,
)
def add_roster_character(
    room_id: UUID,
    campaign_id: UUID,
    payload: RosterAdd,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignService = Depends(get_campaign_service),
) -> RosterEntry:
    _require_roster_authority(context)
    try:
        return service.add_character(room_id, campaign_id, payload)
    except Exception as exc:
        raise _map_campaign_error(exc) from exc


@router.patch(
    "/{campaign_id}/roster/{character_id}",
    response_model=RosterEntry,
)
def update_roster_character(
    room_id: UUID,
    campaign_id: UUID,
    character_id: UUID,
    payload: RosterStatusPatch,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignService = Depends(get_campaign_service),
) -> RosterEntry:
    _require_roster_authority(context)
    try:
        return service.update_roster_status(
            room_id,
            campaign_id,
            character_id,
            payload.status,
        )
    except Exception as exc:
        raise _map_campaign_error(exc) from exc


@router.delete(
    "/{campaign_id}/roster/{character_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_roster_character(
    room_id: UUID,
    campaign_id: UUID,
    character_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignService = Depends(get_campaign_service),
) -> Response:
    _require_roster_authority(context)
    try:
        service.remove_character(room_id, campaign_id, character_id)
    except Exception as exc:
        raise _map_campaign_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
