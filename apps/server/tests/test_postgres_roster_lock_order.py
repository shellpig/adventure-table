"""Roster writes and Session Start must take Seat and Roster locks in one order.

Session Start locks campaign_seats and then campaign_roster_entries. Roster
writes that cascade into Seat selection used to do the reverse — update the
Roster row, then clear the Seat — which deadlocks the pair on PostgreSQL: Start
holds the Seats and waits for the Roster row, the Roster write holds the Roster
row and waits for the Seats.

The Start side here is hand-rolled rather than a real start_session() call. What
is under test is the lock order, and driving it directly is the only way to hold
the Seat locks open across a barrier so the interleaving is deterministic instead
of raced.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Barrier
import time
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import Engine

from app.persistence.characters import characters
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.tables import (
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_characters,
    rooms,
)


POSTGRES_URL = os.environ.get("P2_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P2_POSTGRES_URL is only supplied by the P2 Non-E2E PostgreSQL job",
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


def _seed_campaign_with_seated_character(engine: Engine) -> tuple[UUID, UUID]:
    room_id = uuid4()
    campaign_id = uuid4()
    character_id = uuid4()
    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="LOCKORDER1",
                name="Lock order",
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
            insert(characters).values(
                id=character_id,
                name="Mira",
                ruleset="dnd5e-2014",
                current_version_id=None,
                archived_at=None,
            )
        )
        connection.execute(
            insert(room_characters).values(
                room_id=room_id,
                character_id=character_id,
                created_at=now,
            )
        )
        connection.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="Lock order campaign",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(campaign_roster_entries).values(
                campaign_id=campaign_id,
                character_id=character_id,
                status="active",
                added_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(campaign_seats).values(
                id=uuid4(),
                campaign_id=campaign_id,
                role="player",
                label="Mira Seat",
                controller_kind="none",
                controller_access_session_id=None,
                selected_character_id=character_id,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
        )

    return campaign_id, character_id


def test_roster_retirement_does_not_deadlock_against_session_start_locks(
    postgres_engine: Engine,
) -> None:
    campaign_id, character_id = _seed_campaign_with_seated_character(postgres_engine)
    holding_seats = Barrier(2)

    def start_side() -> str:
        # The order start_from_lobby() uses: Seats first, Roster second.
        with postgres_engine.begin() as connection:
            connection.execute(
                select(campaign_seats.c.id)
                .where(
                    campaign_seats.c.campaign_id == campaign_id,
                    campaign_seats.c.archived_at.is_(None),
                )
                .order_by(campaign_seats.c.created_at, campaign_seats.c.id)
                .with_for_update()
            ).all()
            holding_seats.wait(timeout=10)
            # Give the roster side time to issue its first statement while this
            # transaction still holds every Seat lock.
            time.sleep(0.5)
            connection.execute(
                select(campaign_roster_entries.c.status)
                .where(
                    campaign_roster_entries.c.campaign_id == campaign_id,
                    campaign_roster_entries.c.character_id == character_id,
                )
                .with_for_update()
            ).all()
        return "start"

    def roster_side() -> str:
        repository = CampaignRepository(postgres_engine)
        holding_seats.wait(timeout=10)
        entry = repository.update_roster_status(
            campaign_id=campaign_id,
            character_id=character_id,
            status="retired",
        )
        assert entry is not None
        assert entry.status == "retired"
        return "roster"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (executor.submit(start_side), executor.submit(roster_side))
        # A deadlock surfaces here as OperationalError from whichever side
        # PostgreSQL chooses to abort.
        assert sorted(future.result(timeout=30) for future in futures) == [
            "roster",
            "start",
        ]

    with postgres_engine.connect() as connection:
        seat_selection = connection.execute(
            select(campaign_seats.c.selected_character_id)
            .where(campaign_seats.c.campaign_id == campaign_id)
        ).scalars().all()
        roster_status = connection.execute(
            select(campaign_roster_entries.c.status)
            .where(campaign_roster_entries.c.campaign_id == campaign_id)
        ).scalars().all()

    # Retirement still cascades: the Seat releases the retired Character.
    assert roster_status == ["retired"]
    assert seat_selection == [None]
