"""An active Session stays readable and finishable after the Room switches Campaign.

The Lobby is deliberately restricted to the Room's current active Campaign, but a
Session that is already running is not. Resume therefore has to carry the caller
identity the Lobby would otherwise have supplied, so the Session surface can tell
whether the caller is this Session's DM Controller without the Lobby succeeding.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.seats import (
    ControllerKind,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.domain.rooms.service import RoomService
from app.domain.rooms.session_resume import SessionResumeService
from app.domain.rooms.sessions import SessionService, SessionStatus
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


def test_active_session_survives_the_room_switching_active_campaign() -> None:
    engine = _engine()
    try:
        registry = load_default_content_registry()
        room_repository = RoomRepository(engine)
        rooms = RoomService(room_repository)
        owner = rooms.create_room(
            CreateRoomRequest(name="Switch Room", password="secret", display_name="Owner")
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

        campaigns = CampaignService(CampaignRepository(engine))
        running = campaigns.create_campaign(
            owner.room.id,
            CampaignCreate(name="Running Campaign", ruleset="dnd5e-2014"),
        )
        other = campaigns.create_campaign(
            owner.room.id,
            CampaignCreate(name="Other Campaign", ruleset="dnd5e-2014"),
        )
        for campaign in (running, other):
            campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
        campaigns.select_campaign(owner.room.id, running.id)
        campaigns.add_character(
            owner.room.id,
            running.id,
            RosterAdd(character_id=mira.id),
        )

        seats = SeatService(SeatRepository(engine))
        dm_seat = seats.create_seat(owner.room.id, running.id, SeatCreate(role=SeatRole.DM))
        seats.set_controller(
            owner.room.id,
            running.id,
            dm_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=dm.access_session_id,
            ),
        )
        player = seats.create_seat(
            owner.room.id,
            running.id,
            SeatCreate(role=SeatRole.PLAYER, label="Mira Seat"),
        )
        seats.select_character(owner.room.id, running.id, player.id, mira.id)

        session_service = SessionService(SessionRepository(engine))
        dm_context = rooms.authenticate(owner.room.id, dm.access_token)
        started = session_service.start_session(owner.room.id, running.id, dm_context)

        # The Owner moves the Room to a different Campaign while the Session runs.
        campaigns.select_campaign(owner.room.id, other.id)

        # The Lobby is gone, by contract.
        with pytest.raises(Exception):
            seats.lobby(
                owner.room.id,
                running.id,
                caller_access_session_id=dm.access_session_id,
            )

        # The Session itself is not.
        assert session_service.get_session(
            owner.room.id,
            running.id,
            started.id,
        ).status is SessionStatus.ACTIVE

        resume_service = SessionResumeService(
            session_service=session_service,
            room_repository=room_repository,
            campaign_service=campaigns,
            seat_service=seats,
            character_repository=characters,
        )
        resume = resume_service.resume(
            owner.room.id,
            running.id,
            caller_access_session_id=dm.access_session_id,
        )
        assert resume.active_session is not None
        assert resume.active_session.id == started.id
        assert resume.caller_access_session_id == dm.access_session_id
        assert resume.active_session.dm_controller_access_session_id == dm.access_session_id
        assert [participant.seat_id for participant in resume.participants]
        assert [summary.id for summary in resume.active_characters] == [mira.id]

        # Which is what the Session page needs to keep offering End to the DM.
        ended = session_service.end_session(
            owner.room.id,
            running.id,
            started.id,
            dm_context,
        )
        assert ended.status is SessionStatus.ENDED
    finally:
        engine.dispose()


def test_resume_reports_the_caller_even_without_an_active_session() -> None:
    engine = _engine()
    try:
        room_repository = RoomRepository(engine)
        rooms = RoomService(room_repository)
        owner = rooms.create_room(
            CreateRoomRequest(name="Quiet Room", password="secret", display_name="Owner")
        )
        campaigns = CampaignService(CampaignRepository(engine))
        campaign = campaigns.create_campaign(
            owner.room.id,
            CampaignCreate(name="Quiet Campaign", ruleset="dnd5e-2014"),
        )

        resume = SessionResumeService(
            session_service=SessionService(SessionRepository(engine)),
            room_repository=room_repository,
            campaign_service=campaigns,
            seat_service=SeatService(SeatRepository(engine)),
            character_repository=CharacterRepository(engine, load_default_content_registry()),
        ).resume(
            owner.room.id,
            campaign.id,
            caller_access_session_id=owner.access_session_id,
        )

        assert resume.active_session is None
        assert resume.caller_access_session_id == owner.access_session_id
    finally:
        engine.dispose()
