from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.seats import SeatCreate, SeatHistoryReferencedError, SeatRole, SeatService
from app.domain.rooms.service import RoomService
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import (
    CharacterAlreadyLeasedPersistenceError,
    ParticipantSeed,
    SessionRepository,
)
from app.persistence.rooms.tables import (
    active_character_session_leases,
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


def _seed(engine):
    registry = load_default_content_registry()
    room = RoomService(RoomRepository(engine)).create_room(
        CreateRoomRequest(name="P2-E Room", password="secret")
    )
    build = build_p0_fighter_wizard_fixture()
    character = CharacterRepository(engine, registry).create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    RoomWorkspaceRepository(engine).attach_character(
        room_id=room.room.id,
        character_id=character.id,
    )
    campaigns = CampaignService(CampaignRepository(engine))
    campaign = campaigns.create_campaign(
        room.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns.set_status(room.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(room.room.id, campaign.id)
    campaigns.add_character(
        room.room.id,
        campaign.id,
        RosterAdd(character_id=character.id),
    )
    seats = SeatService(SeatRepository(engine))
    dm_seat = seats.create_seat(room.room.id, campaign.id, SeatCreate(role=SeatRole.DM))
    player_a = seats.create_seat(room.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
    player_b = seats.create_seat(room.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
    return room, campaign, character, seats, dm_seat, player_a, player_b


def _player_seed(seat_id, character_id) -> ParticipantSeed:
    return ParticipantSeed(
        seat_id=seat_id,
        role_snapshot="player",
        controller_kind_at_join="none",
        controller_access_session_id_at_join=None,
        active_character_id=character_id,
    )


def test_lease_collision_rolls_back_the_entire_second_session() -> None:
    engine = _engine()
    try:
        _room, campaign, character, _seats, dm_seat, player_a, player_b = _seed(engine)
        repository = SessionRepository(engine)
        first = repository.create_with_participants(
            campaign_id=campaign.id,
            dm_seat_id=dm_seat.id,
            dm_controller_kind="none",
            dm_controller_access_session_id=None,
            participants=[_player_seed(player_a.id, character.id)],
        )

        with pytest.raises(CharacterAlreadyLeasedPersistenceError):
            repository.create_with_participants(
                campaign_id=campaign.id,
                dm_seat_id=dm_seat.id,
                dm_controller_kind="none",
                dm_controller_access_session_id=None,
                participants=[_player_seed(player_b.id, character.id)],
            )

        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(sessions)) == 1
            assert connection.scalar(select(func.count()).select_from(session_participants)) == 1
            assert connection.scalar(select(func.count()).select_from(active_character_session_leases)) == 1
        lease = repository.lease_for_character(character.id)
        assert lease is not None
        assert lease.session_id == first.id
    finally:
        engine.dispose()


def test_session_referenced_seat_cannot_hard_delete_but_can_archive() -> None:
    engine = _engine()
    try:
        room, campaign, character, seats, dm_seat, player_a, _player_b = _seed(engine)
        session = SessionRepository(engine).create_with_participants(
            campaign_id=campaign.id,
            dm_seat_id=dm_seat.id,
            dm_controller_kind="none",
            dm_controller_access_session_id=None,
            participants=[_player_seed(player_a.id, character.id)],
        )

        with pytest.raises(SeatHistoryReferencedError):
            seats.delete_seat(room.room.id, campaign.id, player_a.id)

        archived = seats.archive_seat(room.room.id, campaign.id, player_a.id)
        assert archived.archived_at is not None
        participant = SessionRepository(engine).list_participants(session.id)[0]
        assert participant.seat_id == player_a.id
        assert SeatRepository(engine).get(player_a.id) is not None
    finally:
        engine.dispose()
