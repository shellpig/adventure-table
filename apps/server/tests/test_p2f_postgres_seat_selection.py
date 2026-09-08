from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import Engine

from app.persistence.characters import characters
from app.persistence.rooms.seats import SeatPersistenceConflictError, SeatRepository
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


def _seed_selection_collision(engine: Engine) -> tuple[UUID, UUID, tuple[UUID, UUID]]:
    room_id = uuid4()
    campaign_id = uuid4()
    character_id = uuid4()
    seat_ids = (uuid4(), uuid4())
    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="P2FSEAT001",
                name="P2-F seat concurrency",
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
                name="Concurrent selection",
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
            insert(campaign_seats),
            [
                {
                    "id": seat_id,
                    "campaign_id": campaign_id,
                    "role": "player",
                    "label": f"Player {index + 1}",
                    "controller_kind": "none",
                    "controller_access_session_id": None,
                    "selected_character_id": None,
                    "archived_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
                for index, seat_id in enumerate(seat_ids)
            ],
        )

    return campaign_id, character_id, seat_ids


def test_concurrent_seat_selection_has_one_database_winner(
    postgres_engine: Engine,
) -> None:
    campaign_id, character_id, seat_ids = _seed_selection_collision(postgres_engine)
    start = Barrier(2)

    def attempt(seat_id: UUID) -> tuple[str, UUID | None]:
        repository = SeatRepository(postgres_engine)
        start.wait(timeout=10)
        try:
            stored = repository.select_character_if_eligible(
                seat_id=seat_id,
                campaign_id=campaign_id,
                character_id=character_id,
            )
        except SeatPersistenceConflictError:
            return ("conflict", None)
        assert stored is not None
        return ("ok", stored.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            future.result(timeout=20)
            for future in (
                executor.submit(attempt, seat_ids[0]),
                executor.submit(attempt, seat_ids[1]),
            )
        ]

    assert sorted(outcome for outcome, _seat_id in outcomes) == ["conflict", "ok"]
    winner_id = next(seat_id for outcome, seat_id in outcomes if outcome == "ok")
    assert winner_id in seat_ids

    with postgres_engine.connect() as connection:
        persisted = connection.execute(
            select(campaign_seats.c.id, campaign_seats.c.selected_character_id)
            .where(campaign_seats.c.campaign_id == campaign_id)
            .order_by(campaign_seats.c.id)
        ).all()

    selected = [row for row in persisted if row.selected_character_id == character_id]
    unselected = [row for row in persisted if row.selected_character_id is None]
    assert len(selected) == 1
    assert selected[0].id == winner_id
    assert len(unselected) == 1
