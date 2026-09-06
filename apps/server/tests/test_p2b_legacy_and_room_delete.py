from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character_builder.schemas import BuilderDraftCreateInput, BuilderDraftPayload
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.service import RoomService
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.main import app
from app.persistence.builder_drafts import BuilderDraftRepository, character_build_drafts
from app.persistence.character_imports import character_import_records
from app.persistence.characters import CharacterRepository, characters
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.tables import room_builder_drafts, room_characters, rooms
from app.persistence.rooms.workspace import RoomWorkspaceRepository


def _engine():
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
    return engine


def _count(engine, table) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(table)) or 0)


def _legacy_core_rows(engine, registry):
    repository = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    character = repository.create_character(
        name=P0_FIXTURE_NAME,
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    draft = BuilderDraftRepository(engine).create_draft(
        BuilderDraftCreateInput(
            draft_payload=BuilderDraftPayload(
                basic={"name": "Legacy draft"},
                target_level=1,
            )
        )
    )
    return character, draft


def test_first_room_bootstrap_claims_existing_unscoped_character_data_atomically() -> None:
    engine = _engine()
    registry = load_default_content_registry()
    character, draft = _legacy_core_rows(engine, registry)
    workspace = RoomWorkspaceRepository(engine)
    room_service = RoomService(
        RoomRepository(engine),
        first_room_bootstrap=workspace.claim_all_unscoped_in_transaction,
    )
    try:
        grant = room_service.create_room(CreateRoomRequest(name="First Room", password="secret1"))
        assert workspace.character_room_id(character.id) == grant.room.id
        assert workspace.draft_room_id(draft.id) == grant.room.id
        assert workspace.legacy_counts().characters == 0
        assert workspace.legacy_counts().drafts == 0
    finally:
        engine.dispose()


def test_owner_claim_card_exposes_counts_only_and_claim_is_idempotent() -> None:
    engine = _engine()
    registry = load_default_content_registry()
    workspace = RoomWorkspaceRepository(engine)
    room_service = RoomService(RoomRepository(engine))
    grant = room_service.create_room(CreateRoomRequest(name="Existing Room", password="secret2"))
    character, draft = _legacy_core_rows(engine, registry)
    member = room_service.enter_room(
        EnterRoomRequest(code=grant.room.code, password="secret2"),
        remote_addr="member-test",
    )
    room_workspace = RoomCharacterWorkspaceService(engine, registry, workspace_repository=workspace)
    app.state.content_registry = registry
    app.state.character_engine = engine
    app.state.room_service = room_service
    app.state.room_workspace_service = room_workspace
    client = TestClient(app)
    owner_headers = {"Authorization": f"Bearer {grant.access_token}"}
    member_headers = {"Authorization": f"Bearer {member.access_token}"}
    try:
        denied = client.get(
            f"/api/rooms/{grant.room.id}/characters/legacy",
            headers=member_headers,
        )
        assert denied.status_code == 403

        status = client.get(
            f"/api/rooms/{grant.room.id}/characters/legacy",
            headers=owner_headers,
        )
        assert status.status_code == 200
        assert status.json() == {
            "character_count": 1,
            "draft_count": 1,
            "available": True,
        }
        assert str(character.id) not in status.text
        assert str(draft.id) not in status.text

        claimed = client.post(
            f"/api/rooms/{grant.room.id}/characters/legacy/claim",
            headers=owner_headers,
        )
        assert claimed.status_code == 200
        assert claimed.json() == {
            "claimed_character_count": 1,
            "claimed_draft_count": 1,
        }
        assert workspace.character_room_id(character.id) == grant.room.id
        assert workspace.draft_room_id(draft.id) == grant.room.id

        repeated = client.post(
            f"/api/rooms/{grant.room.id}/characters/legacy/claim",
            headers=owner_headers,
        )
        assert repeated.json() == {
            "claimed_character_count": 0,
            "claimed_draft_count": 0,
        }
    finally:
        engine.dispose()


def test_room_hard_delete_removes_only_that_workspace_core_and_import_rows() -> None:
    engine = _engine()
    registry = load_default_content_registry()
    room_service = RoomService(RoomRepository(engine))
    room_a = room_service.create_room(CreateRoomRequest(name="Delete Me", password="secret3"))
    room_b = room_service.create_room(CreateRoomRequest(name="Keep Me", password="secret4"))
    workspace = RoomCharacterWorkspaceService(engine, registry)
    try:
        build = build_p0_fighter_wizard_fixture()
        state = build_p0_fighter_wizard_state(build)
        char_a = workspace.character_repository.create_character(name="A", build=build, state=state)
        char_b = workspace.character_repository.create_character(name="B", build=build, state=state)
        workspace.workspace_repository.attach_character(room_id=room_a.room.id, character_id=char_a.id)
        workspace.workspace_repository.attach_character(room_id=room_b.room.id, character_id=char_b.id)
        draft_a = workspace.create_draft(
            room_a.room.id,
            BuilderDraftCreateInput(draft_payload=BuilderDraftPayload(basic={"name": "A draft"}, target_level=1)),
        ).draft
        with engine.begin() as connection:
            connection.execute(
                insert(character_import_records).values(
                    id=uuid4(),
                    character_id=char_a.id,
                    draft_id=None,
                    source_character_id=uuid4(),
                    source_export_id=uuid4(),
                    landing_mode="character",
                )
            )
            connection.execute(
                insert(character_import_records).values(
                    id=uuid4(),
                    character_id=None,
                    draft_id=draft_a.id,
                    source_character_id=uuid4(),
                    source_export_id=uuid4(),
                    landing_mode="draft",
                )
            )

        removed = workspace.workspace_repository.hard_delete_room(room_a.room.id)
        assert removed.characters == 1
        assert removed.drafts == 1
        assert _count(engine, character_import_records) == 0
        assert _count(engine, room_characters) == 1
        assert _count(engine, room_builder_drafts) == 0
        assert _count(engine, characters) == 1
        assert workspace.character_repository.load_character(char_b.id).name == "B"
        with engine.connect() as connection:
            remaining_rooms = set(connection.scalars(select(rooms.c.id)).all())
        assert remaining_rooms == {room_b.room.id}
    finally:
        engine.dispose()
