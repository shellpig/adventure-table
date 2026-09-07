from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.seats import (
    ControllerKind,
    PresenceStatus,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.domain.rooms.service import RoomService
from app.domain.rooms.session_resume import SessionResumeService
from app.domain.rooms.sessions import SessionService
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
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


def test_resume_composes_current_p2_truth_without_a_second_snapshot() -> None:
    engine = _engine()
    try:
        registry = load_default_content_registry()
        room_repository = RoomRepository(engine)
        rooms = RoomService(room_repository)
        owner = rooms.create_room(
            CreateRoomRequest(name="Resume Room", password="secret", display_name="Owner")
        )
        dm = rooms.enter_room(
            EnterRoomRequest(
                code=owner.room.code,
                password="secret",
                elevated_key=owner.dm_key,
                display_name="DM",
            ),
            remote_addr="127.0.0.2",
        )

        build = build_p0_fighter_wizard_fixture()
        characters = CharacterRepository(engine, registry)
        mira = characters.create_character(
            name="Mira",
            build=build,
            state=build_p0_fighter_wizard_state(build),
        )
        RoomWorkspaceRepository(engine).attach_character(
            room_id=owner.room.id,
            character_id=mira.id,
        )

        campaign_repository = CampaignRepository(engine)
        campaigns = CampaignService(campaign_repository)
        campaign = campaigns.create_campaign(
            owner.room.id,
            CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
        )
        campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
        campaigns.select_campaign(owner.room.id, campaign.id)
        campaigns.add_character(
            owner.room.id,
            campaign.id,
            RosterAdd(character_id=mira.id),
        )

        seat_repository = SeatRepository(engine)
        seats = SeatService(seat_repository)
        dm_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.DM))
        seats.set_controller(
            owner.room.id,
            campaign.id,
            dm_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=dm.access_session_id,
            ),
        )
        player = seats.create_seat(
            owner.room.id,
            campaign.id,
            SeatCreate(role=SeatRole.PLAYER, label="Mira Seat"),
        )
        seats.set_controller(
            owner.room.id,
            campaign.id,
            player.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=owner.access_session_id,
            ),
        )
        seats.select_character(owner.room.id, campaign.id, player.id, mira.id)

        session_service = SessionService(SessionRepository(engine))
        dm_context = rooms.authenticate(owner.room.id, dm.access_token)
        started = session_service.start_session(owner.room.id, campaign.id, dm_context)

        # Current Lobby Seat truth may change after Start. The participant-at-join
        # snapshot stays fixed, and Resume must still include an archived Seat so
        # that the participant's Seat reference has structured current truth.
        seats.set_controller(
            owner.room.id,
            campaign.id,
            player.id,
            SeatControllerPatch(controller_kind=ControllerKind.NONE),
        )
        archived_player = seats.archive_seat(owner.room.id, campaign.id, player.id)
        assert archived_player.archived_at is not None
        assert all(
            seat.id != player.id
            for seat in seats.list_seats(owner.room.id, campaign.id)
        )

        resume = SessionResumeService(
            session_service=session_service,
            room_repository=room_repository,
            campaign_service=campaigns,
            seat_service=seats,
            character_repository=characters,
        ).resume(owner.room.id, campaign.id)

        assert resume.room.id == owner.room.id
        assert resume.room.name == "Resume Room"
        assert resume.campaign.id == campaign.id
        assert resume.active_session is not None
        assert resume.active_session.id == started.id
        assert resume.participants == started.participants

        participant_by_seat = {participant.seat_id: participant for participant in resume.participants}
        assert participant_by_seat[player.id].controller_kind_at_join == "human"
        assert participant_by_seat[player.id].controller_access_session_id_at_join == owner.access_session_id
        assert participant_by_seat[player.id].active_character_id == mira.id

        seat_by_id = {seat.id: seat for seat in resume.seats}
        assert seat_by_id[dm_seat.id].presence is PresenceStatus.CONNECTED
        assert seat_by_id[player.id].archived_at is not None
        assert seat_by_id[player.id].controller_kind is ControllerKind.NONE
        assert seat_by_id[player.id].presence is PresenceStatus.NOT_APPLICABLE
        assert seat_by_id[player.id].selected_character_id is None

        assert len(resume.active_characters) == 1
        summary = resume.active_characters[0]
        assert summary.id == mira.id
        assert summary.name == "Mira"
        assert summary.level == mira.build.character_level
        assert summary.version_no == mira.version_no
        assert [(entry.class_ref, entry.level) for entry in summary.classes]
    finally:
        engine.dispose()


def test_resume_without_active_session_keeps_room_and_campaign_truth() -> None:
    engine = _engine()
    try:
        registry = load_default_content_registry()
        room_repository = RoomRepository(engine)
        rooms = RoomService(room_repository)
        owner = rooms.create_room(CreateRoomRequest(name="Empty Resume", password="secret"))
        campaigns = CampaignService(CampaignRepository(engine))
        campaign = campaigns.create_campaign(
            owner.room.id,
            CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
        )
        service = SessionResumeService(
            session_service=SessionService(SessionRepository(engine)),
            room_repository=room_repository,
            campaign_service=campaigns,
            seat_service=SeatService(SeatRepository(engine)),
            character_repository=CharacterRepository(engine, registry),
        )

        resume = service.resume(owner.room.id, campaign.id)
        assert resume.room.id == owner.room.id
        assert resume.campaign.id == campaign.id
        assert resume.active_session is None
        assert resume.participants == []
        assert resume.seats == []
        assert resume.active_characters == []
    finally:
        engine.dispose()
