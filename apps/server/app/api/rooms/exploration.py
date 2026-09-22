from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_campaign_stage_service,
    get_exploration_action_service,
    get_exploration_stage_service,
    get_table_event_service,
)
from app.domain.campaign_runtime.errors import (
    CampaignRuntimeAuthorityError,
    CampaignRuntimeNotFoundError,
    CampaignRuntimeRevisionConflictError,
    CampaignRuntimeSessionNotActiveError,
    CampaignRuntimeValidationError,
)
from app.domain.campaign_runtime.stage import (
    CampaignStageBridgeService,
    StageImageSource,
    StageSourceInvalidError,
    StageSourceNotFoundError,
)
from app.domain.room_assets.schemas import (
    RoomAssetForbiddenError,
    RoomAssetNotFoundError,
    RoomAssetUnsupportedMediaTypeError,
)
from app.domain.rooms.exploration import (
    ExplorationActionService,
    ExplorationInputRequest,
    ExplorationStageService,
    ExplorationSubjectNotFoundError,
    StageImageInvalidError,
    StageImageNotFoundPersistenceError,
    StageRevisionConflictError,
    StageState,
    StageUpdateRequest,
)
from app.domain.rooms.schemas import RoomAccessContext, StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEvent,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
    TableEventSessionNotActiveError,
)


class SetStageImageSourceRequest(StrictModel):
    source: StageImageSource = Field(discriminator="kind")
    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=120)


router = APIRouter(
    prefix=(
        "/api/rooms/{room_id}/campaigns/{campaign_id}"
        "/sessions/{session_id}"
    ),
    tags=["room-exploration"],
)


def _map_exploration_error(exc: Exception) -> APIError:
    if isinstance(exc, APIError):
        return exc
    if isinstance(exc, TableEventNotFoundError):
        return APIError(404, "session_not_found", "Session was not found for this table actor")
    if isinstance(exc, (TableEventActorUnauthorizedError, CampaignRuntimeAuthorityError, RoomAssetForbiddenError)):
        return APIError(403, "table_actor_unauthorized", str(exc))
    if isinstance(exc, (TableEventSessionNotActiveError, CampaignRuntimeSessionNotActiveError)):
        return APIError(409, "session_not_active", "Session is not active")
    if isinstance(exc, ExplorationSubjectNotFoundError):
        return APIError(404, "exploration_subject_not_found", "Player Seat is not active in this Session")
    if isinstance(exc, (StageSourceNotFoundError, RoomAssetNotFoundError, CampaignRuntimeNotFoundError)):
        return APIError(404, "stage_source_not_found", str(exc))
    if isinstance(exc, StageImageNotFoundPersistenceError):
        return APIError(404, "stage_image_not_found", "Stage image was not found in this Room")
    if isinstance(
        exc,
        (
            StageSourceInvalidError,
            StageImageInvalidError,
            RoomAssetUnsupportedMediaTypeError,
            CampaignRuntimeValidationError,
        ),
    ):
        return APIError(422, "invalid_stage_image", str(exc))
    if isinstance(exc, (StageRevisionConflictError, CampaignRuntimeRevisionConflictError)):
        return APIError(409, "stage_revision_conflict", "Main Stage changed since this editor loaded")
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


@router.put("/stage/image-source", response_model=StageState)
def set_stage_image_source(
    room_id: UUID,
    campaign_id: UUID,
    session_id: UUID,
    request: SetStageImageSourceRequest,
    context: RoomAccessContext = Depends(get_room_access_context),
    event_service: TableEventService = Depends(get_table_event_service),
    campaign_stage_service: CampaignStageBridgeService = Depends(get_campaign_stage_service),
) -> StageState:
    try:
        actor = _resolve_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
            event_service=event_service,
        )
        return campaign_stage_service.set_stage_image(
            actor,
            request.source,
            expected_revision=request.expected_revision,
            idempotency_key=request.idempotency_key,
        )
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
        return Response(
            content=image.data,
            media_type=image.media_type,
            headers={"Cache-Control": "private, no-store"},
        )
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
