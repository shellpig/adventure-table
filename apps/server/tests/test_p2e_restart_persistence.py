from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.seats import ControllerKind, SeatControllerPatch, SeatCreate, SeatRole, SeatService
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionService, SessionStatus
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.workspace import RoomWorkspaceRepository


def _engine(database_path: Path):
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.resolve().as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _participant_truth(snapshot):
    return [
        (
            participant.id,
            participant.seat_id,
            participant.role,
            participant.controller_kind_at_join,
            participant.controller_access_session_id_at_join,
            participant.active_character_id,
        )
        for participant in snapshot.participants
    ]


def test_restart_preserves_active_session_controller_participants_leases_and_access(tmp_path: Path) -> None:
    database_path = tmp_path / "p2e-restart.sqlite3"

    engine1 = _engine(database_path)
    metadata.create_all(engine1)
    registry1 = load_default_content_registry()
    rooms1 = RoomService(RoomRepository(engine1))
    owner = rooms1.create_room(
        CreateRoomRequest(name="P2-E restart", password="secret", display_name="Owner")
    )
    dm = rooms1.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            elevated_key=owner.dm_key,
            display_name="Fixed DM",
        ),
        remote_addr="127.0.0.2",
    )

    build = build_p0_fighter_wizard_fixture()
    characters1 = CharacterRepository(engine1, registry1)
    mira = characters1.create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    RoomWorkspaceRepository(engine1).attach_character(
        room_id=owner.room.id,
        character_id=mira.id,
    )

    campaigns1 = CampaignService(CampaignRepository(engine1))
    campaign = campaigns1.create_campaign(
        owner.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns1.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns1.select_campaign(owner.room.id, campaign.id)
    campaigns1.add_character(
        owner.room.id,
        campaign.id,
        RosterAdd(character_id=mira.id),
    )

    seats1 = SeatService(SeatRepository(engine1))
    dm_seat = seats1.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.DM))
    seats1.set_controller(
        owner.room.id,
        campaign.id,
        dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )
    player_seat = seats1.create_seat(
        owner.room.id,
        campaign.id,
        SeatCreate(role=SeatRole.PLAYER, label="Mira"),
    )
    seats1.select_character(owner.room.id, campaign.id, player_seat.id, mira.id)

    sessions1 = SessionService(SessionRepository(engine1))
    started = sessions1.start_session(
        owner.room.id,
        campaign.id,
        rooms1.authenticate(owner.room.id, dm.access_token),
    )
    participant_truth = _participant_truth(started)
    fixed_dm_access_session_id = started.dm_controller_access_session_id
    assert fixed_dm_access_session_id == dm.access_session_id

    # Change the current Lobby DM Seat controller after Start. The Session must
    # continue to remember its original fixed current DM across restart.
    seats1.set_controller(
        owner.room.id,
        campaign.id,
        dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=owner.access_session_id,
        ),
    )
    engine1.dispose()

    # Simulate a server/process restart: construct a fresh Engine and all fresh
    # services from the persisted database, with no in-memory object reuse.
    engine2 = _engine(database_path)
    rooms2 = RoomService(RoomRepository(engine2))
    dm_context2 = rooms2.authenticate(owner.room.id, dm.access_token)
    assert dm_context2.access_session_id == dm.access_session_id

    repository2 = SessionRepository(engine2)
    sessions2 = SessionService(repository2)
    resumed = sessions2.resume(owner.room.id, campaign.id).active_session
    assert resumed is not None
    assert resumed.id == started.id
    assert resumed.status is SessionStatus.ACTIVE
    assert resumed.dm_controller_access_session_id == fixed_dm_access_session_id
    assert _participant_truth(resumed) == participant_truth

    lease = repository2.lease_for_character(mira.id)
    assert lease is not None
    assert lease.session_id == started.id
    mira_participant = next(
        participant for participant in resumed.participants if participant.active_character_id == mira.id
    )
    assert lease.participant_id == mira_participant.id

    current_dm_seat = SeatRepository(engine2).get(dm_seat.id)
    assert current_dm_seat is not None
    assert current_dm_seat.controller_access_session_id == owner.access_session_id

    # The original fixed DM token can still End after restart even though the
    # Lobby Seat now points elsewhere; End persists and releases the lease.
    ended = sessions2.end_session(
        owner.room.id,
        campaign.id,
        started.id,
        dm_context2,
    )
    assert ended.status is SessionStatus.ENDED
    assert repository2.lease_for_character(mira.id) is None

    archived_player = SeatService(SeatRepository(engine2)).archive_seat(
        owner.room.id,
        campaign.id,
        player_seat.id,
    )
    assert archived_player.archived_at is not None
    engine2.dispose()

    # A second restart must not reconstruct leases for ended history, and an
    # archived Seat remains a valid non-null historical Session reference.
    engine3 = _engine(database_path)
    rooms3 = RoomService(RoomRepository(engine3))
    assert rooms3.authenticate(owner.room.id, dm.access_token).access_session_id == dm.access_session_id

    repository3 = SessionRepository(engine3)
    sessions3 = SessionService(repository3)
    assert sessions3.resume(owner.room.id, campaign.id).active_session is None
    persisted = repository3.get(started.id)
    assert persisted is not None
    assert persisted.status == SessionStatus.ENDED.value
    assert persisted.dm_controller_access_session_id == fixed_dm_access_session_id
    assert repository3.lease_for_character(mira.id) is None

    participants_after_second_restart = repository3.list_participants(started.id)
    assert [
        (
            participant.id,
            participant.seat_id,
            participant.role_snapshot,
            participant.controller_kind_at_join,
            participant.controller_access_session_id_at_join,
            participant.active_character_id,
        )
        for participant in participants_after_second_restart
    ] == participant_truth

    historical_seat = SeatRepository(engine3).get(player_seat.id)
    assert historical_seat is not None
    assert historical_seat.archived_at is not None
    assert any(
        participant.seat_id == historical_seat.id
        for participant in participants_after_second_restart
    )
    engine3.dispose()
