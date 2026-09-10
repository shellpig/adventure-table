from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_roll_service, get_table_event_service
from app.domain.rooms.exploration import ExplorationSubjectNotFoundError
from app.domain.rooms.rolls import (
    FormalRollInput,
    QuickRollInput,
    RequestCheckInput,
    RollInputInvalidError,
    RollRequestAlreadyResolvedError,
    RollRequestNotFoundError,
    RollRequestView,
    RollResultView,
    RollService,
    RollVisibility,
)
from app.domain.rooms.schemas import RoomAccessContext, StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
)
from app.persistence.characters import CharacterNotFoundError
from app.persistence.rooms.table_runtime import (
    TableEventActorBindingStalePersistenceError,
    TableEventSessionNotActivePersistenceError,
    TableEventSessionNotFoundPersistenceError,
)


router = APIRouter(
    prefix=(
        "/api/rooms/{room_id}/campaigns/{campaign_id}"
        "/sessions/{session_id}"
    ),
    tags=["room-rolls"],
)


class RequestCheckResponse(StrictModel):
    roll_group_id: UUID
    requests: tuple[RollRequestView, ...]


class RollSubmissionResponse(StrictModel):
    result_id: UUID
    roll_request_id: UUID | None
    hidden: bool
    result: RollResultView | None


def _map_roll_error(exc: Exception) -> APIError:
    if isinstance(exc, (TableEventNotFoundError, TableEventSessionNotFoundPersistenceError)):
        return APIError(404, "session_not_found", "Session was not found for this table actor")
    if isinstance(exc, (TableEventActorUnauthorizedError, TableEventActorBindingStalePersistenceError)):
        return APIError(403, "table_actor_unauthorized", str(exc))
    if isinstance(exc, (TableEventSessionNotActiveError, TableEventSessionNotActivePersistenceError)):
        return APIError(409, "session_not_active", "Session is not active")
    if isinstance(exc, ExplorationSubjectNotFoundError):
        return APIError(404, "exploration_subject_not_found", "Player Seat is not active in this Session")
    if isinstance(exc, RollRequestNotFoundError):
        return APIError(404, "roll_request_not_found", "RollRequest was not found in this Session")
    if isinstance(exc, RollRequestAlreadyResolvedError):
        return APIError(409, "roll_request_already_resolved", "RollRequest is already resolved")
    if isinstance(exc, RollInputInvalidError):
        return APIError(422, "invalid_roll_input", str(exc))
    if isinstance(exc, CharacterNotFoundError):
        return APIError(409, "roll_character_not_found", "RollRequest Character is no longer available")
    raise exc


def _resolve_actor(
    *,
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext,
    event_service: TableEventService,
) -> TableActorContext:
    return event_service.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        context=context,
    )


def _submission_response(
    actor: TableActorContext,
    result: RollResultView,
) -> RollSubmissionResponse:
    # dm-only result details never cross the HTTP boundary to Player clients.
    # The acknowledgement exposes only durable identities so the UI can keep
    # its pending state coherent while waiting for DM adjudication.
    hidden = result.visibility is RollVisibility.DM_ONLY and not actor.is_current_dm
    return RollSubmissionResponse(
        result_id=result.id,
        roll_request_id=result.roll_request_id,
        hidden=hidden,
        result=None if hidden else result,
    )


@router.post("/checks", response_model=RequestCheckResponse)
def request_check(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    request: RequestCheckInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    roll_service: RollService = Depends(get_roll_service),
) -> RequestCheckResponse:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        group_id, requests = roll_service.request_check(actor, request)
        return RequestCheckResponse(roll_group_id=group_id, requests=requests)
    except Exception as exc:
        raise _map_roll_error(exc) from exc


@router.get("/roll-requests", response_model=list[RollRequestView])
def list_roll_requests(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    roll_service: RollService = Depends(get_roll_service),
) -> tuple[RollRequestView, ...]:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        return roll_service.list_requests(actor)
    except Exception as exc:
        raise _map_roll_error(exc) from exc


@router.post("/rolls/formal", response_model=RollSubmissionResponse)
def submit_formal_roll(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    request: FormalRollInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    roll_service: RollService = Depends(get_roll_service),
) -> RollSubmissionResponse:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        return _submission_response(actor, roll_service.complete_formal(actor, request))
    except Exception as exc:
        raise _map_roll_error(exc) from exc


@router.post("/rolls/quick", response_model=RollSubmissionResponse)
def submit_quick_roll(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    request: QuickRollInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    roll_service: RollService = Depends(get_roll_service),
) -> RollSubmissionResponse:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        return _submission_response(actor, roll_service.quick_roll(actor, request))
    except Exception as exc:
        raise _map_roll_error(exc) from exc


__all__ = [
    "RequestCheckResponse",
    "RollSubmissionResponse",
    "router",
]
