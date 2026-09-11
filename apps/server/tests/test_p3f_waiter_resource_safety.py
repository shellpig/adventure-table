from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import time
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
from anyio import to_thread
from httpx import ASGITransport, AsyncClient, Response
import pytest
from sqlalchemy import create_engine, insert, text, update
from sqlalchemy.engine import Engine

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_table_event_service
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventAppend,
    TableEventService,
)
from app.main import app
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import (
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    session_participants,
    sessions,
)


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


@pytest.fixture()
def constrained_postgres_engine() -> Engine:
    assert POSTGRES_URL is not None
    engine = create_engine(
        POSTGRES_URL,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
        pool_timeout=0.25,
    )
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_config(), "heads")
    try:
        yield engine
    finally:
        engine.dispose()


class _CountingNotifier:
    def __init__(self, target: int) -> None:
        self.target = target
        self.waiting = 0
        self.active_handles = 0
        self.all_waiting = asyncio.Event()
        self.release = asyncio.Event()
        self.loop = asyncio.get_running_loop()

    def notify(self, session_id: UUID) -> None:
        del session_id
        self.loop.call_soon_threadsafe(self.release.set)

    def register(self, session_id: UUID) -> object:
        self.active_handles += 1
        return session_id

    async def wait(self, handle: object, timeout: float) -> bool:
        del handle
        self.waiting += 1
        if self.waiting >= self.target:
            self.all_waiting.set()
        try:
            await asyncio.wait_for(self.release.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    def unregister(self, handle: object) -> None:
        del handle
        self.active_handles -= 1


def _seed_human_dm_actor(engine: Engine) -> TableActorContext:
    now = datetime.now(timezone.utc)
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    access_session_id = uuid4()
    dm_seat_id = uuid4()

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="P3FWAIT001",
                name="P3-F waiter pool",
                password_salt=b"s" * 32,
                password_hash=b"p" * 64,
                owner_key_hash=b"o" * 32,
                dm_key_hash=b"d" * 32,
                active_campaign_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(room_access_sessions).values(
                id=access_session_id,
                room_id=room_id,
                authority="dm",
                token_hash=b"w" * 32,
                display_name="Waiter DM",
                created_at=now,
                last_seen_at=now,
                revoked_at=None,
            )
        )
        connection.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="Waiter Campaign",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            update(rooms)
            .where(rooms.c.id == room_id)
            .values(active_campaign_id=campaign_id)
        )
        connection.execute(
            insert(campaign_seats).values(
                id=dm_seat_id,
                campaign_id=campaign_id,
                role="dm",
                label="Waiter DM",
                controller_kind="human",
                controller_access_session_id=access_session_id,
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
                dm_seat_id=dm_seat_id,
                dm_controller_kind="human",
                dm_controller_access_session_id=access_session_id,
                started_at=now,
                ended_at=None,
                created_at=now,
            )
        )
        connection.execute(
            insert(session_participants).values(
                id=uuid4(),
                session_id=session_id,
                seat_id=dm_seat_id,
                role_snapshot="dm",
                controller_kind_at_join="human",
                controller_access_session_id_at_join=access_session_id,
                active_character_id=None,
                joined_at=now,
                left_at=None,
            )
        )

    return TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        seat_id=dm_seat_id,
        controlled_seat_ids=(dm_seat_id,),
        role="dm",
        is_current_dm=True,
        access_session_id=access_session_id,
    )


def _checked_out(engine: Engine) -> int:
    checkedout = getattr(engine.pool, "checkedout")
    return int(checkedout())


def test_many_asgi_waiters_release_postgres_pool_and_worker_capacity(
    constrained_postgres_engine: Engine,
) -> None:
    actor = _seed_human_dm_actor(constrained_postgres_engine)
    context = RoomAccessContext(
        room_id=actor.room_id,
        access_session_id=actor.access_session_id,
        authority=RoomAccessAuthority.DM,
    )

    async def exercise() -> tuple[list[Response], float]:
        notifier = _CountingNotifier(target=12)
        event_service = TableEventService(
            TableEventRepository(constrained_postgres_engine),
            notifier=notifier,
        )
        app.dependency_overrides[get_room_access_context] = lambda: context
        app.dependency_overrides[get_table_event_service] = lambda: event_service
        prefix = (
            f"/api/rooms/{actor.room_id}/campaigns/{actor.campaign_id}"
            f"/sessions/{actor.session_id}"
        )
        transport = ASGITransport(app=app)
        worker_limiter = to_thread.current_default_thread_limiter()
        previous_worker_tokens = worker_limiter.total_tokens
        worker_limiter.total_tokens = 4

        try:
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                waiters = [
                    asyncio.create_task(
                        client.get(f"{prefix}/events/wait?after=0&limit=20&timeout=2")
                    )
                    for _ in range(notifier.target)
                ]

                # Reaching the production notifier wait point proves every ASGI
                # request completed actor resolution plus both durable scans.
                # The worker pool is also deliberately tiny: a sync long-poll
                # that held one worker per request could never place all 12 here.
                await asyncio.wait_for(notifier.all_waiting.wait(), timeout=2.0)
                assert notifier.waiting == notifier.target
                assert notifier.active_handles == notifier.target
                assert worker_limiter.borrowed_tokens == 0
                assert _checked_out(constrained_postgres_engine) == 0

                started = time.perf_counter()
                runtime = await asyncio.wait_for(client.get(f"{prefix}/runtime"), timeout=0.5)
                probe_elapsed = time.perf_counter() - started
                assert runtime.status_code == 200
                assert runtime.json()["last_event_seq"] == 0

                # Exercise cancellation cleanup while the other requests remain
                # pending. The production wait_after() finally block must release
                # notifier handles even on request cancellation.
                cancelled = waiters[-4:]
                for task in cancelled:
                    task.cancel()
                await asyncio.gather(*cancelled, return_exceptions=True)
                assert notifier.active_handles == 8
                assert worker_limiter.borrowed_tokens == 0
                assert _checked_out(constrained_postgres_engine) == 0

                # Publish through the real durable TableEventService. notify() is
                # thread-safe here because normal sync gameplay routes may append
                # from a worker thread while long-poll requests live on the loop.
                event = await asyncio.to_thread(
                    event_service.append_event,
                    actor,
                    TableEventAppend(
                        kind="diagnostic.waiter_wake",
                        payload={"source": "p3-f"},
                        idempotency_key="p3f-waiter-wake",
                    ),
                )
                assert event.seq == 1

                responses = list(await asyncio.gather(*waiters[:8]))
                assert notifier.active_handles == 0
                assert worker_limiter.borrowed_tokens == 0
                assert _checked_out(constrained_postgres_engine) == 0
                return responses, probe_elapsed
        finally:
            worker_limiter.total_tokens = previous_worker_tokens
            app.dependency_overrides.pop(get_room_access_context, None)
            app.dependency_overrides.pop(get_table_event_service, None)

    responses, probe_elapsed = asyncio.run(exercise())

    assert probe_elapsed < 0.5
    assert len(responses) == 8
    for response in responses:
        assert response.status_code == 200
        body = response.json()
        assert body["cursor"] == 1
        assert body["current_seq"] == 1
        assert [event["kind"] for event in body["events"]] == ["diagnostic.waiter_wake"]

    assert _checked_out(constrained_postgres_engine) == 0
