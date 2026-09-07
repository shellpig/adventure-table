from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_session_resume_service, get_session_service
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.session_resume import SessionResumeDTO, SessionResumeService
from app.domain.rooms.sessions import (
    CharacterAlreadyInActiveSessionError,
    DMControllerMismatchError,
    SessionActiveCharacterLockedError,
    SessionActiveCharacterPatch,
    SessionAlreadyActiveError,
    SessionLateJoinError,
    SessionLateJoinRequest,
    SessionLobbyUnavailableError,
    SessionNotActiveError,
    SessionNotFoundError,
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
    if isinstance(exc, SessionActiveCharacterLockedError):
        return APIError(409, "session_active_character_locked", str(exc))
    if isinstance(exc, SessionLateJoinError):
        return APIError(409, "seat_character_invalid", str(exc))
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


@router.get("/sessions/active", response_model=SessionResumeDTO)
def resume_session(
    room_id: UUID,
    campaign_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SessionResumeService = Depends(get_session_resume_service),
) -> SessionResumeDTO:
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


@router.post("/sessions/{session_id}/late-join", response_model=SessionSnapshot)
def late_join(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: SessionLateJoinRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SessionService = Depends(get_session_service),
) -> SessionSnapshot:
    try:
        return service.late_join(
            context.room_id,
            campaign_id,
            session_id,
            payload,
            context,
        )
    except Exception as exc:
        raise _map_session_error(exc) from exc


@router.patch(
    "/sessions/{session_id}/participants/{participant_id}/character",
    status_code=status.HTTP_409_CONFLICT,
)
def reject_active_character_change(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    participant_id: UUID,
    payload: SessionActiveCharacterPatch,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: SessionService = Depends(get_session_service),
) -> Response:
    try:
        service.assert_active_character_locked(
            context.room_id,
            campaign_id,
            session_id,
            participant_id,
            payload,
        )
    except Exception as exc:
        raise _map_session_error(exc) from exc
    raise APIError(
        409,
        "session_active_character_locked",
        "Active Character is immutable after Session participation begins",
    )


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
