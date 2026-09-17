from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_combat_reaction_service,
    get_table_event_service,
)
from app.domain.combat.lifecycle import CombatNotFoundError, CombatStateConflictError
from app.domain.combat.reaction_service import (
    CombatReactionNotFoundError,
    CombatReactionService,
    CombatReactionStateConflictError,
    OpenReactionInput,
    ReactionResolutionView,
    ReactionWindowView,
    ResolveReactionInput,
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
        "/sessions/{session_id}/combat"
    ),
    tags=["room-combat"],
)


def _actor(
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


def _map_error(exc: Exception) -> APIError:
    if isinstance(exc, (TableEventNotFoundError, TableEventSessionNotFoundPersistenceError)):
        return APIError(404, "session_not_found", "Session was not found for this table actor")
    if isinstance(exc, (TableEventActorUnauthorizedError, TableEventActorBindingStalePersistenceError)):
        return APIError(403, "table_actor_unauthorized", str(exc))
    if isinstance(exc, (TableEventSessionNotActiveError, TableEventSessionNotActivePersistenceError)):
        return APIError(409, "session_not_active", "Session is not active")
    if isinstance(exc, (CombatNotFoundError, CombatReactionNotFoundError)):
        return APIError(404, "combat_not_found", str(exc))
    if isinstance(exc, (CombatStateConflictError, CombatReactionStateConflictError)):
        return APIError(409, "combat_state_conflict", str(exc))
    if isinstance(exc, ValueError):
        return APIError(422, "invalid_combat_input", str(exc))
    raise exc


@router.post("/reactions/open", response_model=ReactionWindowView)
def open_reaction(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: OpenReactionInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatReactionService = Depends(get_combat_reaction_service),
) -> ReactionWindowView:
    try:
        return service.open_reaction_window(
            _actor(room_id, campaign_id, session_id, context, event_service), payload
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/reactions/resolve", response_model=ReactionResolutionView)
def resolve_reaction(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: ResolveReactionInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatReactionService = Depends(get_combat_reaction_service),
) -> ReactionResolutionView:
    try:
        return service.resolve_reaction(
            _actor(room_id, campaign_id, session_id, context, event_service), payload
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.get("/entries/{entry_id}/reaction", response_model=ReactionWindowView | None)
def get_reaction_window(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    entry_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatReactionService = Depends(get_combat_reaction_service),
) -> ReactionWindowView | None:
    try:
        return service.get_reaction_window(
            _actor(room_id, campaign_id, session_id, context, event_service), entry_id
        )
    except Exception as exc:
        raise _map_error(exc) from exc


__all__ = ["router"]
