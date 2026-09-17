from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.rooms.access import get_room_access_context
from app.api.rooms.combat import _actor_from_request, _map_combat_error
from app.api.rooms.dependencies import (
    get_monster_instance_service,
    get_table_event_service,
)
from app.domain.combat.monster_instances import (
    CreateMonsterFromContentInput,
    CreateQuickEnemyInput,
    MonsterInstancePatchInput,
    MonsterInstanceService,
    MonsterInstanceView,
)
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.table_events import TableEventService


router = APIRouter(
    prefix=(
        "/api/rooms/{room_id}/campaigns/{campaign_id}"
        "/sessions/{session_id}/monster-instances"
    ),
    tags=["room-monster-instances"],
)


@router.get("", response_model=list[MonsterInstanceView])
def list_monster_instances(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: MonsterInstanceService = Depends(get_monster_instance_service),
) -> list[MonsterInstanceView]:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return list(service.list_instances(actor))
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/from-content", response_model=MonsterInstanceView)
def create_monster_from_content(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    input_data: CreateMonsterFromContentInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: MonsterInstanceService = Depends(get_monster_instance_service),
) -> MonsterInstanceView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.create_from_content(actor, input_data)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.post("/quick-enemy", response_model=MonsterInstanceView)
def create_quick_enemy(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    input_data: CreateQuickEnemyInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: MonsterInstanceService = Depends(get_monster_instance_service),
) -> MonsterInstanceView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.create_quick_enemy(actor, input_data)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


@router.patch("/{instance_id}", response_model=MonsterInstanceView)
def update_monster_instance(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    instance_id: UUID,
    input_data: MonsterInstancePatchInput,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: MonsterInstanceService = Depends(get_monster_instance_service),
) -> MonsterInstanceView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.update_instance(actor, instance_id, input_data)
    except Exception as exc:
        raise _map_combat_error(exc) from exc


__all__ = ["router"]
