from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import time
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, insert, text, update
from sqlalchemy.engine import Engine

from app.domain.rooms.table_events import (
    TableActorContext,
    TableActorKind,
    TableEventService,
)
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


def _probe_database(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text("SELECT 1")).scalar_one())


def test_many_idle_waiters_release_postgres_pool_between_event_scans(
    constrained_postgres_engine: Engine,
) -> None:
    actor = _seed_human_dm_actor(constrained_postgres_engine)
    event_service = TableEventService(
        TableEventRepository(constrained_postgres_engine),
        notifier=None,
    )

    async def exercise() -> tuple[list[object], float]:
        waiters = [
            asyncio.create_task(
                event_service.wait_after(
                    actor,
                    after_seq=0,
                    limit=20,
                    timeout=0.6,
                )
            )
            for _ in range(12)
        ]

        # Give every waiter enough time to perform its initial durable scan and
        # enter the non-DB sleep. With only two pool slots, pinning connections
        # for the full long-poll would make the probe below time out/fail.
        await asyncio.sleep(0.15)
        started = time.perf_counter()
        probe = await asyncio.wait_for(
            asyncio.to_thread(_probe_database, constrained_postgres_engine),
            timeout=0.5,
        )
        elapsed = time.perf_counter() - started
        assert probe == 1

        pages = await asyncio.gather(*waiters)
        return list(pages), elapsed

    pages, probe_elapsed = asyncio.run(exercise())

    assert probe_elapsed < 0.5
    assert len(pages) == 12
    for page in pages:
        assert page.cursor == 0
        assert page.current_seq == 0
        assert page.events == []
