from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character_builder.service import CharacterBuilderService
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.service import RoomService
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.main import app
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.workspace import RoomWorkspaceRepository


def _seed():
    registry = load_default_content_registry()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    character_repository = CharacterRepository(engine, registry)
    builder_service = CharacterBuilderService(
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
    room_a = room_service.create_room(CreateRoomRequest(name="Room A", password="secret-a"))
    room_b = room_service.create_room(CreateRoomRequest(name="Room B", password="secret-b"))
    return TestClient(app), engine, character_repository, workspace, room_a, room_b


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_web_global_character_and_builder_mutation_routes_are_closed() -> None:
    client, engine, _, _, room_a, _ = _seed()
    try:
        assert client.get("/api/characters").status_code == 404
        assert client.post("/api/character-builder/drafts", json={"draft_payload": {}}).status_code == 404
        created = client.post(
            f"/api/rooms/{room_a.room.id}/character-builder/drafts",
            headers=_auth(room_a.access_token),
            json={"draft_payload": {"basic": {"name": "Room draft"}, "target_level": 1}},
        )
        assert created.status_code == 201, created.text
        listed = client.get(
            f"/api/rooms/{room_a.room.id}/character-builder/drafts",
            headers=_auth(room_a.access_token),
        )
        assert listed.status_code == 200
        assert [item["draft"]["id"] for item in listed.json()] == [created.json()["draft"]["id"]]
    finally:
        engine.dispose()


def test_room_a_cannot_use_room_b_character_or_draft_ids() -> None:
    client, engine, repository, workspace, room_a, room_b = _seed()
    try:
        build = build_p0_fighter_wizard_fixture()
        character = repository.create_character(
            name=P0_FIXTURE_NAME,
            build=build,
            state=build_p0_fighter_wizard_state(build),
        )
        workspace.workspace_repository.attach_character(
            room_id=room_b.room.id,
            character_id=character.id,
        )
        draft_response = client.post(
            f"/api/rooms/{room_b.room.id}/character-builder/drafts",
            headers=_auth(room_b.access_token),
            json={"draft_payload": {"basic": {"name": "Room B draft"}, "target_level": 1}},
        )
        assert draft_response.status_code == 201, draft_response.text
        draft_id = draft_response.json()["draft"]["id"]
        headers = _auth(room_a.access_token)
        room_a_id = room_a.room.id

        character_requests = [
            client.get(f"/api/rooms/{room_a_id}/characters/{character.id}", headers=headers),
            client.get(f"/api/rooms/{room_a_id}/characters/{character.id}/sheet", headers=headers),
            client.patch(
                f"/api/rooms/{room_a_id}/characters/{character.id}/state",
                headers=headers,
                json={"current_hp": 1},
            ),
            client.get(f"/api/rooms/{room_a_id}/characters/{character.id}/export", headers=headers),
            client.post(f"/api/rooms/{room_a_id}/characters/{character.id}/archive", headers=headers),
            client.post(f"/api/rooms/{room_a_id}/characters/{character.id}/unarchive", headers=headers),
            client.delete(f"/api/rooms/{room_a_id}/characters/{character.id}", headers=headers),
            client.get(f"/api/rooms/{room_a_id}/characters/{character.id}/versions", headers=headers),
            client.post(
                f"/api/rooms/{room_a_id}/character-builder/characters/{character.id}/drafts",
                headers=headers,
                json={"mode": "level_up"},
            ),
            client.get(
                f"/api/rooms/{room_a_id}/character-builder/characters/{character.id}/drafts",
                headers=headers,
            ),
        ]
        assert all(response.status_code == 404 for response in character_requests)

        draft_requests = [
            client.get(f"/api/rooms/{room_a_id}/character-builder/drafts/{draft_id}", headers=headers),
            client.patch(
                f"/api/rooms/{room_a_id}/character-builder/drafts/{draft_id}",
                headers=headers,
                json={"expected_revision": 1, "draft_payload": {"basic": {"name": "forged"}}},
            ),
            client.post(
                f"/api/rooms/{room_a_id}/character-builder/drafts/{draft_id}/validate",
                headers=headers,
            ),
            client.get(
                f"/api/rooms/{room_a_id}/character-builder/drafts/{draft_id}/review",
                headers=headers,
            ),
            client.post(
                f"/api/rooms/{room_a_id}/character-builder/drafts/{draft_id}/confirm",
                headers=headers,
            ),
            client.delete(
                f"/api/rooms/{room_a_id}/character-builder/drafts/{draft_id}",
                headers=headers,
            ),
        ]
        assert all(response.status_code == 404 for response in draft_requests)

        room_a_list = client.get(f"/api/rooms/{room_a_id}/characters", headers=headers)
        assert room_a_list.status_code == 200
        assert room_a_list.json() == []
    finally:
        engine.dispose()
