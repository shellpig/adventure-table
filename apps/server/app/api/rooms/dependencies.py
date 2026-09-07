from __future__ import annotations

from typing import Any

from fastapi import Request

from app.api.dependencies import get_content_registry, get_database_engine
from app.api.errors import APIError
from app.domain.rooms.campaigns import CampaignService
from app.domain.rooms.seats import SeatService
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.sessions import SessionRepository


class _HistoryGuardedCharacterRepository:
    """Web-only adapter that keeps multiplayer history out of Character Core."""

    def __init__(
        self,
        delegate: Any,
        campaigns: CampaignRepository,
        sessions: SessionLiveRepository,
    ) -> None:
        self._delegate = delegate
        self._campaigns = campaigns
        self._sessions = sessions

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def delete_character(self, character_id) -> None:
        if self._campaigns.character_is_referenced(character_id) or self._sessions.character_is_history_referenced(
            character_id
        ):
            raise APIError(
                409,
                "character_history_referenced",
                "Character is referenced by Campaign or Session history and cannot be permanently deleted",
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
            SessionLiveRepository(engine),
        )
        request.app.state.room_workspace_service = service
    return service


def get_campaign_service(request: Request) -> CampaignService:
    service = getattr(request.app.state, "campaign_service", None)
    if service is None:
        service = CampaignService(CampaignRepository(get_database_engine(request)))
        request.app.state.campaign_service = service
    return service


def get_seat_service(request: Request) -> SeatService:
    service = getattr(request.app.state, "seat_service", None)
    if service is None:
        service = SeatService(SeatRepository(get_database_engine(request)))
        request.app.state.seat_service = service
    return service


def get_session_service(request: Request) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if service is None:
        engine = get_database_engine(request)
        service = SessionService(
            SessionRepository(engine),
            SessionLiveRepository(engine),
        )
        request.app.state.session_service = service
    return service


__all__ = [
    "_HistoryGuardedCharacterRepository",
    "get_campaign_service",
    "get_room_workspace_service",
    "get_seat_service",
    "get_session_service",
]
