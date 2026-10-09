"""M07-D D1 (F11): Session-scoped read-only library routes for the current DM.

A non-Owner Human sitting on the current DM Seat can list and read the Room
battle-map and monster libraries from inside a Session (the same read-only
surface the AI DM tools use). No authoring action is exposed here; management
routes stay Owner/DM-authority gated. Permission logic is reused verbatim
from ``MonsterLibraryService.list_for_actor`` / ``get_for_actor`` and
``BattleMapService.list_for_actor`` / ``get_for_actor``
(``actor.role == "dm" and actor.is_current_dm``).
"""

from __future__ import annotations

from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.battle_maps import _map_battle_map_error
from app.api.rooms.combat import _actor_from_request
from app.api.rooms.dependencies import (
    get_battle_map_service,
    get_monster_library_service,
    get_table_event_service,
)
from app.api.rooms.monster_library import _map_library_error
from app.domain.battle_maps.schemas import BattleMap, BattleMapSummary
from app.domain.battle_maps.service import BattleMapService
from app.domain.monster_library.schemas import (
    MonsterLibraryDetailView,
    MonsterLibrarySummaryView,
)
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.table_events import (
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
)
from app.persistence.rooms.table_runtime import (
    TableEventActorBindingStalePersistenceError,
    TableEventSessionNotFoundPersistenceError,
)

router = APIRouter(
    prefix=(
        "/api/rooms/{room_id}/campaigns/{campaign_id}"
        "/sessions/{session_id}/libraries"
    ),
    tags=["room-session-libraries"],
)


def _map_session_library_error(exc: Exception) -> APIError:
    if isinstance(exc, (TableEventNotFoundError, TableEventSessionNotFoundPersistenceError)):
        return APIError(404, "session_not_found", "Session was not found for this table actor")
    if isinstance(exc, (TableEventActorUnauthorizedError, TableEventActorBindingStalePersistenceError)):
        return APIError(403, "table_actor_unauthorized", str(exc))
    for mapper in (_map_library_error, _map_battle_map_error):
        try:
            return mapper(exc)
        except Exception as unmapped:
            if unmapped is not exc:
                raise
            continue
    raise exc


@router.get("/battle-maps", response_model=list[BattleMapSummary])
def list_session_battle_maps(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    include_archived: bool = Query(default=False),
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: BattleMapService = Depends(get_battle_map_service),
) -> list[BattleMapSummary]:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.list_for_actor(actor, include_archived=include_archived)
    except Exception as exc:
        raise _map_session_library_error(exc) from exc


@router.get("/battle-maps/{map_id}", response_model=BattleMap)
def get_session_battle_map(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    map_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: BattleMapService = Depends(get_battle_map_service),
) -> BattleMap:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.get_for_actor(actor, map_id)
    except Exception as exc:
        raise _map_session_library_error(exc) from exc


@router.get("/monster-library", response_model=list[MonsterLibrarySummaryView])
def list_session_monster_library(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    query: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: str = Query(default="all"),
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: MonsterLibraryService = Depends(get_monster_library_service),
) -> list[MonsterLibrarySummaryView]:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.list_for_actor(
            actor,
            room_id,
            query=query,
            limit=limit,
            offset=offset,
            source=source,
            include_archived=include_archived,
        )
    except Exception as exc:
        raise _map_session_library_error(exc) from exc


@router.get("/monster-library/{ref}", response_model=MonsterLibraryDetailView)
def get_session_monster_library_entry(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    ref: str,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    service: MonsterLibraryService = Depends(get_monster_library_service),
) -> MonsterLibraryDetailView:
    try:
        actor = _actor_from_request(room_id, campaign_id, session_id, context, event_service)
        return service.get_for_actor(actor, room_id, ref=unquote(ref))
    except Exception as exc:
        raise _map_session_library_error(exc) from exc


__all__ = ["router"]
