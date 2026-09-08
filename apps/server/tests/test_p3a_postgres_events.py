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
from sqlalchemy import create_engine, insert, select, text, update
from sqlalchemy.engine import Engine

from app.persistence.rooms.table_runtime import (
    TableEventRepository,
    session_events,
    session_table_runtime,
)
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
def postgres_engine() -> Engine:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_config(), "heads")
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_session(engine: Engine):
    now = datetime.now(timezone.utc)
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    dm_access_id = uuid4()
    dm_seat_id = uuid4()

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="P3APG0001",
                name="P3-A postgres",
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
                id=dm_access_id,
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
                name="Campaign",
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
                label="DM",
                controller_kind="human",
                controller_access_session_id=dm_access_id,
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
                dm_controller_access_session_id=dm_access_id,
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
                controller_access_session_id_at_join=dm_access_id,
                active_character_id=None,
                joined_at=now,
                left_at=None,
            )
        )
    return room_id, campaign_id, session_id, dm_seat_id


def test_concurrent_event_append_allocates_unique_monotonic_sequence(
    postgres_engine: Engine,
) -> None:
    room_id, campaign_id, session_id, dm_seat_id = _seed_session(postgres_engine)
    start = Barrier(8)

    def append(number: int) -> int:
        repository = TableEventRepository(postgres_engine)
        start.wait(timeout=10)
        event = repository.append(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            kind="diagnostic.concurrent",
            acting_seat_id=dm_seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode="self",
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={"writer": number},
            idempotency_key=f"writer-{number}",
        )
        return event.seq

    with ThreadPoolExecutor(max_workers=8) as executor:
        seqs = sorted(
            future.result(timeout=30)
            for future in [executor.submit(append, number) for number in range(8)]
        )

    assert seqs == list(range(1, 9))
    with postgres_engine.connect() as connection:
        persisted = connection.execute(
            select(session_events.c.seq)
            .where(session_events.c.session_id == session_id)
            .order_by(session_events.c.seq)
        ).scalars().all()
        runtime = connection.execute(
            select(
                session_table_runtime.c.revision,
                session_table_runtime.c.last_event_seq,
            ).where(session_table_runtime.c.session_id == session_id)
        ).one()
    assert list(persisted) == list(range(1, 9))
    assert runtime.revision == 8
    assert runtime.last_event_seq == 8


def test_p3a_migration_backfills_zero_runtime_for_existing_p2_session() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        command.upgrade(_alembic_config(), "0014_p2e_sessions")
        room_id, campaign_id, session_id, _dm_seat_id = _seed_session(engine)

        command.upgrade(_alembic_config(), "heads")

        with engine.connect() as connection:
            runtime = connection.execute(
                select(
                    session_table_runtime.c.revision,
                    session_table_runtime.c.last_event_seq,
                ).where(session_table_runtime.c.session_id == session_id)
            ).one()
        assert room_id is not None
        assert campaign_id is not None
        assert runtime.revision == 0
        assert runtime.last_event_seq == 0
    finally:
        engine.dispose()
