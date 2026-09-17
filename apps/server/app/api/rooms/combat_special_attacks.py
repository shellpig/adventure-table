from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_combat_special_attack_service, get_table_event_service
from app.domain.combat.lifecycle import CombatNotFoundError, CombatStateConflictError
from app.domain.combat.special_attacks import (
    CombatSpecialAttackService,
    SpecialAttackAdjudicationInput,
    SpecialAttackNotFoundError,
    SpecialAttackRequestInput,
    SpecialAttackView,
)
from app.domain.rooms.rolls import FormalRollInput, RollInputInvalidError
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
)
from app.persistence.combat.special_attacks import SpecialAttackStateConflictError
from app.persistence.rooms.table_runtime import (
    TableEventActorBindingStalePersistenceError,
    TableEventSessionNotActivePersistenceError,
    TableEventSessionNotFoundPersistenceError,
)


router = APIRouter(
    prefix=(
        "/api/rooms/{room_id}/campaigns/{campaign_id}"
        "/sessions/{session_id}/combat/special-attacks"
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
    if isinstance(exc, CombatNotFoundError):
        return APIError(404, "combat_not_found", str(exc))
    if isinstance(exc, SpecialAttackNotFoundError):
        return APIError(404, "special_attack_not_found", str(exc))
    if isinstance(exc, (CombatStateConflictError, SpecialAttackStateConflictError)):
        return APIError(409, "combat_state_conflict", str(exc))
    if isinstance(exc, (RollInputInvalidError, ValueError)):
        return APIError(422, "invalid_combat_input", str(exc))
    raise exc


@router.post("/request", response_model=SpecialAttackView)
def request_special_attack(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: SpecialAttackRequestInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatSpecialAttackService = Depends(get_combat_special_attack_service),
) -> SpecialAttackView:
    try:
        return service.request_special_attack(
            _actor(room_id, campaign_id, session_id, context, event_service), payload
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/adjudicate", response_model=SpecialAttackView)
def adjudicate_special_attack(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: SpecialAttackAdjudicationInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatSpecialAttackService = Depends(get_combat_special_attack_service),
) -> SpecialAttackView:
    try:
        return service.adjudicate_special_attack(
            _actor(room_id, campaign_id, session_id, context, event_service), payload
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/roll", response_model=SpecialAttackView)
def roll_special_attack(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: FormalRollInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatSpecialAttackService = Depends(get_combat_special_attack_service),
) -> SpecialAttackView:
    try:
        return service.complete_special_attack_roll(
            _actor(room_id, campaign_id, session_id, context, event_service), payload
        )
    except Exception as exc:
        raise _map_error(exc) from exc


__all__ = ["router"]
