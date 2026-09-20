from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_campaign_adventure_service
from app.domain.adventures.attachments import CampaignAdventureService
from app.domain.adventures.schemas import (
    AdventureAlreadyAttachedError,
    AdventureForbiddenError,
    AdventureNotFinalizedError,
    AdventureNotFoundError,
    AttachedAdventure,
    CampaignAdventureAttach,
    CampaignAdventureLinkNotFoundError,
)
from app.domain.rooms.campaigns import CampaignNotFoundError
from app.domain.rooms.schemas import RoomAccessContext

router = APIRouter(
    prefix="/api/rooms/{room_id}/campaigns/{campaign_id}/adventures",
    tags=["campaign-adventures"],
)


def _map_campaign_adventure_error(exc: Exception) -> APIError:
    if isinstance(exc, CampaignNotFoundError):
        return APIError(404, "campaign_not_found", str(exc))
    if isinstance(exc, (AdventureNotFoundError, AdventureForbiddenError)):
        return APIError(404, "adventure_not_found", str(exc))
    if isinstance(exc, AdventureNotFinalizedError):
        return APIError(409, "adventure_not_finalized", str(exc))
    if isinstance(exc, AdventureAlreadyAttachedError):
        return APIError(409, "adventure_already_attached", str(exc))
    if isinstance(exc, CampaignAdventureLinkNotFoundError):
        return APIError(404, "campaign_adventure_link_not_found", str(exc))
    raise exc


@router.get("", response_model=list[AttachedAdventure])
def list_campaign_adventures(
    room_id: UUID,
    campaign_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignAdventureService = Depends(get_campaign_adventure_service),
  ) -> list[AttachedAdventure]:
    try:
        return service.list(context, room_id=room_id, campaign_id=campaign_id)
    except Exception as exc:
        raise _map_campaign_adventure_error(exc) from exc


@router.post("", response_model=AttachedAdventure, status_code=status.HTTP_201_CREATED)
def attach_campaign_adventure(
    room_id: UUID,
    campaign_id: UUID,
    payload: CampaignAdventureAttach,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignAdventureService = Depends(get_campaign_adventure_service),
) -> AttachedAdventure:
    try:
        return service.attach(
            context, room_id=room_id, campaign_id=campaign_id, payload=payload
        )
    except Exception as exc:
        raise _map_campaign_adventure_error(exc) from exc


@router.delete("/{adventure_id}", status_code=status.HTTP_204_NO_CONTENT)
def detach_campaign_adventure(
    room_id: UUID,
    campaign_id: UUID,
    adventure_id: UUID,
    context: RoomAccessContext = Depends(get_room_access_context),
    service: CampaignAdventureService = Depends(get_campaign_adventure_service),
) -> Response:
    try:
        service.detach(
            context, room_id=room_id, campaign_id=campaign_id, adventure_id=adventure_id
        )
    except Exception as exc:
        raise _map_campaign_adventure_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
