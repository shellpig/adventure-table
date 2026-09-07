from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, update
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
    SessionAlreadyActiveError,
    SessionService,
    SessionStatus,
)
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.tables import room_access_sessions
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


def _setup_table(engine):
    registry = load_default_content_registry()
    rooms = RoomService(RoomRepository(engine))
    owner = rooms.create_room(
        CreateRoomRequest(name="P2-E lifecycle", password="secret", display_name="Owner")
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
    workspace = RoomWorkspaceRepository(engine)
    mira = characters.create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    serena = characters.create_character(
        name="Serena",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    for character in (mira, serena):
        workspace.attach_character(room_id=owner.room.id, character_id=character.id)

    campaigns = CampaignService(CampaignRepository(engine))
    campaign = campaigns.create_campaign(
        owner.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(owner.room.id, campaign.id)
    for character in (mira, serena):
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
    player = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
    seats.select_character(owner.room.id, campaign.id, player.id, mira.id)
    sessions = SessionService(SessionRepository(engine))
    return rooms, owner, dm, campaign, mira, serena, seats, dm_seat, sessions


def test_start_freezes_dm_and_selected_players_then_end_releases_lease() -> None:
    engine = _engine()
    try:
        rooms, owner, dm, campaign, mira, serena, seats, dm_seat, service = _setup_table(engine)
        owner_context = rooms.authenticate(owner.room.id, owner.access_token)
        dm_context = rooms.authenticate(owner.room.id, dm.access_token)

        with pytest.raises(DMControllerMismatchError):
            service.start_session(owner.room.id, campaign.id, owner_context)

        started = service.start_session(owner.room.id, campaign.id, dm_context)
        assert started.status is SessionStatus.ACTIVE
        assert started.dm_controller_access_session_id == dm.access_session_id
        player_characters = {
            item.active_character_id
            for item in started.participants
            if item.role == "player"
        }
        assert player_characters == {mira.id}
        assert serena.id not in player_characters
        assert service.repository.lease_for_character(mira.id).session_id == started.id

        with pytest.raises(SessionAlreadyActiveError):
            service.start_session(owner.room.id, campaign.id, dm_context)

        seats.set_controller(
            owner.room.id,
            campaign.id,
            dm_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=owner.access_session_id,
            ),
        )
        with pytest.raises(DMControllerMismatchError):
            service.end_session(owner.room.id, campaign.id, started.id, owner_context)

        ended = service.end_session(owner.room.id, campaign.id, started.id, dm_context)
        assert ended.status is SessionStatus.ENDED
        assert service.repository.lease_for_character(mira.id) is None
        assert service.resume(owner.room.id, campaign.id).active_session is None
    finally:
        engine.dispose()


def test_start_authority_matrix_offline_players_and_reopen_after_finalization() -> None:
    engine = _engine()
    try:
        rooms, owner, dm, campaign, mira, serena, seats, dm_seat, service = _setup_table(engine)
        other_dm = rooms.enter_room(
            EnterRoomRequest(
                code=owner.room.code,
                password="secret",
                elevated_key=owner.dm_key,
                display_name="Other DM",
            ),
            remote_addr="127.0.0.3",
        )
        member = rooms.enter_room(
            EnterRoomRequest(
                code=owner.room.code,
                password="secret",
                display_name="Offline Player",
            ),
            remote_addr="127.0.0.4",
        )
        owner_context = rooms.authenticate(owner.room.id, owner.access_token)
        dm_context = rooms.authenticate(owner.room.id, dm.access_token)
        other_dm_context = rooms.authenticate(owner.room.id, other_dm.access_token)
        member_context = rooms.authenticate(owner.room.id, member.access_token)

        with pytest.raises(DMControllerMismatchError):
            service.start_session(owner.room.id, campaign.id, owner_context)
        with pytest.raises(DMControllerMismatchError):
            service.start_session(owner.room.id, campaign.id, other_dm_context)
        with pytest.raises(DMControllerMismatchError):
            service.start_session(owner.room.id, campaign.id, member_context)

        player = next(
            seat
            for seat in seats.list_seats(owner.room.id, campaign.id)
            if seat.role == SeatRole.PLAYER and seat.selected_character_id == mira.id
        )
        seats.set_controller(
            owner.room.id,
            campaign.id,
            player.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=member.access_session_id,
            ),
        )
        empty_player = seats.create_seat(
            owner.room.id,
            campaign.id,
            SeatCreate(role=SeatRole.PLAYER, label="Empty player"),
        )
        with engine.begin() as connection:
            connection.execute(
                update(room_access_sessions)
                .where(room_access_sessions.c.id == member.access_session_id)
                .values(last_seen_at=datetime.now(timezone.utc) - timedelta(minutes=10))
            )

        first = service.start_session(owner.room.id, campaign.id, dm_context)
        player_participants = [item for item in first.participants if item.role == "player"]
        assert [item.active_character_id for item in player_participants] == [mira.id]
        assert player_participants[0].controller_access_session_id_at_join == member.access_session_id
        assert all(item.seat_id != empty_player.id for item in first.participants)
        assert all(item.active_character_id != serena.id for item in first.participants)

        with pytest.raises(DMControllerMismatchError):
            service.end_session(owner.room.id, campaign.id, first.id, other_dm_context)

        with engine.begin() as connection:
            connection.execute(
                update(room_access_sessions)
                .where(room_access_sessions.c.id == dm.access_session_id)
                .values(last_seen_at=datetime.now(timezone.utc) - timedelta(minutes=10))
            )
        assert service.get_session(owner.room.id, campaign.id, first.id).status is SessionStatus.ACTIVE
        assert service.end_session(
            owner.room.id,
            campaign.id,
            first.id,
            dm_context,
        ).status is SessionStatus.ENDED

        seats.set_controller(
            owner.room.id,
            campaign.id,
            dm_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=owner.access_session_id,
            ),
        )
        second = service.start_session(owner.room.id, campaign.id, owner_context)
        assert second.dm_controller_access_session_id == owner.access_session_id
        assert service.abandon_session(
            owner.room.id,
            campaign.id,
            second.id,
            owner_context,
        ).status is SessionStatus.ABANDONED

        seats.set_controller(
            owner.room.id,
            campaign.id,
            dm_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=dm.access_session_id,
            ),
        )
        third = service.start_session(owner.room.id, campaign.id, dm_context)
        assert third.status is SessionStatus.ACTIVE
        assert third.id not in {first.id, second.id}
        assert service.end_session(
            owner.room.id,
            campaign.id,
            third.id,
            dm_context,
        ).status is SessionStatus.ENDED
    finally:
        engine.dispose()


def test_active_character_snapshot_ignores_lobby_and_roster_changes() -> None:
    engine = _engine()
    try:
        rooms, owner, dm, campaign, mira, serena, seats, _dm_seat, service = _setup_table(engine)
        dm_context = rooms.authenticate(owner.room.id, dm.access_token)
        started = service.start_session(owner.room.id, campaign.id, dm_context)
        player = next(
            seat
            for seat in seats.list_seats(owner.room.id, campaign.id)
            if seat.role == SeatRole.PLAYER and seat.selected_character_id == mira.id
        )
        participant_before = next(
            item for item in started.participants if item.seat_id == player.id
        )
        assert participant_before.active_character_id == mira.id

        seats.select_character(owner.room.id, campaign.id, player.id, serena.id)
        CampaignService(CampaignRepository(engine)).update_roster_status(
            owner.room.id,
            campaign.id,
            mira.id,
            RosterStatus.RETIRED,
        )

        current = service.get_session(owner.room.id, campaign.id, started.id)
        participant_after = next(
            item for item in current.participants if item.seat_id == player.id
        )
        assert participant_after.active_character_id == mira.id
        assert service.repository.lease_for_character(mira.id).session_id == started.id
        assert service.repository.lease_for_character(serena.id) is None
    finally:
        engine.dispose()


def test_owner_can_abandon_without_becoming_replacement_dm() -> None:
    engine = _engine()
    try:
        rooms, owner, dm, campaign, mira, _serena, _seats, _dm_seat, service = _setup_table(engine)
        dm_context = rooms.authenticate(owner.room.id, dm.access_token)
        owner_context = rooms.authenticate(owner.room.id, owner.access_token)
        started = service.start_session(owner.room.id, campaign.id, dm_context)

        abandoned = service.abandon_session(
            owner.room.id,
            campaign.id,
            started.id,
            owner_context,
        )
        assert abandoned.status is SessionStatus.ABANDONED
        assert abandoned.dm_controller_access_session_id == dm.access_session_id
        assert service.repository.lease_for_character(mira.id) is None
    finally:
        engine.dispose()
