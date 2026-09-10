from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine

from app.content import load_default_content_registry
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.rooms.ai_controllers import (
    AIControllerHandoffError,
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
    TableEventSessionNotActiveError,
)
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import ai_controller_grants, rooms, sessions
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
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True, pool_size=12, max_overflow=12)
    _reset_database(engine)
    command.upgrade(_alembic_config(), "heads")
    try:
        yield engine
    finally:
        engine.dispose()


def _active_grants(engine: Engine, seat_id):
    with engine.connect() as connection:
        return connection.execute(
            select(ai_controller_grants).where(
                ai_controller_grants.c.seat_id == seat_id,
                ai_controller_grants.c.status == "active",
            )
        ).mappings().all()


def _capture(call):
    try:
        return call()
    except Exception as exc:  # the losing concurrent request is expected to fail closed
        return exc


def _setup_player_table(engine: Engine, *, handoff: bool) -> SimpleNamespace:
    registry = load_default_content_registry()
    room_service = RoomService(RoomRepository(engine))
    owner = room_service.create_room(
        CreateRoomRequest(name="P3-D matrix", password="secret", display_name="Origin")
    )
    dm = room_service.enter_room(
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

    origin_context = room_service.authenticate(owner.room.id, owner.access_token)
    dm_context = room_service.authenticate(owner.room.id, dm.access_token)
    event_service = TableEventService(TableEventRepository(engine))
    session_service = SessionService(SessionRepository(engine), event_service=event_service)
    started = session_service.start_session(owner.room.id, campaign.id, dm_context)
    controllers = AIControllerService(AIControllerGrantRepository(engine), event_service)
    issued = None
    if handoff:
        issued = controllers.let_ai_control_player(
            room_id=owner.room.id,
            campaign_id=campaign.id,
            session_id=started.id,
            seat_id=player_seat.id,
            context=origin_context,
            request=AIHandoffRequest(temporary_instruction="Protect the wizard"),
        )
    return SimpleNamespace(
        room_service=room_service,
        owner=owner,
        campaign_service=campaign_service,
        campaign=campaign,
        seat_service=seat_service,
        player_seat=player_seat,
        origin_context=origin_context,
        event_service=event_service,
        session_service=session_service,
        started=started,
        controllers=controllers,
        issued=issued,
    )


def _new_member(table: SimpleNamespace, *, name: str, remote_addr: str):
    grant = table.room_service.enter_room(
        EnterRoomRequest(
            code=table.owner.room.code,
            password="secret",
            display_name=name,
        ),
        remote_addr=remote_addr,
    )
    return table.room_service.authenticate(table.owner.room.id, grant.access_token)


def _setup_pre_session_ai_dm(engine: Engine, *, notifier=None) -> SimpleNamespace:
    room_service = RoomService(RoomRepository(engine))
    owner = room_service.create_room(
        CreateRoomRequest(name="AI DM matrix", password="secret", display_name="Owner")
    )
    owner_context = room_service.authenticate(owner.room.id, owner.access_token)
    campaign_service = CampaignService(CampaignRepository(engine))
    campaign = campaign_service.create_campaign(
        owner.room.id,
        CampaignCreate(name="AI Campaign", ruleset="dnd5e-2014"),
    )
    campaign_service.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaign_service.select_campaign(owner.room.id, campaign.id)

    seat_service = SeatService(SeatRepository(engine))
    dm_seat = seat_service.create_seat(
        owner.room.id,
        campaign.id,
        SeatCreate(role=SeatRole.DM, label="AI DM"),
    )
    event_service = TableEventService(TableEventRepository(engine), notifier=notifier)
    controllers = AIControllerService(AIControllerGrantRepository(engine), event_service)
    issued = controllers.configure_pre_session_ai_dm(
        room_id=owner.room.id,
        campaign_id=campaign.id,
        seat_id=dm_seat.id,
    )
    session_service = SessionService(SessionRepository(engine), event_service=event_service)
    return SimpleNamespace(
        room_service=room_service,
        owner=owner,
        owner_context=owner_context,
        campaign_service=campaign_service,
        campaign=campaign,
        seat_service=seat_service,
        dm_seat=dm_seat,
        event_service=event_service,
        controllers=controllers,
        session_service=session_service,
        issued=issued,
    )


def _start_ai_dm(table: SimpleNamespace):
    return table.session_service.start_session_as_ai_dm(
        table.owner.room.id,
        table.campaign.id,
        grant_id=table.issued.grant_id,
        generation=table.issued.generation,
    )


def test_two_let_ai_control_requests_leave_one_current_generation(postgres_engine: Engine) -> None:
    table = _setup_player_table(postgres_engine, handoff=False)
    barrier = Barrier(2)

    def handoff(label: str):
        barrier.wait(timeout=10)
        return _capture(lambda: table.controllers.let_ai_control_player(
            room_id=table.owner.room.id,
            campaign_id=table.campaign.id,
            session_id=table.started.id,
            seat_id=table.player_seat.id,
            context=table.origin_context,
            request=AIHandoffRequest(temporary_instruction=label),
        ))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(handoff, "first")
        second_future = pool.submit(handoff, "second")
        outcomes = [
            first_future.result(timeout=30),
            second_future.result(timeout=30),
        ]

    winners = [item for item in outcomes if not isinstance(item, Exception)]
    assert len(winners) == 1
    assert all(
        not isinstance(item, Exception) or isinstance(item, AIControllerHandoffError)
        for item in outcomes
    )
    winner = winners[0]
    seat = SeatRepository(postgres_engine).get(table.player_seat.id)
    assert seat is not None
    assert seat.controller_kind == "ai"
    assert seat.ai_controller_grant_id == winner.grant_id
    assert seat.controller_epoch == winner.generation
    active = _active_grants(postgres_engine, table.player_seat.id)
    assert [row["id"] for row in active] == [winner.grant_id]


def test_let_ai_control_racing_take_back_is_serializable(postgres_engine: Engine) -> None:
    table = _setup_player_table(postgres_engine, handoff=True)
    old = table.issued
    assert old is not None
    barrier = Barrier(2)

    def rehandoff():
        barrier.wait(timeout=10)
        return _capture(lambda: table.controllers.let_ai_control_player(
            room_id=table.owner.room.id,
            campaign_id=table.campaign.id,
            session_id=table.started.id,
            seat_id=table.player_seat.id,
            context=table.origin_context,
            request=AIHandoffRequest(temporary_instruction="second generation"),
        ))

    def take_back():
        barrier.wait(timeout=10)
        return _capture(lambda: table.controllers.take_back_player(
            room_id=table.owner.room.id,
            campaign_id=table.campaign.id,
            session_id=table.started.id,
            seat_id=table.player_seat.id,
            context=table.origin_context,
        ))

    with ThreadPoolExecutor(max_workers=2) as pool:
        rehandoff_future = pool.submit(rehandoff)
        takeback_future = pool.submit(take_back)
        rehandoff_result = rehandoff_future.result(timeout=30)
        takeback_result = takeback_future.result(timeout=30)

    assert takeback_result is None
    with pytest.raises(AIControllerUnauthorizedError):
        table.controllers.resolve_actor(old.token)

    seat = SeatRepository(postgres_engine).get(table.player_seat.id)
    assert seat is not None
    if isinstance(rehandoff_result, Exception):
        assert isinstance(rehandoff_result, AIControllerHandoffError)
        assert seat.controller_kind == "human"
        assert seat.controller_access_session_id == table.origin_context.access_session_id
        assert seat.controller_epoch == old.generation + 1
        assert _active_grants(postgres_engine, table.player_seat.id) == []
    else:
        assert seat.controller_kind == "ai"
        assert seat.ai_controller_grant_id == rehandoff_result.grant_id
        assert seat.controller_epoch == old.generation + 2
        active = _active_grants(postgres_engine, table.player_seat.id)
        assert [row["id"] for row in active] == [rehandoff_result.grant_id]


def test_take_back_racing_admin_reassignment_has_one_human_winner(postgres_engine: Engine) -> None:
    table = _setup_player_table(postgres_engine, handoff=True)
    issued = table.issued
    assert issued is not None
    h2 = _new_member(table, name="Replacement", remote_addr="127.0.0.3")
    barrier = Barrier(2)

    def take_back():
        barrier.wait(timeout=10)
        return _capture(lambda: table.controllers.take_back_player(
            room_id=table.owner.room.id,
            campaign_id=table.campaign.id,
            session_id=table.started.id,
            seat_id=table.player_seat.id,
            context=table.origin_context,
        ))

    def admin():
        barrier.wait(timeout=10)
        return _capture(lambda: table.controllers.administratively_reassign_player(
            room_id=table.owner.room.id,
            campaign_id=table.campaign.id,
            session_id=table.started.id,
            seat_id=table.player_seat.id,
            target_access_session_id=h2.access_session_id,
            admin_context=table.origin_context,
        ))

    with ThreadPoolExecutor(max_workers=2) as pool:
        takeback_future = pool.submit(take_back)
        admin_future = pool.submit(admin)
        outcomes = [takeback_future.result(timeout=30), admin_future.result(timeout=30)]

    assert sum(item is None for item in outcomes) == 1
    assert all(item is None or isinstance(item, AIControllerHandoffError) for item in outcomes)
    seat = SeatRepository(postgres_engine).get(table.player_seat.id)
    assert seat is not None
    assert seat.controller_kind == "human"
    assert seat.controller_access_session_id in {
        table.origin_context.access_session_id,
        h2.access_session_id,
    }
    assert seat.controller_epoch == issued.generation + 1
    assert _active_grants(postgres_engine, table.player_seat.id) == []


def test_two_admin_reassignments_leave_one_human_binding(postgres_engine: Engine) -> None:
    table = _setup_player_table(postgres_engine, handoff=True)
    issued = table.issued
    assert issued is not None
    h2 = _new_member(table, name="H2", remote_addr="127.0.0.3")
    h3 = _new_member(table, name="H3", remote_addr="127.0.0.4")
    barrier = Barrier(2)

    def admin(target):
        barrier.wait(timeout=10)
        return _capture(lambda: table.controllers.administratively_reassign_player(
            room_id=table.owner.room.id,
            campaign_id=table.campaign.id,
            session_id=table.started.id,
            seat_id=table.player_seat.id,
            target_access_session_id=target.access_session_id,
            admin_context=table.origin_context,
        ))

    with ThreadPoolExecutor(max_workers=2) as pool:
        f2 = pool.submit(admin, h2)
        f3 = pool.submit(admin, h3)
        outcomes = [f2.result(timeout=30), f3.result(timeout=30)]

    assert sum(item is None for item in outcomes) == 1
    assert all(item is None or isinstance(item, AIControllerHandoffError) for item in outcomes)
    seat = SeatRepository(postgres_engine).get(table.player_seat.id)
    assert seat is not None
    assert seat.controller_kind == "human"
    assert seat.controller_access_session_id in {h2.access_session_id, h3.access_session_id}
    assert seat.controller_epoch == issued.generation + 1
    assert _active_grants(postgres_engine, table.player_seat.id) == []


def test_pre_session_rotate_racing_start_has_one_generation_path(postgres_engine: Engine) -> None:
    table = _setup_pre_session_ai_dm(postgres_engine)
    first = table.issued
    barrier = Barrier(2)

    def rotate():
        barrier.wait(timeout=10)
        return _capture(lambda: table.controllers.configure_pre_session_ai_dm(
            room_id=table.owner.room.id,
            campaign_id=table.campaign.id,
            seat_id=table.dm_seat.id,
        ))

    def start():
        barrier.wait(timeout=10)
        return _capture(lambda: _start_ai_dm(table))

    with ThreadPoolExecutor(max_workers=2) as pool:
        rotate_future = pool.submit(rotate)
        start_future = pool.submit(start)
        rotate_result = rotate_future.result(timeout=30)
        start_result = start_future.result(timeout=30)

    assert sum(not isinstance(item, Exception) for item in (rotate_result, start_result)) == 1
    seat = SeatRepository(postgres_engine).get(table.dm_seat.id)
    assert seat is not None and seat.controller_kind == "ai"
    if not isinstance(start_result, Exception):
        assert seat.ai_controller_grant_id == first.grant_id
        assert table.controllers.authenticate(first.token).session_id == start_result.id
    else:
        assert not isinstance(rotate_result, Exception)
        assert seat.ai_controller_grant_id == rotate_result.grant_id
        with pytest.raises(AIControllerUnauthorizedError):
            table.controllers.authenticate(first.token)


@pytest.mark.parametrize("mutation", ["none", "archive"])
def test_dm_seat_mutation_racing_start_is_serializable(
    postgres_engine: Engine,
    mutation: str,
) -> None:
    table = _setup_pre_session_ai_dm(postgres_engine)
    barrier = Barrier(2)

    def mutate():
        barrier.wait(timeout=10)
        if mutation == "archive":
            return _capture(lambda: table.seat_service.archive_seat(
                table.owner.room.id,
                table.campaign.id,
                table.dm_seat.id,
            ))
        return _capture(lambda: table.seat_service.set_controller(
            table.owner.room.id,
            table.campaign.id,
            table.dm_seat.id,
            SeatControllerPatch(controller_kind=ControllerKind.NONE),
        ))

    def start():
        barrier.wait(timeout=10)
        return _capture(lambda: _start_ai_dm(table))

    with ThreadPoolExecutor(max_workers=2) as pool:
        mutation_future = pool.submit(mutate)
        start_future = pool.submit(start)
        mutation_result = mutation_future.result(timeout=30)
        start_result = start_future.result(timeout=30)

    assert sum(not isinstance(item, Exception) for item in (mutation_result, start_result)) == 1
    if not isinstance(start_result, Exception):
        assert table.session_service.get_session(
            table.owner.room.id,
            table.campaign.id,
            start_result.id,
        ).status.value == "active"
        assert table.controllers.authenticate(table.issued.token).session_id == start_result.id
    else:
        with pytest.raises(AIControllerUnauthorizedError):
            table.controllers.authenticate(table.issued.token)


@pytest.mark.parametrize("transition", ["completed", "switch"])
def test_campaign_lifecycle_racing_pre_session_start_is_linearizable(
    postgres_engine: Engine,
    transition: str,
) -> None:
    table = _setup_pre_session_ai_dm(postgres_engine)
    second_campaign = None
    if transition == "switch":
        second_campaign = table.campaign_service.create_campaign(
            table.owner.room.id,
            CampaignCreate(name="Other", ruleset="dnd5e-2014"),
        )
        table.campaign_service.set_status(
            table.owner.room.id,
            second_campaign.id,
            CampaignStatus.ACTIVE,
        )
    barrier = Barrier(2)

    def change_campaign():
        barrier.wait(timeout=10)
        if transition == "completed":
            return _capture(lambda: table.campaign_service.set_status(
                table.owner.room.id,
                table.campaign.id,
                CampaignStatus.COMPLETED,
            ))
        assert second_campaign is not None
        return _capture(lambda: table.campaign_service.select_campaign(
            table.owner.room.id,
            second_campaign.id,
        ))

    def start():
        barrier.wait(timeout=10)
        return _capture(lambda: _start_ai_dm(table))

    with ThreadPoolExecutor(max_workers=2) as pool:
        transition_future = pool.submit(change_campaign)
        start_future = pool.submit(start)
        transition_result = transition_future.result(timeout=30)
        start_result = start_future.result(timeout=30)

    assert not isinstance(transition_result, Exception)
    if isinstance(start_result, Exception):
        with pytest.raises(AIControllerUnauthorizedError):
            table.controllers.authenticate(table.issued.token)
    else:
        auth = table.controllers.authenticate(table.issued.token)
        assert auth.session_id == start_result.id
        assert auth.is_current_dm is True


def test_duplicate_ai_dm_start_binds_grant_once(postgres_engine: Engine) -> None:
    table = _setup_pre_session_ai_dm(postgres_engine)
    barrier = Barrier(2)

    def start():
        barrier.wait(timeout=10)
        return _capture(lambda: _start_ai_dm(table))

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(start)
        f2 = pool.submit(start)
        outcomes = [f1.result(timeout=30), f2.result(timeout=30)]

    winners = [item for item in outcomes if not isinstance(item, Exception)]
    assert len(winners) == 1
    with postgres_engine.connect() as connection:
        active_sessions = connection.scalars(
            select(sessions.c.id).where(
                sessions.c.campaign_id == table.campaign.id,
                sessions.c.status == "active",
            )
        ).all()
    assert active_sessions == [winners[0].id]
    auth = table.controllers.authenticate(table.issued.token)
    assert auth.session_id == winners[0].id


class _WaitGateNotifier:
    def __init__(self) -> None:
        self.waiting = Event()

    def notify(self, _session_id) -> None:
        return None

    def register(self, session_id):
        return session_id

    async def wait(self, _handle, timeout: float) -> bool:
        self.waiting.set()
        await asyncio.sleep(min(timeout, 0.4))
        return False

    def unregister(self, _handle) -> None:
        return None


def test_ai_dm_end_racing_write_revokes_old_actor(postgres_engine: Engine) -> None:
    table = _setup_pre_session_ai_dm(postgres_engine)
    started = _start_ai_dm(table)
    actor = table.controllers.resolve_actor(table.issued.token)
    barrier = Barrier(2)

    def write():
        barrier.wait(timeout=10)
        return _capture(lambda: table.event_service.append_event(
            actor,
            TableEventAppend(kind="p3d.end_race", payload={"ok": True}),
        ))

    def end():
        barrier.wait(timeout=10)
        return _capture(lambda: table.session_service.end_session_actor(
            table.owner.room.id,
            table.campaign.id,
            started.id,
            actor,
        ))

    with ThreadPoolExecutor(max_workers=2) as pool:
        write_future = pool.submit(write)
        end_future = pool.submit(end)
        write_result = write_future.result(timeout=30)
        end_result = end_future.result(timeout=30)

    assert not isinstance(end_result, Exception)
    assert not isinstance(write_result, Exception) or isinstance(
        write_result,
        (TableEventActorUnauthorizedError, TableEventSessionNotActiveError),
    )
    with pytest.raises(AIControllerUnauthorizedError):
        table.controllers.resolve_actor(table.issued.token)
    assert table.session_service.get_session(
        table.owner.room.id,
        table.campaign.id,
        started.id,
    ).status.value == "ended"


def test_owner_abandon_wakes_ai_wait_into_revoked_scope(postgres_engine: Engine) -> None:
    notifier = _WaitGateNotifier()
    table = _setup_pre_session_ai_dm(postgres_engine, notifier=notifier)
    started = _start_ai_dm(table)
    actor = table.controllers.resolve_actor(table.issued.token)
    cursor = table.event_service.current_cursor(actor).last_event_seq

    def wait_for_event():
        return _capture(lambda: asyncio.run(table.event_service.wait_after(
            actor,
            after_seq=cursor,
            limit=20,
            timeout=0.4,
        )))

    with ThreadPoolExecutor(max_workers=1) as pool:
        waiter = pool.submit(wait_for_event)
        assert notifier.waiting.wait(timeout=10)
        abandoned = table.session_service.abandon_session(
            table.owner.room.id,
            table.campaign.id,
            started.id,
            table.owner_context,
        )
        wait_result = waiter.result(timeout=30)

    assert abandoned.status.value == "abandoned"
    assert isinstance(wait_result, TableEventActorUnauthorizedError)
    with pytest.raises(AIControllerUnauthorizedError):
        table.controllers.resolve_actor(table.issued.token)
    with postgres_engine.connect() as connection:
        room_active_campaign = connection.scalar(
            select(rooms.c.active_campaign_id).where(rooms.c.id == table.owner.room.id)
        )
    assert room_active_campaign == table.campaign.id
