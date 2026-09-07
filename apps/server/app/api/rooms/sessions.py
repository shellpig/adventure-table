from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_session_service
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.sessions import (
    CharacterAlreadyInActiveSessionError,
    DMControllerMismatchError,
    SessionAlreadyActiveError,
    SessionLobbyUnavailableError,
    SessionNotActiveError,
    SessionNotFoundError,
    SessionResume,
    SessionService,
    SessionSnapshot,
)


router = APIRouter(
    prefix="/api/rooms/{room_id}/campaigns/{campaign_id}",
    tags=["room-sessions"],
)


def _map_session_error(exc: Exception) -> APIError:
    if isinstance(exc, SessionNotFoundError):
        return APIError(404, "session_not_found", "Session was not found in this Room Campaign")
    if isinstance(exc, SessionAlreadyActiveError):
        return APIError(409, "session_already_active", "Campaign already has an active Session")
    if isinstance(exc, CharacterAlreadyInActiveSessionError):
        return APIError(
            409,
            "character_already_in_active_session",
            "A selected Character is already active in another Session",
        )
    if isinstance(exc, DMControllerMismatchError):
        return APIError(403, "dm_controller_mismatch", str(exc))
    if isinstance(exc, SessionNotActiveError):
        return APIError(409, "session_not_active", "Session is not active")
    if isinstance(exc, SessionLobbyUnavailableError):
        return APIError(409, "lobby_unavailable", str(exc))
    raise exc


@router.post("/sessions", response_model=SessionSnapshot, status_code=status.HTTP_201_CREATED)
def start_session(
    room_id: UUID,
    campaign_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SessionService = Depends(get_session_service),
) -> SessionSnapshot:
    try:
        return service.start_session(context.room_id, campaign_id, context)
    except Exception as exc:
        raise _map_session_error(exc) from exc


@router.get("/sessions/active", response_model=SessionResume)
def resume_session(
    room_id: UUID,
    campaign_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SessionService = Depends(get_session_service),
) -> SessionResume:
    try:
        return service.resume(context.room_id, campaign_id)
    except Exception as exc:
        raise _map_session_error(exc) from exc


@router.get("/sessions/{session_id}", response_model=SessionSnapshot)
def get_session(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SessionService = Depends(get_session_service),
) -> SessionSnapshot:
    try:
        return service.get_session(context.room_id, campaign_id, session_id)
    except Exception as exc:
        raise _map_session_error(exc) from exc


@router.post("/sessions/{session_id}/end", response_model=SessionSnapshot)
def end_session(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SessionService = Depends(get_session_service),
) -> SessionSnapshot:
    try:
        return service.end_session(context.room_id, campaign_id, session_id, context)
    except Exception as exc:
        raise _map_session_error(exc) from exc


@router.post("/sessions/{session_id}/abandon", response_model=SessionSnapshot)
def abandon_session(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SessionService = Depends(get_session_service),
) -> SessionSnapshot:
    try:
        return service.abandon_session(context.room_id, campaign_id, session_id, context)
    except Exception as exc:
        raise _map_session_error(exc) from exc


__all__ = ["router"]
