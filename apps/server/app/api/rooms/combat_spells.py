from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_combat_concentration_service,
    get_combat_spell_service,
    get_table_event_service,
)
from app.domain.combat.concentration import (
    CombatConcentrationNotFoundError,
    CombatConcentrationService,
    CombatConcentrationStateConflictError,
    ConcentrationCheckResultView,
    DropConcentrationView,
)
from app.domain.combat.lifecycle import CombatNotFoundError, CombatStateConflictError
from app.domain.combat.spell_service import (
    AoeSpellProposalView,
    AoeSpellResolutionView,
    CastableSpellView,
    CastSpellInput,
    CombatSpellNotFoundError,
    CombatSpellService,
    CombatSpellStateConflictError,
    ProposeAoeSpellInput,
    ResolveAoeSpellInput,
    SpellCastView,
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
    if isinstance(exc, (CombatNotFoundError, CombatSpellNotFoundError, CombatConcentrationNotFoundError)):
        return APIError(404, "not_found", str(exc))
    if isinstance(exc, (CombatStateConflictError, CombatSpellStateConflictError, CombatConcentrationStateConflictError)):
        return APIError(409, "combat_state_conflict", str(exc))
    if isinstance(exc, (RollInputInvalidError, ValueError)):
        return APIError(422, "invalid_combat_input", str(exc))
    raise exc


class DropConcentrationInput(StrictModel):
    idempotency_key: str | None = None


@router.get("/entries/{entry_id}/spells", response_model=list[CastableSpellView])
def list_castable_spells(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    entry_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatSpellService = Depends(get_combat_spell_service),
) -> tuple[CastableSpellView, ...]:
    try:
        return service.available_spells(
            _actor(room_id, campaign_id, session_id, context, event_service), entry_id
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/spells/cast", response_model=SpellCastView)
def cast_spell(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: CastSpellInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatSpellService = Depends(get_combat_spell_service),
) -> SpellCastView:
    try:
        return service.cast_spell(
            _actor(room_id, campaign_id, session_id, context, event_service), payload
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/spells/aoe/propose", response_model=AoeSpellProposalView)
def propose_aoe(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: ProposeAoeSpellInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatSpellService = Depends(get_combat_spell_service),
) -> AoeSpellProposalView:
    try:
        return service.propose_aoe(
            _actor(room_id, campaign_id, session_id, context, event_service), payload
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/spells/aoe/resolve", response_model=AoeSpellResolutionView)
def resolve_aoe(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: ResolveAoeSpellInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatSpellService = Depends(get_combat_spell_service),
) -> AoeSpellResolutionView:
    try:
        return service.resolve_aoe(
            _actor(room_id, campaign_id, session_id, context, event_service), payload
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/concentration/roll", response_model=ConcentrationCheckResultView)
def roll_concentration_check(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    payload: FormalRollInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatConcentrationService = Depends(get_combat_concentration_service),
) -> ConcentrationCheckResultView:
    try:
        return service.complete_check(
            _actor(room_id, campaign_id, session_id, context, event_service), payload
        )
    except Exception as exc:
        raise _map_error(exc) from exc


@router.post("/entries/{entry_id}/concentration/drop", response_model=DropConcentrationView)
def drop_concentration(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    entry_id: UUID,
    payload: DropConcentrationInput | None = None,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: CombatConcentrationService = Depends(get_combat_concentration_service),
) -> DropConcentrationView:
    try:
        key = payload.idempotency_key if payload is not None else None
        return service.drop_concentration(
            _actor(room_id, campaign_id, session_id, context, event_service),
            entry_id,
            idempotency_key=key,
        )
    except Exception as exc:
        raise _map_error(exc) from exc


__all__ = ["router"]
