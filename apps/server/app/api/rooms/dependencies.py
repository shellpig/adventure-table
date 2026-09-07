from __future__ import annotations

from fastapi import Request

from app.api.dependencies import get_content_registry, get_database_engine
from app.domain.rooms.workspace import RoomCharacterWorkspaceService


def get_room_workspace_service(request: Request) -> RoomCharacterWorkspaceService:
    service = getattr(request.app.state, "room_workspace_service", None)
    if service is None:
        service = RoomCharacterWorkspaceService(
            get_database_engine(request),
            get_content_registry(request),
        )
        request.app.state.room_workspace_service = service
    return service


__all__ = ["get_room_workspace_service"]
