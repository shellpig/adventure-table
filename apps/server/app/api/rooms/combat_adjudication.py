from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.rooms.access import get_room_access_context
from app.api.rooms.combat import _actor_from_request, _map_combat_error
from app.api.rooms.dependencies import get_combat_attack_service, get_table_event_service
from app.domain.combat.attacks import (
    AttackAdjudicationInput,
    AttackRequestView,
    CombatAttackService,
)
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.table_events import TableEventService


router = APIRouter(
    prefix=(
        "/api/rooms/{room_id}/campaigns/{campaign_id}"
        "/sessions/{session_id}/combat"
    ),
    tags=["room-combat"],
)


@router.post("/attacks/adjudicate", response_model=AttackRequestView)
def adjudicate_attack(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: AttackAdjudicationInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatAttackService = Depends(get_combat_attack_service),
) -> AttackRequestView:
    try:
        actor = _actor_from_request(
            room_id,
            campaign_id,
            session_id,
            context,
            event_service,
        )
        return service.adjudicate_attack(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


__all__ = ["router"]
