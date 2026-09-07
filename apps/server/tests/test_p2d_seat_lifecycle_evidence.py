from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine, event, insert, update
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.seats import (
    ControllerKind,
    PresenceStatus,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.domain.rooms.service import RoomService
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
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


def _seed_active_campaign(engine):
    registry = load_default_content_registry()
    room = RoomService(RoomRepository(engine)).create_room(
        CreateRoomRequest(name="Room", password="secret")
    )
    characters = CharacterRepository(engine, registry)
    workspace = RoomWorkspaceRepository(engine)
    campaigns = CampaignService(CampaignRepository(engine))
    build = build_p0_fighter_wizard_fixture()
    character = characters.create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    workspace.attach_character(room_id=room.room.id, character_id=character.id)
    campaign = campaigns.create_campaign(
        room.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns.set_status(room.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(room.room.id, campaign.id)
    campaigns.add_character(room.room.id, campaign.id, RosterAdd(character_id=character.id))
    return room, campaign, character


def _insert_access(engine, room_id, *, authority="member", seen_seconds_ago=0):
    access_id = uuid4()
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            insert(room_access_sessions).values(
                id=access_id,
                room_id=room_id,
                authority=authority,
                token_hash=access_id.bytes + access_id.bytes,
                display_name=f"{authority}-{str(access_id)[:8]}",
                created_at=now,
                last_seen_at=now - timedelta(seconds=seen_seconds_ago),
                revoked_at=None,
            )
        )
    return access_id


def test_unreferenced_seat_delete_and_archive_release_character_for_another_seat() -> None:
    engine = _engine()
    try:
        room, campaign, character = _seed_active_campaign(engine)
        repository = SeatRepository(engine)
        service = SeatService(repository)

        first = service.create_seat(room.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
        second = service.create_seat(room.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
        disposable = service.create_seat(room.room.id, campaign.id, SeatCreate(role=SeatRole.SPECTATOR))
        service.select_character(room.room.id, campaign.id, first.id, character.id)

        archived = service.archive_seat(room.room.id, campaign.id, first.id)
        assert archived.archived_at is not None
        assert archived.selected_character_id is None
        assert {seat.id for seat in service.list_seats(room.room.id, campaign.id)} == {
            second.id,
            disposable.id,
        }

        rebound = service.select_character(room.room.id, campaign.id, second.id, character.id)
        assert rebound.selected_character_id == character.id

        service.delete_seat(room.room.id, campaign.id, disposable.id)
        assert repository.get(disposable.id) is None
    finally:
        engine.dispose()


def test_offline_controller_keeps_seat_binding_and_reconnect_restores_connected_presence() -> None:
    engine = _engine()
    try:
        room, campaign, _character = _seed_active_campaign(engine)
        repository = SeatRepository(engine)
        service = SeatService(repository)
        access_id = _insert_access(engine, room.room.id, seen_seconds_ago=91)
        seat = service.create_seat(room.room.id, campaign.id, SeatCreate(role=SeatRole.PLAYER))
        service.set_controller(
            room.room.id,
            campaign.id,
            seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=access_id,
            ),
        )

        offline = service.lobby(room.room.id, campaign.id)
        offline_seat = next(item for item in offline.seats if item.id == seat.id)
        assert offline_seat.presence is PresenceStatus.OFFLINE
        assert offline_seat.controller_kind is ControllerKind.HUMAN
        assert offline_seat.controller_access_session_id == access_id
        assert repository.get(seat.id).controller_access_session_id == access_id

        with engine.begin() as connection:
            connection.execute(
                update(room_access_sessions)
                .where(room_access_sessions.c.id == access_id)
                .values(last_seen_at=datetime.now(timezone.utc))
            )

        reconnected = service.lobby(room.room.id, campaign.id)
        reconnected_seat = next(item for item in reconnected.seats if item.id == seat.id)
        assert reconnected_seat.presence is PresenceStatus.CONNECTED
        assert reconnected_seat.controller_kind is ControllerKind.HUMAN
        assert reconnected_seat.controller_access_session_id == access_id
    finally:
        engine.dispose()


def test_dm_seat_can_be_reassigned_from_one_dm_controller_to_another() -> None:
    engine = _engine()
    try:
        room, campaign, _character = _seed_active_campaign(engine)
        repository = SeatRepository(engine)
        service = SeatService(repository)
        dm_a = _insert_access(engine, room.room.id, authority="dm")
        dm_b = _insert_access(engine, room.room.id, authority="dm")
        seat = service.create_seat(room.room.id, campaign.id, SeatCreate(role=SeatRole.DM))

        first = service.set_controller(
            room.room.id,
            campaign.id,
            seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=dm_a,
            ),
        )
        assert first.controller_access_session_id == dm_a

        second = service.set_controller(
            room.room.id,
            campaign.id,
            seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=dm_b,
            ),
        )
        assert second.controller_access_session_id == dm_b
        assert repository.get(seat.id).controller_access_session_id == dm_b
    finally:
        engine.dispose()
