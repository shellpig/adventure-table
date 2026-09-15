from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_combat_attack_service,
    get_combat_initiative_service,
    get_combat_order_service,
    get_combat_resolution_service,
    get_combat_service,
    get_table_event_service,
)
from app.domain.combat.attack_definitions import (
    AttackDefinitionInvalidError,
    AttackDefinitionNotFoundError,
)
from app.domain.combat.attacks import (
    AttackDefinitionView,
    AttackRequestInput,
    AttackRequestView,
    AttackResolutionView,
    CombatAttackService,
)
from app.domain.combat.initiative import (
    CombatInitiativeService,
    FinalizeInitiativeInput,
    InitiativeInputError,
    InitiativeRequestResponse,
    InitiativeRollResponse,
    RequestInitiativeInput,
)
from app.domain.combat.lifecycle import (
    ActiveCombatExistsError,
    AddCharacterInput,
    AddMonsterInput,
    CombatActionInput,
    CombatActionView,
    CombatNotFoundError,
    CombatService,
    CombatStateConflictError,
    CombatView,
    ReactionWindowInput,
    StartCombatInput,
)
from app.domain.combat.order import CombatOrderService, ReorderInitiativeInput
from app.domain.combat.semantic_hp import (
    CombatResolutionService,
    SemanticDamageInput,
    SemanticHealingInput,
)
from app.domain.rooms.rolls import FormalRollInput, RollInputInvalidError
from app.domain.rooms.schemas import RoomAccessContext, StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
)
from app.persistence.characters import CharacterNotFoundError
from app.persistence.combat.attacks import (
    AttackRequestNotFoundPersistenceError,
    AttackRequestNotPendingPersistenceError,
    AttackStateConflictPersistenceError,
)
from app.persistence.combat.initiative import (
    InitiativeRequestNotFoundPersistenceError,
    InitiativeRequestNotPendingPersistenceError,
)
from app.persistence.combat.lifecycle import (
    CombatNotFoundPersistenceError,
    CombatStateConflictPersistenceError,
)
from app.persistence.combat.resolution import (
    CombatResolutionStateConflictError,
    CombatResolutionTargetNotFoundError,
    StoredSemanticResolution,
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


class CombatMutationInput(StrictModel):
    idempotency_key: str | None = None


def _map_combat_error(exc: Exception) -> APIError:
    if isinstance(
        exc,
        (
            TableEventNotFoundError,
            TableEventSessionNotFoundPersistenceError,
        ),
    ):
        return APIError(404, "session_not_found", "Session was not found for this table actor")
    if isinstance(
        exc,
        (
            TableEventActorUnauthorizedError,
            TableEventActorBindingStalePersistenceError,
        ),
    ):
        return APIError(403, "table_actor_unauthorized", str(exc))
    if isinstance(
        exc,
        (
            TableEventSessionNotActiveError,
            TableEventSessionNotActivePersistenceError,
        ),
    ):
        return APIError(409, "session_not_active", "Session is not active")
    if isinstance(
        exc,
        (
            CombatNotFoundError,
            CombatNotFoundPersistenceError,
        ),
    ):
        return APIError(404, "combat_not_found", str(exc))
    if isinstance(
        exc,
        (
            AttackRequestNotFoundPersistenceError,
            AttackDefinitionNotFoundError,
        ),
    ):
        return APIError(404, "attack_not_found", str(exc))
    if isinstance(exc, CombatResolutionTargetNotFoundError):
        return APIError(404, "combat_target_not_found", str(exc))
    if isinstance(exc, ActiveCombatExistsError):
        return APIError(409, "active_combat_exists", str(exc))
    if isinstance(
        exc,
        (
            CombatStateConflictError,
            CombatStateConflictPersistenceError,
            InitiativeRequestNotPendingPersistenceError,
            AttackRequestNotPendingPersistenceError,
            AttackStateConflictPersistenceError,
            CombatResolutionStateConflictError,
        ),
    ):
        return APIError(409, "combat_state_conflict", str(exc))
    if isinstance(exc, InitiativeRequestNotFoundPersistenceError):
        return APIError(404, "initiative_request_not_found", str(exc))
    if isinstance(exc, InitiativeInputError):
        return APIError(422, "invalid_initiative_input", str(exc))
    if isinstance(exc, AttackDefinitionInvalidError):
        return APIError(422, "invalid_attack_definition", str(exc))
    if isinstance(exc, RollInputInvalidError):
        return APIError(422, "invalid_roll_input", str(exc))
    if isinstance(exc, CharacterNotFoundError):
        return APIError(404, "character_not_found", str(exc))
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


def _actor_from_request(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext,
    event_service: TableEventService,
) -> TableActorContext:
    return _resolve_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        context=context,
        event_service=event_service,
    )


@router.get("", response_model=CombatView | None)
def get_active_combat(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatService = Depends(get_combat_service),
) -> CombatView | None:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.get_active_combat(actor)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/start", response_model=CombatView)
def start_combat(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: StartCombatInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatService = Depends(get_combat_service),
) -> CombatView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.start_quick_combat(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/entries/characters", response_model=CombatView)
def add_character(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: AddCharacterInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatService = Depends(get_combat_service),
) -> CombatView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.add_character(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/entries/monsters", response_model=CombatView)
def add_monster(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: AddMonsterInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatService = Depends(get_combat_service),
) -> CombatView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.add_monster(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/initiative/request", response_model=InitiativeRequestResponse)
def request_initiative(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: RequestInitiativeInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatInitiativeService = Depends(get_combat_initiative_service),
) -> InitiativeRequestResponse:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.request_initiative(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/initiative/roll", response_model=InitiativeRollResponse)
def roll_initiative(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: FormalRollInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatInitiativeService = Depends(get_combat_initiative_service),
) -> InitiativeRollResponse:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.complete_initiative(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.get("/initiative/suggested-order", response_model=list[UUID])
def suggested_order(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatInitiativeService = Depends(get_combat_initiative_service),
) -> tuple[UUID, ...]:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.suggested_order(actor)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.get("/initiative/ties", response_model=dict[int, tuple[UUID, ...]])
def initiative_ties(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatInitiativeService = Depends(get_combat_initiative_service),
) -> dict[int, tuple[UUID, ...]]:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.tied_totals(actor)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/initiative/finalize", response_model=CombatView)
def finalize_initiative(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: FinalizeInitiativeInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatInitiativeService = Depends(get_combat_initiative_service),
) -> CombatView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.finalize_initiative(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/initiative/reorder", response_model=CombatView)
def reorder_initiative(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: ReorderInitiativeInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatOrderService = Depends(get_combat_order_service),
) -> CombatView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.reorder_running(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/turn/advance", response_model=CombatView)
def advance_turn(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: CombatMutationInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatService = Depends(get_combat_service),
) -> CombatView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.advance_turn(actor, idempotency_key=payload.idempotency_key)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.get("/entries/{entry_id}/attacks", response_model=list[AttackDefinitionView])
def list_attacks(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    entry_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatAttackService = Depends(get_combat_attack_service),
) -> tuple[AttackDefinitionView, ...]:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.available_attacks(actor, entry_id)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/attacks/request", response_model=AttackRequestView)
def request_attack(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: AttackRequestInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatAttackService = Depends(get_combat_attack_service),
) -> AttackRequestView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.request_attack(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/attacks/roll", response_model=AttackResolutionView)
def roll_attack(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: FormalRollInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatAttackService = Depends(get_combat_attack_service),
) -> AttackResolutionView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.complete_attack(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/damage")
def apply_damage(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: SemanticDamageInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatResolutionService = Depends(get_combat_resolution_service),
) -> StoredSemanticResolution:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.apply_damage(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/healing")
def apply_healing(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: SemanticHealingInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatResolutionService = Depends(get_combat_resolution_service),
) -> StoredSemanticResolution:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.apply_healing(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/actions", response_model=CombatActionView)
def use_action(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: CombatActionInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatService = Depends(get_combat_service),
) -> CombatActionView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.use_action(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/reaction-window", response_model=CombatView)
def set_reaction_window(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: ReactionWindowInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatService = Depends(get_combat_service),
) -> CombatView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.set_reaction_window(actor, payload)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/entries/{entry_id}/withdraw", response_model=CombatView)
def withdraw_entry(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    entry_id: UUID,
    payload: CombatMutationInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatService = Depends(get_combat_service),
) -> CombatView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.withdraw_entry(
            actor,
            entry_id,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/entries/{entry_id}/remove", response_model=CombatView)
def remove_entry(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    entry_id: UUID,
    payload: CombatMutationInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatService = Depends(get_combat_service),
) -> CombatView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.remove_entry(
            actor,
            entry_id,
            idempotency_key=payload.idempotency_key,
        )
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/end", response_model=CombatView)
def end_combat(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: CombatMutationInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatService = Depends(get_combat_service),
) -> CombatView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.end_combat(actor, idempotency_key=payload.idempotency_key)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


__all__ = ["router"]
