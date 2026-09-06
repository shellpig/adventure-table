from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.content.registry import ContentRegistry
from app.domain.character_builder.service import CharacterBuilderService
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.service import RoomService
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.main import app
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.repository import RoomRepository


class WebRoomTestClient(TestClient):
    """`app.main` client carrying one authenticated Room namespace."""

    def __init__(
        self,
        *,
        room_id: UUID,
        access_token: str,
        raise_server_exceptions: bool = True,
    ) -> None:
        super().__init__(
            app,
            headers={"Authorization": f"Bearer {access_token}"},
            raise_server_exceptions=raise_server_exceptions,
        )
        self.room_id = room_id
        self.access_token = access_token
        self.character_api = f"/api/rooms/{room_id}/characters"
        self.builder_api = f"/api/rooms/{room_id}/character-builder"


def _bind_services(
    engine: Engine,
    registry: ContentRegistry,
    *,
    character_repository: CharacterRepository | None = None,
    builder_service: CharacterBuilderService | None = None,
) -> tuple[CharacterRepository, RoomService, RoomCharacterWorkspaceService]:
    character_repository = character_repository or CharacterRepository(engine, registry)
    builder_service = builder_service or CharacterBuilderService(
        BuilderDraftRepository(engine),
        registry,
        character_repository,
    )
    room_service = RoomService(RoomRepository(engine))
    workspace = RoomCharacterWorkspaceService(engine, registry)

    app.state.content_registry = registry
    app.state.character_engine = engine
    app.state.character_repository = character_repository
    app.state.character_builder_service = builder_service
    app.state.room_service = room_service
    app.state.room_workspace_service = workspace
    return character_repository, room_service, workspace


def create_web_room_client(
    engine: Engine,
    registry: ContentRegistry,
    *,
    character_repository: CharacterRepository | None = None,
    builder_service: CharacterBuilderService | None = None,
    character_ids: Iterable[UUID] = (),
    raise_server_exceptions: bool = True,
    room_name: str = "Web regression room",
) -> WebRoomTestClient:
    """Bind `app.main`, create one Owner Room and scope pre-seeded Characters."""

    _, room_service, workspace = _bind_services(
        engine,
        registry,
        character_repository=character_repository,
        builder_service=builder_service,
    )
    grant = room_service.create_room(
        CreateRoomRequest(name=room_name, password="web-regression-password")
    )
    for character_id in character_ids:
        workspace.workspace_repository.attach_character(
            room_id=grant.room.id,
            character_id=character_id,
        )
    return WebRoomTestClient(
        room_id=grant.room.id,
        access_token=grant.access_token,
        raise_server_exceptions=raise_server_exceptions,
    )


def rebind_web_room_client(
    engine: Engine,
    registry: ContentRegistry,
    *,
    room_id: UUID,
    access_token: str,
    raise_server_exceptions: bool = True,
) -> WebRoomTestClient:
    """Rebuild Web services while preserving an existing Room and access session."""

    _bind_services(engine, registry)
    return WebRoomTestClient(
        room_id=room_id,
        access_token=access_token,
        raise_server_exceptions=raise_server_exceptions,
    )


__all__ = [
    "WebRoomTestClient",
    "create_web_room_client",
    "rebind_web_room_client",
]
