from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_table_event_service
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventPage,
    TableEventService,
    TableRuntimeCursor,
)


router = APIRouter(
    prefix=(
        "/api/rooms/{room_id}/campaigns/{campaign_id}"
        "/sessions/{session_id}"
    ),
    tags=["room-table-events"],
)


def _map_table_event_error(exc: Exception) -> APIError:
    if isinstance(exc, TableEventNotFoundError):
        return APIError(404, "session_not_found", "Session was not found for this table actor")
    if isinstance(exc, TableEventActorUnauthorizedError):
        return APIError(403, "table_actor_unauthorized", str(exc))
    raise exc


def _resolve_actor(
    *,
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext,
    service: TableEventService,
) -> TableActorContext:
    return service.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        context=context,
    )


@router.get("/runtime", response_model=TableRuntimeCursor)
def get_table_runtime_cursor(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: TableEventService = Depends(get_table_event_service),
) -> TableRuntimeCursor:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            service=service,
        )
        return service.current_cursor(actor)
    except Exception as exc:
        raise _map_table_event_error(exc) from exc


@router.get("/events", response_model=TableEventPage)
def list_table_events(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    after_seq: int = Query(default=0, alias="after", ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    context: RoomAccessContext = Depends(get_room_access_context),
    service: TableEventService = Depends(get_table_event_service),
) -> TableEventPage:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            service=service,
        )
        return service.list_after(actor, after_seq=after_seq, limit=limit)
    except Exception as exc:
        raise _map_table_event_error(exc) from exc


@router.get("/events/wait", response_model=TableEventPage)
async def wait_table_events(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    after_seq: int = Query(default=0, alias="after", ge=0),
    limit: int = Query(default=100, ge=1, le=200),
    timeout: float = Query(default=30.0, ge=0.0, le=60.0),
    context: RoomAccessContext = Depends(get_room_access_context),
    service: TableEventService = Depends(get_table_event_service),
) -> TableEventPage:
    """Non-blocking long-poll over the durable P3 event cursor.

    Actor resolution is one short synchronous DB operation and is offloaded.
    TableEventService.wait_after likewise offloads only short DB rechecks; the
    idle timeout itself stays in this async request task and owns no DB handle.
    """

    try:
        actor = await run_in_threadpool(
            _resolve_actor,
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            service=service,
        )
        return await service.wait_after(
            actor,
            after_seq=after_seq,
            limit=limit,
            timeout=timeout,
        )
    except Exception as exc:
        raise _map_table_event_error(exc) from exc


__all__ = ["router", "wait_table_events"]
