from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Barrier, Lock
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine

from app.content import load_default_content_registry
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
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.pending_actions import (
    PendingActionCreateInput,
    PendingActionInvalidTransitionError,
    PendingActionService,
    PendingActionStatus,
    PendingActionTransitionInput,
    PendingActionVersionConflictError,
)
from app.domain.rooms.rolls import (
    FormalRollInput,
    RequestCheckInput,
    RollEngine,
    RollRequestType,
    RollService,
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
from app.domain.rooms.table_events import TableEventService
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_pending import PendingActionRepository, pending_actions
from app.persistence.rooms.p3c_rolls import RollRepository, roll_results
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
PERCEPTION = "srd5.1:skill:perception"


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    config.attributes["target_database_url"] = POSTGRES_URL
    return config


@pytest.fixture()
def postgres_engine() -> Engine:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True, pool_size=8, max_overflow=8)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_config(), "heads")
    try:
        yield engine
    finally:
        engine.dispose()


class _CountingRng:
    """Real dice, but every draw is observable."""

    def __init__(self) -> None:
        self.calls = 0
        self.lock = Lock()

    def randint(self, low: int, high: int) -> int:
        with self.lock:
            self.calls += 1
        return low + (self.calls % (high - low + 1))


class Table:
    def __init__(self, **fields) -> None:
        self.__dict__.update(fields)


def _setup(engine: Engine, rng: _CountingRng) -> Table:
    registry = load_default_content_registry()
    rooms = RoomService(RoomRepository(engine))
    owner = rooms.create_room(
        CreateRoomRequest(name="P3-C postgres", password="secret", display_name="Mira Player")
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
    seats.select_character(owner.room.id, campaign.id, player_seat.id, character.id)

    dm_context = rooms.authenticate(owner.room.id, dm.access_token)
    player_context = rooms.authenticate(owner.room.id, owner.access_token)
    started = SessionService(SessionRepository(engine)).start_session(
        owner.room.id, campaign.id, dm_context
    )

    events = TableEventService(TableEventRepository(engine))
    roll_repository = RollRepository(engine, events.repository)
    roll_service = RollService(
        roll_repository,
        ExplorationSubjectRepository(engine),
        events,
        CharacterRollModifierResolver(characters, registry),
        RollEngine(rng),
    )
    pending_service = PendingActionService(
        PendingActionRepository(engine, events.repository),
        ExplorationSubjectRepository(engine),
        events,
        roll_repository,
    )

    def actor(context):
        return events.resolve_human_actor(
            room_id=owner.room.id,
            campaign_id=campaign.id,
            session_id=started.id,
            context=context,
        )

    return Table(
        session_id=started.id,
        player_seat=player_seat,
        roll_service=roll_service,
        pending_service=pending_service,
        events=events,
        dm_actor=actor(dm_context),
        player_actor=actor(player_context),
    )


def _race(first, second):
    barrier = Barrier(2)

    def run(operation):
        def call():
            barrier.wait(timeout=10)
            try:
                return operation()
            except Exception as exc:  # returned so both outcomes can be asserted
                return exc

        return call

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run(first)), pool.submit(run(second))]
        return [future.result(timeout=30) for future in futures]


def test_concurrent_cancel_and_resolve_commit_exactly_one_pending_outcome(
    postgres_engine: Engine,
) -> None:
    table = _setup(postgres_engine, _CountingRng())
    action = table.pending_service.create(
        table.player_actor,
        PendingActionCreateInput(
            subject_seat_id=table.player_seat.id,
            text="I pry the lid off the sarcophagus.",
        ),
    )
    processing = table.pending_service.transition(
        table.player_actor,
        action.id,
        PendingActionTransitionInput(
            expected_version=action.version,
            to_status=PendingActionStatus.PROCESSING,
        ),
    )

    outcomes = _race(
        lambda: table.pending_service.transition(
            table.dm_actor,
            action.id,
            PendingActionTransitionInput(
                expected_version=processing.version,
                to_status=PendingActionStatus.CANCELLED,
            ),
        ),
        lambda: table.pending_service.transition(
            table.player_actor,
            action.id,
            PendingActionTransitionInput(
                expected_version=processing.version,
                to_status=PendingActionStatus.RESOLVED,
            ),
        ),
    )

    winners = [item for item in outcomes if not isinstance(item, Exception)]
    losers = [item for item in outcomes if isinstance(item, Exception)]
    assert len(winners) == 1
    assert len(losers) == 1
    # Losing on the compare-and-set and losing after re-reading an already
    # terminal row are both legitimate refusals; either way nothing commits.
    assert isinstance(
        losers[0],
        (PendingActionVersionConflictError, PendingActionInvalidTransitionError),
    )

    with postgres_engine.connect() as connection:
        row = connection.execute(
            select(pending_actions.c.status, pending_actions.c.version)
            .where(pending_actions.c.id == action.id)
        ).one()
    assert row.status == winners[0].status.value
    assert row.status in {"cancelled", "resolved"}
    assert row.version == processing.version + 1

    page = table.events.list_after(table.dm_actor, after_seq=0, limit=50)
    transitions = [
        item for item in page.events if item.kind == "pending_action.transitioned"
    ]
    # Create, one legal processing transition, one winning outcome. The loser
    # must not have appended a second durable outcome for the same action.
    assert len(transitions) == 2
    assert transitions[-1].payload["to_status"] == row.status


def test_concurrent_formal_completion_commits_one_result_and_one_rng_draw(
    postgres_engine: Engine,
) -> None:
    rng = _CountingRng()
    table = _setup(postgres_engine, rng)
    _group_id, requests = table.roll_service.request_check(
        table.dm_actor,
        RequestCheckInput(
            target_seat_ids=(table.player_seat.id,),
            request_type=RollRequestType.SKILL,
            skill_ref=PERCEPTION,
        ),
    )
    request = requests[0]
    draws_before = rng.calls

    outcomes = _race(
        lambda: table.roll_service.complete_formal(
            table.player_actor,
            FormalRollInput(roll_request_id=request.id),
        ),
        lambda: table.roll_service.complete_formal(
            table.dm_actor,
            FormalRollInput(roll_request_id=request.id),
        ),
    )

    results = [item for item in outcomes if not isinstance(item, Exception)]
    assert [item for item in outcomes if isinstance(item, Exception)] == []
    assert len({item.id for item in results}) == 1
    assert len({item.total for item in results}) == 1
    assert rng.calls - draws_before == 1

    with postgres_engine.connect() as connection:
        stored = connection.execute(
            select(func.count())
            .select_from(roll_results)
            .where(roll_results.c.roll_request_id == request.id)
        ).scalar_one()
    assert stored == 1


def test_cross_session_request_id_is_not_resolvable_on_postgres(
    postgres_engine: Engine,
) -> None:
    table = _setup(postgres_engine, _CountingRng())
    before = table.events.current_cursor(table.dm_actor)

    with pytest.raises(Exception):
        table.roll_service.complete_formal(
            table.player_actor,
            FormalRollInput(roll_request_id=uuid4()),
        )

    assert table.events.current_cursor(table.dm_actor) == before
