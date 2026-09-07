from __future__ import annotations

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.seats import ControllerKind, SeatControllerPatch, SeatCreate, SeatRole, SeatService
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionService
from app.persistence.characters import CharacterRepository, characters
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.tables import (
    active_character_session_leases,
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_access_sessions,
    room_characters,
    rooms,
    session_participants,
    sessions,
)
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


def test_room_hard_delete_removes_session_restrict_graph_before_owned_history() -> None:
    engine = _engine()
    try:
        registry = load_default_content_registry()
        room_repository = RoomRepository(engine)
        room_service = RoomService(room_repository)
        owner = room_service.create_room(
            CreateRoomRequest(name="Delete Session Room", password="secret")
        )

        build = build_p0_fighter_wizard_fixture()
        character_repository = CharacterRepository(engine, registry)
        character = character_repository.create_character(
            name="Mira",
            build=build,
            state=build_p0_fighter_wizard_state(build),
        )
        workspace = RoomWorkspaceRepository(engine)
        workspace.attach_character(
            room_id=owner.room.id,
            character_id=character.id,
        )

        campaigns_service = CampaignService(CampaignRepository(engine))
        campaign = campaigns_service.create_campaign(
            owner.room.id,
            CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
        )
        campaigns_service.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
        campaigns_service.select_campaign(owner.room.id, campaign.id)
        campaigns_service.add_character(
            owner.room.id,
            campaign.id,
            RosterAdd(character_id=character.id),
        )

        seat_service = SeatService(SeatRepository(engine))
        dm_seat = seat_service.create_seat(
            owner.room.id,
            campaign.id,
            SeatCreate(role=SeatRole.DM),
        )
        seat_service.set_controller(
            owner.room.id,
            campaign.id,
            dm_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=owner.access_session_id,
            ),
        )
        player_seat = seat_service.create_seat(
            owner.room.id,
            campaign.id,
            SeatCreate(role=SeatRole.PLAYER, label="Mira"),
        )
        seat_service.select_character(
            owner.room.id,
            campaign.id,
            player_seat.id,
            character.id,
        )

        session_repository = SessionRepository(engine)
        started = SessionService(session_repository).start_session(
            owner.room.id,
            campaign.id,
            room_service.authenticate(owner.room.id, owner.access_token),
        )
        assert started.participants
        assert session_repository.lease_for_character(character.id) is not None

        removed = workspace.hard_delete_room(owner.room.id)
        assert removed.characters == 1
        assert removed.drafts == 0

        for table in (
            active_character_session_leases,
            session_participants,
            sessions,
            campaign_roster_entries,
            campaign_seats,
            campaigns,
            room_characters,
            room_access_sessions,
            rooms,
            characters,
        ):
            assert _count(engine, table) == 0, table.name
    finally:
        engine.dispose()
