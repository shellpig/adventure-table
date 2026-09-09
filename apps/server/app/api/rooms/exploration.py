from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_exploration_action_service,
    get_exploration_stage_service,
    get_table_event_service,
)
from app.domain.rooms.exploration import (
    ExplorationActionService,
    ExplorationInputRequest,
    ExplorationStageService,
    ExplorationSubjectNotFoundError,
    StageImageInvalidError,
    StageImageNotFoundPersistenceError,
    StageState,
    StageUpdateRequest,
)
from app.domain.rooms.schemas import RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEvent,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
)


router = APIRouter(
    prefix=(
        "/api/rooms/{room_id}/campaigns/{campaign_id}"
        "/sessions/{session_id}"
    ),
    tags=["room-exploration"],
)


def _map_exploration_error(exc: Exception) -> APIError:
    if isinstance(exc, TableEventNotFoundError):
        return APIError(404, "session_not_found", "Session was not found for this table actor")
    if isinstance(exc, TableEventActorUnauthorizedError):
        return APIError(403, "table_actor_unauthorized", str(exc))
    if isinstance(exc, TableEventSessionNotActiveError):
        return APIError(409, "session_not_active", "Session is not active")
    if isinstance(exc, ExplorationSubjectNotFoundError):
        return APIError(404, "exploration_subject_not_found", "Player Seat is not active in this Session")
    if isinstance(exc, StageImageNotFoundPersistenceError):
        return APIError(404, "stage_image_not_found", "Stage image was not found in this Room")
    if isinstance(exc, StageImageInvalidError):
        return APIError(422, "invalid_stage_image", str(exc))
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


@router.get("/stage", response_model=StageState)
def get_stage(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    stage_service: ExplorationStageService = Depends(get_exploration_stage_service),
) -> StageState:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        return stage_service.get_stage(actor)
    except Exception as exc:
        raise _map_exploration_error(exc) from exc


@router.put("/stage", response_model=StageState)
def replace_stage(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    request: StageUpdateRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    stage_service: ExplorationStageService = Depends(get_exploration_stage_service),
) -> StageState:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        return stage_service.replace_stage(actor, request)
    except Exception as exc:
        raise _map_exploration_error(exc) from exc


@router.get("/stage/images/{image_id}")
def get_stage_image(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    image_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    stage_service: ExplorationStageService = Depends(get_exploration_stage_service),
) -> Response:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        image = stage_service.get_image(actor, image_id)
        headers = {"Cache-Control": "private, no-store"}
        if image.filename:
            safe_name = image.filename.replace('"', "")
            headers["Content-Disposition"] = f'inline; filename="{safe_name}"'
        return Response(content=image.data, media_type=image.media_type, headers=headers)
    except Exception as exc:
        raise _map_exploration_error(exc) from exc


@router.post("/exploration", response_model=TableEvent)
def send_exploration_input(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    request: ExplorationInputRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    action_service: ExplorationActionService = Depends(get_exploration_action_service),
) -> TableEvent:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        return action_service.send(actor, request)
    except Exception as exc:
        raise _map_exploration_error(exc) from exc


__all__ = ["router"]
