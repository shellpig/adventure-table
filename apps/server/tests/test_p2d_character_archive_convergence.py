from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character_builder.service import CharacterBuilderService
from app.domain.rooms.campaigns import (
    CampaignCreate,
    CampaignService,
    CampaignStatus,
    RosterAdd,
)
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.service import RoomService
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.main import app
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository


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


def test_room_character_archive_clears_selected_seat_in_same_room_write_path() -> None:
    engine = _engine()
    registry = load_default_content_registry()
    character_repository = CharacterRepository(engine, registry)
    builder_service = CharacterBuilderService(
        BuilderDraftRepository(engine),
        registry,
        character_repository,
    )
    room_service = RoomService(RoomRepository(engine))
    workspace = RoomCharacterWorkspaceService(engine, registry)
    campaign_service = CampaignService(CampaignRepository(engine))
    seats = SeatRepository(engine)

    app.state.content_registry = registry
    app.state.character_engine = engine
    app.state.character_repository = character_repository
    app.state.character_builder_service = builder_service
    app.state.room_service = room_service
    app.state.room_workspace_service = workspace

    room = room_service.create_room(CreateRoomRequest(name="Room A", password="secret-a"))
    build = build_p0_fighter_wizard_fixture()
    character = character_repository.create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    workspace.workspace_repository.attach_character(
        room_id=room.room.id,
        character_id=character.id,
    )
    campaign = campaign_service.create_campaign(
        room.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaign_service.set_status(room.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaign_service.select_campaign(room.room.id, campaign.id)
    campaign_service.add_character(
        room.room.id,
        campaign.id,
        RosterAdd(character_id=character.id),
    )
    seat = seats.create(campaign_id=campaign.id, role="player", label="Player")
    selected = seats.select_character_if_eligible(
        seat_id=seat.id,
        campaign_id=campaign.id,
        character_id=character.id,
    )
    assert selected is not None
    assert selected.selected_character_id == character.id

    client = TestClient(app)
    try:
        response = client.post(
            f"/api/rooms/{room.room.id}/characters/{character.id}/archive",
            headers={"Authorization": f"Bearer {room.access_token}"},
        )
        assert response.status_code == 200, response.text
        assert character_repository.load_character(character.id).archived_at is not None
        assert seats.get(seat.id).selected_character_id is None

        unarchive = client.post(
            f"/api/rooms/{room.room.id}/characters/{character.id}/unarchive",
            headers={"Authorization": f"Bearer {room.access_token}"},
        )
        assert unarchive.status_code == 200, unarchive.text
        assert character_repository.load_character(character.id).archived_at is None
        assert seats.get(seat.id).selected_character_id is None
    finally:
        engine.dispose()
