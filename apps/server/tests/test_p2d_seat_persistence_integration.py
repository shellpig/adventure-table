from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert

from app.db import metadata
from app.persistence.characters import characters
from app.persistence.rooms.seats import (
    SeatPersistenceConflictError,
    SeatRepository,
    SeatSelectionPersistenceError,
)
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_access_sessions,
    room_characters,
    rooms,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(
        engine,
        tables=[
            characters,
            rooms,
            room_access_sessions,
            room_characters,
            campaigns,
            campaign_roster_entries,
            campaign_seats,
            ai_controller_grants,
        ],
    )
    return engine


def _seed_room(connection, room_id, *, name):
    now = datetime.now(timezone.utc)
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code=name[:6].upper(),
            name=name,
            password_salt=b"s" * 32,
            password_hash=b"h" * 64,
            owner_key_hash=b"o" * 32,
            dm_key_hash=b"d" * 32,
            active_campaign_id=None,
            created_at=now,
            updated_at=now,
        )
    )


def _seed_character(connection, *, room_id, character_id, name):
    connection.execute(
        insert(characters).values(
            id=character_id,
            name=name,
            ruleset="dnd5e-2014",
            current_version_id=None,
            archived_at=None,
        )
    )
    connection.execute(
        insert(room_characters).values(room_id=room_id, character_id=character_id)
    )


def test_selection_transaction_rejects_cross_room_roster_corruption_and_duplicate_character() -> None:
    engine = _engine()
    repo = SeatRepository(engine)
    room_a = uuid4()
    room_b = uuid4()
    campaign_id = uuid4()
    same_room_character = uuid4()
    cross_room_character = uuid4()

    try:
        with engine.begin() as connection:
            _seed_room(connection, room_a, name="RoomA1")
            _seed_room(connection, room_b, name="RoomB1")
            _seed_character(
                connection,
                room_id=room_a,
                character_id=same_room_character,
                name="Mira",
            )
            _seed_character(
                connection,
                room_id=room_b,
                character_id=cross_room_character,
                name="Luna",
            )
            connection.execute(
                insert(campaigns).values(
                    id=campaign_id,
                    room_id=room_a,
                    name="Campaign A",
                    ruleset="dnd5e-2014",
                    status="active",
                )
            )
            connection.execute(
                insert(campaign_roster_entries),
                [
                    {
                        "campaign_id": campaign_id,
                        "character_id": same_room_character,
                        "status": "active",
                    },
                    {
                        "campaign_id": campaign_id,
                        "character_id": cross_room_character,
                        "status": "active",
                    },
                ],
            )

        first = repo.create(campaign_id=campaign_id, role="player", label="Seat 1")
        second = repo.create(campaign_id=campaign_id, role="player", label="Seat 2")

        selected = repo.select_character_if_eligible(
            seat_id=first.id,
            campaign_id=campaign_id,
            character_id=same_room_character,
        )
        assert selected is not None
        assert selected.selected_character_id == same_room_character

        with pytest.raises(SeatSelectionPersistenceError):
            repo.select_character_if_eligible(
                seat_id=second.id,
                campaign_id=campaign_id,
                character_id=cross_room_character,
            )

        with pytest.raises(SeatPersistenceConflictError):
            repo.select_character_if_eligible(
                seat_id=second.id,
                campaign_id=campaign_id,
                character_id=same_room_character,
            )
    finally:
        engine.dispose()


def test_selection_transaction_rechecks_roster_status_and_character_archive() -> None:
    engine = _engine()
    repo = SeatRepository(engine)
    room_id = uuid4()
    campaign_id = uuid4()
    character_id = uuid4()

    try:
        with engine.begin() as connection:
            _seed_room(connection, room_id, name="RoomC1")
            _seed_character(
                connection,
                room_id=room_id,
                character_id=character_id,
                name="Borin",
            )
            connection.execute(
                insert(campaigns).values(
                    id=campaign_id,
                    room_id=room_id,
                    name="Campaign C",
                    ruleset="dnd5e-2014",
                    status="active",
                )
            )
            connection.execute(
                insert(campaign_roster_entries).values(
                    campaign_id=campaign_id,
                    character_id=character_id,
                    status="retired",
                )
            )

        seat = repo.create(campaign_id=campaign_id, role="player", label=None)
        with pytest.raises(SeatSelectionPersistenceError):
            repo.select_character_if_eligible(
                seat_id=seat.id,
                campaign_id=campaign_id,
                character_id=character_id,
            )

        with engine.begin() as connection:
            connection.execute(
                campaign_roster_entries.update()
                .where(
                    campaign_roster_entries.c.campaign_id == campaign_id,
                    campaign_roster_entries.c.character_id == character_id,
                )
                .values(status="active")
            )
            connection.execute(
                characters.update()
                .where(characters.c.id == character_id)
                .values(archived_at=datetime.now(timezone.utc))
            )

        with pytest.raises(SeatSelectionPersistenceError):
            repo.select_character_if_eligible(
                seat_id=seat.id,
                campaign_id=campaign_id,
                character_id=character_id,
            )
    finally:
        engine.dispose()
