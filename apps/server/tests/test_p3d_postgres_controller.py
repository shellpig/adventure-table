from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import MetaData, Table, create_engine, insert, select, text, update
from sqlalchemy.engine import Engine

from app.content import load_default_content_registry
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.rooms.ai_controllers import (
    AIControllerService,
    AIControllerUnauthorizedError,
    AIHandoffRequest,
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
from app.domain.rooms.table_events import (
    TableEventActorUnauthorizedError,
    TableEventAppend,
    TableEventService,
)
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.workspace import RoomWorkspaceRepository


POSTGRES_URL = os.environ.get("P3_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P3_POSTGRES_URL is only supplied by the P3 Non-E2E PostgreSQL job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    config.attributes["target_database_url"] = POSTGRES_URL
    return config


def _reset_database(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@pytest.fixture()
def postgres_engine() -> Engine:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True, pool_size=8, max_overflow=8)
    _reset_database(engine)
    command.upgrade(_alembic_config(), "heads")
    try:
        yield engine
    finally:
        engine.dispose()


def test_p2_human_controller_rows_survive_p3d_migration() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        _reset_database(engine)
        config = _alembic_config()
        command.upgrade(config, "0019_p3c_check_command")

        legacy = MetaData()
        legacy.reflect(
            bind=engine,
            only=[
                "rooms",
                "room_access_sessions",
                "campaigns",
                "campaign_seats",
                "sessions",
                "session_participants",
            ],
        )
        rooms = legacy.tables["rooms"]
        access = legacy.tables["room_access_sessions"]
        campaigns = legacy.tables["campaigns"]
        seats = legacy.tables["campaign_seats"]
        sessions = legacy.tables["sessions"]
        participants = legacy.tables["session_participants"]

        now = datetime.now(timezone.utc)
        room_id, access_id, campaign_id, seat_id, session_id = (
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
        )
        with engine.begin() as connection:
            connection.execute(
                insert(rooms).values(
                    id=room_id,
                    code="P3DPG1",
                    name="Legacy Room",
                    password_salt=b"s" * 32,
                    password_hash=b"h" * 64,
                    owner_key_hash=b"o" * 32,
                    dm_key_hash=b"d" * 32,
                    active_campaign_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(access).values(
                    id=access_id,
                    room_id=room_id,
                    authority="dm",
                    token_hash=b"t" * 32,
                    display_name="DM",
                    created_at=now,
                    last_seen_at=now,
                    revoked_at=None,
                )
            )
            connection.execute(
                insert(campaigns).values(
                    id=campaign_id,
                    room_id=room_id,
                    name="Legacy Campaign",
                    ruleset="dnd5e-2014",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
            )
            connection.execute(
                insert(seats).values(
                    id=seat_id,
                    campaign_id=campaign_id,
                    role="dm",
                    label="DM",
                    controller_kind="human",
                    controller_access_session_id=access_id,
                    selected_character_id=None,
                    archived_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(sessions).values(
                    id=session_id,
                    campaign_id=campaign_id,
                    status="active",
                    dm_seat_id=seat_id,
                    dm_controller_kind="human",
                    dm_controller_access_session_id=access_id,
                    started_at=now,
                    ended_at=None,
                    created_at=now,
                )
            )
            connection.execute(
                insert(participants).values(
                    id=uuid4(),
                    session_id=session_id,
                    seat_id=seat_id,
                    role_snapshot="dm",
                    controller_kind_at_join="human",
                    controller_access_session_id_at_join=access_id,
                    active_character_id=None,
                    joined_at=now,
                    left_at=None,
                )
            )

        command.upgrade(config, "heads")
        current = MetaData()
        current.reflect(
            bind=engine,
            only=["campaign_seats", "sessions", "session_participants"],
        )
        with engine.connect() as connection:
            seat = connection.execute(
                select(current.tables["campaign_seats"]).where(
                    current.tables["campaign_seats"].c.id == seat_id
                )
            ).mappings().one()
            session = connection.execute(
                select(current.tables["sessions"]).where(
                    current.tables["sessions"].c.id == session_id
                )
            ).mappings().one()
            participant = connection.execute(
                select(current.tables["session_participants"]).where(
                    current.tables["session_participants"].c.session_id == session_id
                )
            ).mappings().one()
            constraint_names = set(
                connection.scalars(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conname IN ("
                        "'ck_campaign_seats_controller_binding', "
                        "'ck_sessions_dm_controller_binding', "
                        "'ck_session_participants_controller_binding')"
                    )
                ).all()
            )

        assert seat["controller_kind"] == "human"
        assert seat["controller_access_session_id"] == access_id
        assert seat["ai_controller_grant_id"] is None
        assert seat["controller_epoch"] == 0
        assert session["dm_controller_kind"] == "human"
        assert session["dm_controller_ai_grant_id"] is None
        assert session["dm_controller_generation"] is None
        assert participant["controller_kind_at_join"] == "human"
        assert participant["controller_ai_grant_id_at_join"] is None
        assert participant["controller_generation_at_join"] is None
        assert constraint_names == {
            "ck_campaign_seats_controller_binding",
            "ck_sessions_dm_controller_binding",
            "ck_session_participants_controller_binding",
        }
    finally:
        engine.dispose()


def _setup_handoff_table(engine: Engine):
    registry = load_default_content_registry()
    rooms = RoomService(RoomRepository(engine))
    owner = rooms.create_room(
        CreateRoomRequest(name="P3-D postgres", password="secret", display_name="Player")
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

    character_repository = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    character = character_repository.create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    RoomWorkspaceRepository(engine).attach_character(
        room_id=owner.room.id,
        character_id=character.id,
    )

    campaign_service = CampaignService(CampaignRepository(engine))
    campaign = campaign_service.create_campaign(
        owner.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaign_service.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaign_service.select_campaign(owner.room.id, campaign.id)
    campaign_service.add_character(
        owner.room.id,
        campaign.id,
        RosterAdd(character_id=character.id),
    )

    seat_service = SeatService(SeatRepository(engine))
    dm_seat = seat_service.create_seat(
        owner.room.id,
        campaign.id,
        SeatCreate(role=SeatRole.DM, label="DM"),
    )
    seat_service.set_controller(
        owner.room.id,
        campaign.id,
        dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )
    player_seat = seat_service.create_seat(
        owner.room.id,
        campaign.id,
        SeatCreate(role=SeatRole.PLAYER, label="Mira"),
    )
    seat_service.set_controller(
        owner.room.id,
        campaign.id,
        player_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=owner.access_session_id,
        ),
    )
    seat_service.select_character(owner.room.id, campaign.id, player_seat.id, character.id)

    player_context = rooms.authenticate(owner.room.id, owner.access_token)
    started = SessionService(SessionRepository(engine)).start_session(
        owner.room.id,
        campaign.id,
        rooms.authenticate(owner.room.id, dm.access_token),
    )
    events = TableEventService(TableEventRepository(engine))
    controllers = AIControllerService(AIControllerGrantRepository(engine), events)
    issued = controllers.let_ai_control_player(
        room_id=owner.room.id,
        campaign_id=campaign.id,
        session_id=started.id,
        seat_id=player_seat.id,
        context=player_context,
        request=AIHandoffRequest(temporary_instruction="Protect the wizard"),
    )
    return owner, campaign, started, player_seat, player_context, events, controllers, issued


def test_take_back_racing_old_ai_write_has_one_current_authority(
    postgres_engine: Engine,
) -> None:
    (
        owner,
        campaign,
        started,
        player_seat,
        player_context,
        events,
        controllers,
        issued,
    ) = _setup_handoff_table(postgres_engine)
    ai_actor = controllers.resolve_actor(issued.token)
    barrier = Barrier(2)

    def run_write():
        barrier.wait(timeout=10)
        try:
            return events.append_event(
                ai_actor,
                TableEventAppend(kind="p3d.concurrent_write", payload={"source": "old-ai"}),
            )
        except Exception as exc:
            return exc

    def run_take_back():
        barrier.wait(timeout=10)
        try:
            controllers.take_back_player(
                room_id=owner.room.id,
                campaign_id=campaign.id,
                session_id=started.id,
                seat_id=player_seat.id,
                context=player_context,
            )
            return None
        except Exception as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        write_future = pool.submit(run_write)
        take_back_future = pool.submit(run_take_back)
        write_result = write_future.result(timeout=30)
        take_back_result = take_back_future.result(timeout=30)

    assert take_back_result is None
    assert not isinstance(write_result, Exception) or isinstance(
        write_result,
        TableEventActorUnauthorizedError,
    )
    with pytest.raises(AIControllerUnauthorizedError):
        controllers.resolve_actor(issued.token)

    seat = SeatRepository(postgres_engine).get(player_seat.id)
    assert seat is not None
    assert seat.controller_kind == "human"
    assert seat.controller_access_session_id == player_context.access_session_id
    assert seat.ai_controller_grant_id is None
    assert seat.controller_epoch == issued.generation + 1
