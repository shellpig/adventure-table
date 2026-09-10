from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.rooms.campaigns import (
    CampaignCreate,
    CampaignService,
    CampaignStatus,
    RosterAdd,
)
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.seats import (
    ControllerKind,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_character_state import (
    TableCharacterStatePatch,
    TableCharacterStateService,
)
from app.domain.rooms.table_events import TableEventService
from app.persistence.characters import CharacterRepository, StaleBuildVersionError
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_character_state import TableCharacterStatePersistence
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
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
    room_repository = RoomRepository(engine)
    rooms = RoomService(room_repository)
    owner = rooms.create_room(
        CreateRoomRequest(name="P3-C State Room", password="secret", display_name="Player")
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

    characters = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    character = characters.create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    RoomWorkspaceRepository(engine).attach_character(
        room_id=owner.room.id,
        character_id=character.id,
    )

    campaigns = CampaignService(CampaignRepository(engine))
    campaign = campaigns.create_campaign(
        owner.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(owner.room.id, campaign.id)
    campaigns.add_character(
        owner.room.id,
        campaign.id,
        RosterAdd(character_id=character.id),
    )

    seats = SeatService(SeatRepository(engine))
    dm_seat = seats.create_seat(
        owner.room.id,
        campaign.id,
        SeatCreate(role=SeatRole.DM, label="DM"),
    )
    seats.set_controller(
        owner.room.id,
        campaign.id,
        dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )
    player_seat = seats.create_seat(
        owner.room.id,
        campaign.id,
        SeatCreate(role=SeatRole.PLAYER, label="Mira Player"),
    )
    seats.set_controller(
        owner.room.id,
        campaign.id,
        player_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=owner.access_session_id,
        ),
    )
    seats.select_character(
        owner.room.id,
        campaign.id,
        player_seat.id,
        character.id,
    )

    sessions = SessionService(SessionRepository(engine))
    dm_context = rooms.authenticate(owner.room.id, dm.access_token)
    player_context = rooms.authenticate(owner.room.id, owner.access_token)
    started = sessions.start_session(owner.room.id, campaign.id, dm_context)

    events = TableEventService(TableEventRepository(engine))
    state_service = TableCharacterStateService(
        TableCharacterStatePersistence(engine, registry, events.repository),
        ExplorationSubjectRepository(engine),
        events,
    )
    dm_actor = events.resolve_human_actor(
        room_id=owner.room.id,
        campaign_id=campaign.id,
        session_id=started.id,
        context=dm_context,
    )
    player_actor = events.resolve_human_actor(
        room_id=owner.room.id,
        campaign_id=campaign.id,
        session_id=started.id,
        context=player_context,
    )
    return characters, character, player_seat, events, state_service, dm_actor, player_actor


def test_table_state_self_and_dm_proxy_commit_state_with_audit_event() -> None:
    engine = _engine()
    try:
        characters, character, player_seat, events, service, dm_actor, player_actor = _setup(engine)

        self_updated = service.apply_patch(
            player_actor,
            subject_seat_id=player_seat.id,
            patch=TableCharacterStatePatch(current_hp=7, idempotency_key="self-hp"),
        )
        assert self_updated.state.current_hp == 7

        proxied = service.apply_patch(
            dm_actor,
            subject_seat_id=player_seat.id,
            patch=TableCharacterStatePatch(temporary_hp=4, idempotency_key="dm-temp-hp"),
        )
        assert proxied.state.current_hp == 7
        assert proxied.state.temporary_hp == 4

        page = events.list_after(dm_actor, after_seq=0, limit=20)
        state_events = [item for item in page.events if item.kind == "character.state.updated"]
        assert len(state_events) == 2
        assert state_events[0].acting_seat_id == player_seat.id
        assert state_events[0].subject_seat_id == player_seat.id
        assert state_events[0].execution_mode.value == "self"
        assert state_events[0].payload == {"changed_fields": ["current_hp"]}
        assert state_events[1].acting_seat_id == dm_actor.seat_id
        assert state_events[1].subject_seat_id == player_seat.id
        assert state_events[1].subject_character_id == character.id
        assert state_events[1].execution_mode.value == "dm_proxy"
        assert state_events[1].payload == {"changed_fields": ["temporary_hp"]}
        assert characters.load_character(character.id).state.temporary_hp == 4
    finally:
        engine.dispose()


def test_failed_state_projection_rolls_back_event_and_state_atomically() -> None:
    engine = _engine()
    try:
        characters, character, player_seat, events, service, _dm_actor, player_actor = _setup(engine)
        before = events.current_cursor(player_actor)
        before_state = characters.load_character(character.id).state

        with pytest.raises(StaleBuildVersionError):
            service.apply_patch(
                player_actor,
                subject_seat_id=player_seat.id,
                patch=TableCharacterStatePatch(
                    current_hp=1,
                    expected_current_version_id=uuid4(),
                    idempotency_key="stale-build",
                ),
            )

        after = events.current_cursor(player_actor)
        assert after == before
        assert characters.load_character(character.id).state == before_state
        assert events.list_after(player_actor, after_seq=before.last_event_seq, limit=20).events == []
    finally:
        engine.dispose()
