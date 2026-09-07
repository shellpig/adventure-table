from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.campaigns import (
    CampaignCreate,
    CampaignService,
    CampaignStatus,
    RosterAdd,
    RosterStatus,
)
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.seats import ControllerKind, SeatControllerPatch, SeatCreate, SeatRole, SeatService
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import (
    DMControllerMismatchError,
    SessionActiveCharacterLockedError,
    SessionActiveCharacterPatch,
    SessionLateJoinError,
    SessionLateJoinRequest,
    SessionService,
)
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


def _setup(engine):
    registry = load_default_content_registry()
    rooms = RoomService(RoomRepository(engine))
    owner = rooms.create_room(CreateRoomRequest(name="Late Join", password="secret"))
    dm = rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            elevated_key=owner.dm_key,
        ),
        remote_addr="127.0.0.2",
    )
    build = build_p0_fighter_wizard_fixture()
    characters = CharacterRepository(engine, registry)
    workspace = RoomWorkspaceRepository(engine)
    mira = characters.create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    luna = characters.create_character(
        name="Luna",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    for character in (mira, luna):
        workspace.attach_character(room_id=owner.room.id, character_id=character.id)

    campaigns = CampaignService(CampaignRepository(engine))
    campaign = campaigns.create_campaign(
        owner.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(owner.room.id, campaign.id)
    for character in (mira, luna):
        campaigns.add_character(
            owner.room.id,
            campaign.id,
            RosterAdd(character_id=character.id),
        )

    seats = SeatService(SeatRepository(engine))
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
    mira_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
    seats.select_character(owner.room.id, campaign.id, mira_seat.id, mira.id)
    sessions = SessionService(SessionRepository(engine))
    started = sessions.start_session(
        owner.room.id,
        campaign.id,
        rooms.authenticate(owner.room.id, dm.access_token),
    )
    return rooms, owner, dm, campaigns, campaign, mira, luna, seats, sessions, started


def test_late_join_is_current_dm_only_and_snapshots_selected_character() -> None:
    engine = _engine()
    try:
        rooms, owner, dm, _campaigns, campaign, mira, luna, seats, sessions, started = _setup(engine)
        late_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
        seats.select_character(owner.room.id, campaign.id, late_seat.id, luna.id)
        owner_context = rooms.authenticate(owner.room.id, owner.access_token)
        dm_context = rooms.authenticate(owner.room.id, dm.access_token)

        with pytest.raises(DMControllerMismatchError):
            sessions.late_join(
                owner.room.id,
                campaign.id,
                started.id,
                SessionLateJoinRequest(seat_id=late_seat.id),
                owner_context,
            )

        joined = sessions.late_join(
            owner.room.id,
            campaign.id,
            started.id,
            SessionLateJoinRequest(seat_id=late_seat.id),
            dm_context,
        )
        participant = next(item for item in joined.participants if item.seat_id == late_seat.id)
        assert participant.active_character_id == luna.id
        lease = sessions.repository.lease_for_character(luna.id)
        assert lease is not None and lease.session_id == started.id

        with pytest.raises(SessionActiveCharacterLockedError):
            sessions.assert_active_character_locked(
                owner.room.id,
                campaign.id,
                started.id,
                participant.id,
                SessionActiveCharacterPatch(active_character_id=mira.id),
            )
    finally:
        engine.dispose()


def test_late_join_revalidates_roster_status_inside_transaction() -> None:
    engine = _engine()
    try:
        rooms, owner, dm, campaigns, campaign, _mira, luna, seats, sessions, started = _setup(engine)
        late_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
        seats.select_character(owner.room.id, campaign.id, late_seat.id, luna.id)
        campaigns.update_roster_status(
            owner.room.id,
            campaign.id,
            luna.id,
            RosterStatus.RETIRED,
        )

        with pytest.raises(SessionLateJoinError):
            sessions.late_join(
                owner.room.id,
                campaign.id,
                started.id,
                SessionLateJoinRequest(seat_id=late_seat.id),
                rooms.authenticate(owner.room.id, dm.access_token),
            )
        assert sessions.repository.lease_for_character(luna.id) is None
        current = sessions.get_session(owner.room.id, campaign.id, started.id)
        assert all(item.seat_id != late_seat.id for item in current.participants)
    finally:
        engine.dispose()
