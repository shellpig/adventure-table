from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.rooms.access import get_room_access_context
from app.api.rooms.combat import _actor_from_request, _map_combat_error
from app.api.rooms.dependencies import (
    get_combat_adjudication_service,
    get_combat_attack_service,
    get_table_event_service,
)
from app.domain.combat.adjudication_service import (
    AdjudicationDecisionInput,
    CombatAdjudicationService,
    CombatAdjudicationView,
    OpportunityAttackRequestInput,
    SpecialAdjudicationRequestInput,
)
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


@router.get("/adjudications", response_model=list[CombatAdjudicationView])
def list_pending_adjudications(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatAdjudicationService = Depends(get_combat_adjudication_service),
) -> list[CombatAdjudicationView]:
    try:
        actor = _actor_from_request(
            room_id,
            campaign_id,
            session_id,
            context,
            event_service,
        )
        return list(service.list_pending(actor))
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/adjudications/opportunity-attack", response_model=CombatAdjudicationView)
def request_opportunity_attack(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: OpportunityAttackRequestInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatAdjudicationService = Depends(get_combat_adjudication_service),
) -> CombatAdjudicationView:
    try:
        actor = _actor_from_request(
            room_id,
            campaign_id,
            session_id,
            context,
            event_service,
        )
        return service.request_opportunity_attack(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/adjudications/special", response_model=CombatAdjudicationView)
def request_special(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: SpecialAdjudicationRequestInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatAdjudicationService = Depends(get_combat_adjudication_service),
) -> CombatAdjudicationView:
    try:
        actor = _actor_from_request(
            room_id,
            campaign_id,
            session_id,
            context,
            event_service,
        )
        return service.request_special(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/adjudications/{action_id}/resolve", response_model=CombatAdjudicationView)
def resolve_adjudication(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    action_id: UUID,
    payload: AdjudicationDecisionInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatAdjudicationService = Depends(get_combat_adjudication_service),
) -> CombatAdjudicationView:
    try:
        actor = _actor_from_request(
            room_id,
            campaign_id,
            session_id,
            context,
            event_service,
        )
        return service.resolve_adjudication(actor, action_id, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


__all__ = ["router"]
