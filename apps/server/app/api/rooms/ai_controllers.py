from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.dependencies import get_database_engine
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_seat_service, get_table_event_service
from app.domain.rooms.ai_controllers import (
    AIControllerGrantView,
    AIControllerHandoffError,
    AIControllerService,
    AIHandoffRequest,
    AIHumanReassignmentRequest,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.seats import (
    ControllerKind,
    SeatControllerError,
    SeatControllerPatch,
    SeatNotFoundError,
    SeatRole,
    SeatService,
)
from app.persistence.mcp.lifecycle import revoke_grant_authorizations_in_transaction
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository


router = APIRouter(
    prefix="/api/rooms/{room_id}/campaigns/{campaign_id}",
    tags=["ai-controllers"],
)


def get_ai_controller_service(request: Request) -> AIControllerService:
    service = getattr(request.app.state, "ai_controller_service", None)
    if service is None:
        service = AIControllerService(
            AIControllerGrantRepository(
                get_database_engine(request),
                grant_authorization_revoker=revoke_grant_authorizations_in_transaction,
            ),
            get_table_event_service(request),
        )
        request.app.state.ai_controller_service = service
    return service


def _map_error(exc: Exception) -> APIError:
    if isinstance(exc, AIControllerHandoffError):
        return APIError(409, "ai_controller_handoff_invalid", str(exc))
    if isinstance(exc, SeatNotFoundError):
        return APIError(404, "seat_not_found", "Seat was not found in this Campaign")
    if isinstance(exc, SeatControllerError):
        return APIError(409, "seat_controller_invalid", str(exc))
    raise exc


def _require_admin(context: RoomAccessContext) -> None:
    if context.authority not in {RoomAccessAuthority.OWNER, RoomAccessAuthority.DM}:
        raise APIError(
            403,
            "seat_management_authority_required",
            "Owner or DM authority is required",
        )


def _require_owner(context: RoomAccessContext) -> None:
    if context.authority is not RoomAccessAuthority.OWNER:
        raise APIError(403, "room_owner_required", "Owner authority is required")


@router.post(
    "/sessions/{session_id}/seats/{seat_id}/ai-control",
    response_model=AIControllerGrantView,
    status_code=status.HTTP_201_CREATED,
)
def let_ai_control_player(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    seat_id: UUID,
    payload: AIHandoffRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AIControllerService = Depends(get_ai_controller_service),
) -> AIControllerGrantView:
    try:
        return service.let_ai_control_player(
            room_id=context.room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            seat_id=seat_id,
            context=context,
            request=payload,
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post(
    "/sessions/{session_id}/seats/{seat_id}/take-back",
    status_code=status.HTTP_204_NO_CONTENT,
)
def take_back_player(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    seat_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AIControllerService = Depends(get_ai_controller_service),
) -> Response:
    try:
        service.take_back_player(
            room_id=context.room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            seat_id=seat_id,
            context=context,
        )
    except Exception as exc:
        raise _map_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/{session_id}/seats/{seat_id}/reassign-human",
    status_code=status.HTTP_204_NO_CONTENT,
)
def administratively_reassign_player(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    seat_id: UUID,
    payload: AIHumanReassignmentRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AIControllerService = Depends(get_ai_controller_service),
) -> Response:
    _require_admin(context)
    try:
        service.administratively_reassign_player(
            room_id=context.room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            seat_id=seat_id,
            target_access_session_id=payload.target_access_session_id,
            admin_context=context,
        )
    except Exception as exc:
        raise _map_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/seats/{seat_id}/ai-dm-grant",
    response_model=AIControllerGrantView,
    status_code=status.HTTP_201_CREATED,
)
def configure_pre_session_ai_dm(
    room_id: UUID,
    campaign_id: UUID,
    seat_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: AIControllerService = Depends(get_ai_controller_service),
) -> AIControllerGrantView:
    _require_owner(context)
    try:
        return service.configure_pre_session_ai_dm(
            room_id=context.room_id,
            campaign_id=campaign_id,
            seat_id=seat_id,
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.delete(
    "/seats/{seat_id}/ai-dm-grant",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_pre_session_ai_dm(
    room_id: UUID,
    campaign_id: UUID,
    seat_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    seat_service: SeatService = Depends(get_seat_service),
) -> Response:
    _require_owner(context)
    try:
        seat = seat_service.get_scoped_seat(context.room_id, campaign_id, seat_id)
        if seat.role != SeatRole.DM.value or seat.controller_kind != ControllerKind.AI.value:
            raise SeatControllerError("Seat does not have a current pre-session AI DM grant")
        seat_service.set_controller(
            context.room_id,
            campaign_id,
            seat_id,
            SeatControllerPatch(controller_kind=ControllerKind.NONE),
        )
    except Exception as exc:
        raise _map_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["get_ai_controller_service", "router"]
