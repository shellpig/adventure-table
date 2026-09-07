from __future__ import annotations

from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.service import RoomService
from app.main import app
from app.persistence.builder_drafts import character_build_drafts
from app.persistence.characters import (
    CharacterRepository,
    character_states,
    character_versions,
    characters,
)
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.tables import (
    room_access_sessions,
    room_builder_drafts,
    room_characters,
    rooms,
)
from app.persistence.rooms.workspace import RoomWorkspaceAssociationConflictError
from web_room_support import create_web_room_client


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    return engine


def _count(engine, table) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(table)) or 0)


def test_first_room_bootstrap_conflict_retries_the_whole_room_transaction() -> None:
    engine = _engine()
    calls = 0

    def bootstrap(_connection, _room_id) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RoomWorkspaceAssociationConflictError("concurrent legacy claim")

    service = RoomService(
        RoomRepository(engine),
        first_room_bootstrap=bootstrap,
    )
    grant = service.create_room(
        CreateRoomRequest(name="Bootstrap retry", password="bootstrap-password")
    )

    assert calls == 2
    assert service.repository.count_rooms() == 1
    assert service.repository.get_room(grant.room.id) is not None
    assert _count(engine, room_access_sessions) == 1
    engine.dispose()


def test_legacy_claim_race_is_a_stable_conflict_not_a_500(monkeypatch) -> None:
    engine = _engine()
    registry = load_default_content_registry()
    client = create_web_room_client(engine, registry)

    def conflict(_room_id):
        raise RoomWorkspaceAssociationConflictError("claimed by another request")

    monkeypatch.setattr(
        app.state.room_workspace_service.workspace_repository,
        "claim_all_unscoped",
        conflict,
    )
    response = client.post(f"{client.character_api}/legacy/claim")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "room_workspace_conflict"
    engine.dispose()


def test_room_hard_delete_leaves_no_character_workspace_or_access_orphans() -> None:
    engine = _engine()
    registry = load_default_content_registry()
    repository = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    character = repository.create_character(
        name="Hard Delete Hero",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    client = create_web_room_client(
        engine,
        registry,
        character_repository=repository,
        character_ids=(character.id,),
    )
    created_draft = client.post(
        f"{client.builder_api}/drafts",
        json={"draft_payload": {"basic": {"name": "Delete Draft"}}},
    )
    assert created_draft.status_code == 201
    assert _count(engine, room_characters) == 1
    assert _count(engine, room_builder_drafts) == 1
    assert _count(engine, room_access_sessions) == 1

    response = client.delete(f"/api/rooms/{client.room_id}")
    assert response.status_code == 204

    for table in (
        room_characters,
        room_builder_drafts,
        room_access_sessions,
        rooms,
        character_build_drafts,
        character_states,
        character_versions,
        characters,
    ):
        assert _count(engine, table) == 0, table.name
    engine.dispose()
