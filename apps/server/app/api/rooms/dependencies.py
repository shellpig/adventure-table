from __future__ import annotations

from typing import Any

from fastapi import Request

from app.api.dependencies import get_content_registry, get_database_engine
from app.api.errors import APIError
from app.domain.rooms.campaigns import CampaignService
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.persistence.rooms.campaigns import CampaignRepository


class _HistoryGuardedCharacterRepository:
    """Web-only adapter that keeps Campaign history out of Character Core."""

    def __init__(self, delegate: Any, campaigns: CampaignRepository) -> None:
        self._delegate = delegate
        self._campaigns = campaigns

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def delete_character(self, character_id) -> None:
        if self._campaigns.character_is_referenced(character_id):
            raise APIError(
                409,
                "character_history_referenced",
                "Character is referenced by Campaign history and cannot be permanently deleted",
            )
        self._delegate.delete_character(character_id)


def get_room_workspace_service(request: Request) -> RoomCharacterWorkspaceService:
    service = getattr(request.app.state, "room_workspace_service", None)
    if service is None:
        engine = get_database_engine(request)
        service = RoomCharacterWorkspaceService(
            engine,
            get_content_registry(request),
        )
        service.character_repository = _HistoryGuardedCharacterRepository(
            service.character_repository,
            CampaignRepository(engine),
        )
        request.app.state.room_workspace_service = service
    return service


def get_campaign_service(request: Request) -> CampaignService:
    service = getattr(request.app.state, "campaign_service", None)
    if service is None:
        service = CampaignService(CampaignRepository(get_database_engine(request)))
        request.app.state.campaign_service = service
    return service


__all__ = [
    "_HistoryGuardedCharacterRepository",
    "get_campaign_service",
    "get_room_workspace_service",
]
