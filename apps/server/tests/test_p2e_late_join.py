from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, insert, update
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
    CharacterAlreadyInActiveSessionError,
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
from app.persistence.rooms.sessions import ParticipantSeed, SessionRepository
from app.persistence.rooms.tables import campaign_roster_entries, campaign_seats
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
        other_dm = rooms.enter_room(
            EnterRoomRequest(
                code=owner.room.code,
                password="secret",
                elevated_key=owner.dm_key,
                display_name="Other DM",
            ),
            remote_addr="127.0.0.3",
        )
        other_dm_context = rooms.authenticate(owner.room.id, other_dm.access_token)

        with pytest.raises(DMControllerMismatchError):
            sessions.late_join(
                owner.room.id,
                campaign.id,
                started.id,
                SessionLateJoinRequest(seat_id=late_seat.id),
                owner_context,
            )
        with pytest.raises(DMControllerMismatchError):
            sessions.late_join(
                owner.room.id,
                campaign.id,
                started.id,
                SessionLateJoinRequest(seat_id=late_seat.id),
                other_dm_context,
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


@pytest.mark.parametrize("roster_status", [RosterStatus.RETIRED, RosterStatus.DEAD])
def test_late_join_revalidates_terminal_roster_status_inside_transaction(roster_status: RosterStatus) -> None:
    engine = _engine()
    try:
        rooms, owner, dm, campaigns, campaign, _mira, luna, seats, sessions, started = _setup(engine)
        late_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
        seats.select_character(owner.room.id, campaign.id, late_seat.id, luna.id)
        campaigns.update_roster_status(
            owner.room.id,
            campaign.id,
            luna.id,
            roster_status,
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


def test_late_join_revalidates_archived_character_inside_transaction() -> None:
    engine = _engine()
    try:
        rooms, owner, dm, _campaigns, campaign, _mira, luna, seats, sessions, started = _setup(engine)
        late_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
        seats.select_character(owner.room.id, campaign.id, late_seat.id, luna.id)
        CharacterRepository(engine, load_default_content_registry()).set_archived(luna.id, True)

        with pytest.raises(SessionLateJoinError):
            sessions.late_join(
                owner.room.id,
                campaign.id,
                started.id,
                SessionLateJoinRequest(seat_id=late_seat.id),
                rooms.authenticate(owner.room.id, dm.access_token),
            )
        assert sessions.repository.lease_for_character(luna.id) is None
    finally:
        engine.dispose()


def test_late_join_revalidates_same_room_even_if_persistence_is_tampered() -> None:
    engine = _engine()
    try:
        rooms, owner, dm, _campaigns, campaign, _mira, luna, seats, sessions, started = _setup(engine)
        late_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
        seats.select_character(owner.room.id, campaign.id, late_seat.id, luna.id)

        other_room = rooms.create_room(CreateRoomRequest(name="Other Room", password="secret"))
        registry = load_default_content_registry()
        build = build_p0_fighter_wizard_fixture()
        foreign = CharacterRepository(engine, registry).create_character(
            name="Foreign",
            build=build,
            state=build_p0_fighter_wizard_state(build),
        )
        RoomWorkspaceRepository(engine).attach_character(
            room_id=other_room.room.id,
            character_id=foreign.id,
        )
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(
                insert(campaign_roster_entries).values(
                    campaign_id=campaign.id,
                    character_id=foreign.id,
                    status="active",
                    added_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == late_seat.id)
                .values(selected_character_id=foreign.id, updated_at=now)
            )

        with pytest.raises(SessionLateJoinError):
            sessions.late_join(
                owner.room.id,
                campaign.id,
                started.id,
                SessionLateJoinRequest(seat_id=late_seat.id),
                rooms.authenticate(owner.room.id, dm.access_token),
            )
        assert sessions.repository.lease_for_character(foreign.id) is None
        assert all(
            item.active_character_id != foreign.id
            for item in sessions.get_session(owner.room.id, campaign.id, started.id).participants
        )
    finally:
        engine.dispose()


def test_late_join_maps_existing_global_lease_without_partial_participant() -> None:
    engine = _engine()
    try:
        rooms, owner, dm, campaigns, campaign, _mira, luna, seats, sessions, started = _setup(engine)
        late_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
        seats.select_character(owner.room.id, campaign.id, late_seat.id, luna.id)

        other_campaign = campaigns.create_campaign(
            owner.room.id,
            CampaignCreate(name="Other Campaign", ruleset="dnd5e-2014"),
        )
        campaigns.set_status(owner.room.id, other_campaign.id, CampaignStatus.ACTIVE)
        campaigns.add_character(
            owner.room.id,
            other_campaign.id,
            RosterAdd(character_id=luna.id),
        )
        seat_repository = SeatRepository(engine)
        other_dm_seat = seat_repository.create(
            campaign_id=other_campaign.id,
            role="dm",
            label="Other DM",
        )
        seat_repository.set_controller(
            seat_id=other_dm_seat.id,
            controller_kind="human",
            controller_access_session_id=dm.access_session_id,
        )
        other_player = seat_repository.create(
            campaign_id=other_campaign.id,
            role="player",
            label="Other Luna",
        )
        selected = seat_repository.select_character_if_eligible(
            seat_id=other_player.id,
            campaign_id=other_campaign.id,
            character_id=luna.id,
        )
        assert selected is not None and selected.selected_character_id == luna.id

        other_session = SessionRepository(engine).create_with_participants(
            campaign_id=other_campaign.id,
            dm_seat_id=other_dm_seat.id,
            dm_controller_kind="human",
            dm_controller_access_session_id=dm.access_session_id,
            participants=(
                ParticipantSeed(
                    seat_id=other_dm_seat.id,
                    role_snapshot="dm",
                    controller_kind_at_join="human",
                    controller_access_session_id_at_join=dm.access_session_id,
                    active_character_id=None,
                ),
                ParticipantSeed(
                    seat_id=other_player.id,
                    role_snapshot="player",
                    controller_kind_at_join="none",
                    controller_access_session_id_at_join=None,
                    active_character_id=luna.id,
                ),
            ),
        )

        with pytest.raises(CharacterAlreadyInActiveSessionError):
            sessions.late_join(
                owner.room.id,
                campaign.id,
                started.id,
                SessionLateJoinRequest(seat_id=late_seat.id),
                rooms.authenticate(owner.room.id, dm.access_token),
            )

        lease = sessions.repository.lease_for_character(luna.id)
        assert lease is not None and lease.session_id == other_session.id
        assert all(
            item.seat_id != late_seat.id
            for item in sessions.get_session(owner.room.id, campaign.id, started.id).participants
        )
    finally:
        engine.dispose()
