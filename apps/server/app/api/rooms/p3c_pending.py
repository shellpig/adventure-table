from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_pending_action_service, get_table_event_service
from app.domain.rooms.exploration import ExplorationSubjectNotFoundError
from app.domain.rooms.pending_actions import (
    PendingActionCreateInput,
    PendingActionInvalidTransitionError,
    PendingActionNotFoundError,
    PendingActionRollBindingError,
    PendingActionService,
    PendingActionTransitionInput,
    PendingActionVersionConflictError,
    PendingActionView,
)
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
)
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
    tags=["room-pending-actions"],
)


def _map_pending_error(exc: Exception) -> APIError:
    if isinstance(exc, (TableEventNotFoundError, TableEventSessionNotFoundPersistenceError)):
        return APIError(404, "session_not_found", "Session was not found for this table actor")
    if isinstance(exc, (TableEventActorUnauthorizedError, TableEventActorBindingStalePersistenceError)):
        return APIError(403, "table_actor_unauthorized", str(exc))
    if isinstance(exc, (TableEventSessionNotActiveError, TableEventSessionNotActivePersistenceError)):
        return APIError(409, "session_not_active", "Session is not active")
    if isinstance(exc, ExplorationSubjectNotFoundError):
        return APIError(404, "exploration_subject_not_found", "Player Seat is not active in this Session")
    if isinstance(exc, PendingActionNotFoundError):
        return APIError(404, "pending_action_not_found", "PendingAction was not found in this Session")
    if isinstance(exc, PendingActionInvalidTransitionError):
        return APIError(409, "pending_action_invalid_transition", "PendingAction transition is not allowed")
    if isinstance(exc, PendingActionVersionConflictError):
        return APIError(409, "pending_action_version_conflict", "PendingAction changed since this view loaded")
    if isinstance(exc, PendingActionRollBindingError):
        return APIError(409, "pending_action_invalid_roll_binding", str(exc))
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


@router.get("/pending-actions", response_model=list[PendingActionView])
def list_pending_actions(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    pending_service: PendingActionService = Depends(get_pending_action_service),
) -> tuple[PendingActionView, ...]:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        return pending_service.list(actor)
    except Exception as exc:
        raise _map_pending_error(exc) from exc


@router.post("/pending-actions", response_model=PendingActionView)
def create_pending_action(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    request: PendingActionCreateInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    pending_service: PendingActionService = Depends(get_pending_action_service),
) -> PendingActionView:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        return pending_service.create(actor, request)
    except Exception as exc:
        raise _map_pending_error(exc) from exc


@router.post("/pending-actions/{action_id}/transition", response_model=PendingActionView)
def transition_pending_action(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    action_id: UUID,
    request: PendingActionTransitionInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    pending_service: PendingActionService = Depends(get_pending_action_service),
) -> PendingActionView:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        return pending_service.transition(actor, action_id, request)
    except Exception as exc:
        raise _map_pending_error(exc) from exc


__all__ = ["router"]
