from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_seat_service
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.seats import (
    CampaignSeat,
    LobbySnapshot,
    LobbyUnavailableError,
    SeatCampaignMismatchError,
    SeatCharacterPatch,
    SeatCharacterSelectionError,
    SeatControllerError,
    SeatControllerPatch,
    SeatCreate,
    SeatNotFoundError,
    SeatRole,
    SeatService,
)


router = APIRouter(prefix="/api/rooms/{room_id}/campaigns/{campaign_id}", tags=["room-seats"])


def _management_allowed(context: RoomAccessContext) -> bool:
    return context.authority in {RoomAccessAuthority.OWNER, RoomAccessAuthority.DM}


def _require_non_dm_seat_management(context: RoomAccessContext) -> None:
    if not _management_allowed(context):
        raise APIError(403, "seat_management_authority_required", "Owner or DM authority is required")


def _require_dm_seat_management(context: RoomAccessContext) -> None:
    if context.authority is not RoomAccessAuthority.OWNER:
        raise APIError(403, "room_owner_required", "Owner authority is required for DM Seat assignment")


def _map_seat_error(exc: Exception) -> APIError:
    if isinstance(exc, (SeatCampaignMismatchError, SeatNotFoundError)):
        return APIError(404, "seat_not_found", "Seat or Campaign was not found in this Room")
    if isinstance(exc, LobbyUnavailableError):
        return APIError(409, "lobby_unavailable", str(exc))
    if isinstance(exc, SeatControllerError):
        return APIError(409, "seat_controller_invalid", str(exc))
    if isinstance(exc, SeatCharacterSelectionError):
        return APIError(409, "seat_character_invalid", str(exc))
    raise exc


def _seat_role(service: SeatService, room_id: UUID, campaign_id: UUID, seat_id: UUID) -> SeatRole:
    try:
        seat = service._require_seat(room_id, campaign_id, seat_id)
    except Exception as exc:
        raise _map_seat_error(exc) from exc
    return SeatRole(seat.role)


def _require_seat_mutation_authority(
    *,
    context: RoomAccessContext,
    service: SeatService,
    room_id: UUID,
    campaign_id: UUID,
    seat_id: UUID,
) -> SeatRole:
    role = _seat_role(service, room_id, campaign_id, seat_id)
    if role is SeatRole.DM:
        _require_dm_seat_management(context)
    else:
        _require_non_dm_seat_management(context)
    return role


@router.get("/seats", response_model=list[CampaignSeat])
def list_seats(
    room_id: UUID,
    campaign_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SeatService = Depends(get_seat_service),
) -> list[CampaignSeat]:
    try:
        return service.list_seats(context.room_id, campaign_id)
    except Exception as exc:
        raise _map_seat_error(exc) from exc


@router.post("/seats", response_model=CampaignSeat, status_code=status.HTTP_201_CREATED)
def create_seat(
    room_id: UUID,
    campaign_id: UUID,
    payload: SeatCreate,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SeatService = Depends(get_seat_service),
) -> CampaignSeat:
    if payload.role is SeatRole.DM:
        _require_dm_seat_management(context)
    else:
        _require_non_dm_seat_management(context)
    try:
        return service.create_seat(context.room_id, campaign_id, payload)
    except Exception as exc:
        raise _map_seat_error(exc) from exc


@router.patch("/seats/{seat_id}/controller", response_model=CampaignSeat)
def set_controller(
    room_id: UUID,
    campaign_id: UUID,
    seat_id: UUID,
    payload: SeatControllerPatch,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SeatService = Depends(get_seat_service),
) -> CampaignSeat:
    _require_seat_mutation_authority(
        context=context,
        service=service,
        room_id=room_id,
        campaign_id=campaign_id,
        seat_id=seat_id,
    )
    try:
        return service.set_controller(context.room_id, campaign_id, seat_id, payload)
    except Exception as exc:
        raise _map_seat_error(exc) from exc


@router.patch("/seats/{seat_id}/character", response_model=CampaignSeat)
def set_selected_character(
    room_id: UUID,
    campaign_id: UUID,
    seat_id: UUID,
    payload: SeatCharacterPatch,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SeatService = Depends(get_seat_service),
) -> CampaignSeat:
    try:
        seat = service._require_seat(context.room_id, campaign_id, seat_id)
    except Exception as exc:
        raise _map_seat_error(exc) from exc
    if context.authority is RoomAccessAuthority.MEMBER:
        if not (
            seat.role == SeatRole.PLAYER.value
            and seat.controller_kind == "human"
            and seat.controller_access_session_id == context.access_session_id
        ):
            raise APIError(403, "seat_controller_required", "Member may operate only their assigned Human Player Seat")
    else:
        _require_non_dm_seat_management(context)
    try:
        return service.select_character(context.room_id, campaign_id, seat_id, payload.selected_character_id)
    except Exception as exc:
        raise _map_seat_error(exc) from exc


@router.post("/seats/{seat_id}/archive", response_model=CampaignSeat)
def archive_seat(
    room_id: UUID,
    campaign_id: UUID,
    seat_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SeatService = Depends(get_seat_service),
) -> CampaignSeat:
    _require_seat_mutation_authority(
        context=context,
        service=service,
        room_id=room_id,
        campaign_id=campaign_id,
        seat_id=seat_id,
    )
    try:
        return service.archive_seat(context.room_id, campaign_id, seat_id)
    except Exception as exc:
        raise _map_seat_error(exc) from exc


@router.delete("/seats/{seat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_seat(
    room_id: UUID,
    campaign_id: UUID,
    seat_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SeatService = Depends(get_seat_service),
) -> Response:
    _require_seat_mutation_authority(
        context=context,
        service=service,
        room_id=room_id,
        campaign_id=campaign_id,
        seat_id=seat_id,
    )
    try:
        service.delete_seat(context.room_id, campaign_id, seat_id)
    except Exception as exc:
        raise _map_seat_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/lobby", response_model=LobbySnapshot)
def get_lobby(
    room_id: UUID,
    campaign_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SeatService = Depends(get_seat_service),
) -> LobbySnapshot:
    try:
        return service.lobby(
            context.room_id,
            campaign_id,
            caller_access_session_id=context.access_session_id,
        )
    except Exception as exc:
        raise _map_seat_error(exc) from exc


__all__ = ["_require_dm_seat_management", "_require_non_dm_seat_management", "router"]
