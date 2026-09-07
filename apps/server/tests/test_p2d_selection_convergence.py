from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, insert

from app.db import metadata
from app.persistence.characters import characters
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.tables import (
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
        ],
    )
    return engine


def _seed_selected_character(engine):
    room_id = uuid4()
    campaign_id = uuid4()
    character_id = uuid4()
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="ROOM01",
                name="Room",
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
            insert(characters).values(
                id=character_id,
                name="Mira",
                ruleset="dnd5e-2014",
                current_version_id=None,
                archived_at=None,
            )
        )
        connection.execute(insert(room_characters).values(room_id=room_id, character_id=character_id))
        connection.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="Campaign",
                ruleset="dnd5e-2014",
                status="active",
            )
        )
        connection.execute(
            insert(campaign_roster_entries).values(
                campaign_id=campaign_id,
                character_id=character_id,
                status="active",
            )
        )
        connection.execute(
            rooms.update().where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
        )

    seats = SeatRepository(engine)
    seat = seats.create(campaign_id=campaign_id, role="player", label="Player")
    selected = seats.select_character_if_eligible(
        seat_id=seat.id,
        campaign_id=campaign_id,
        character_id=character_id,
    )
    assert selected is not None
    assert selected.selected_character_id == character_id
    return room_id, campaign_id, character_id, seat.id


def test_retired_or_dead_roster_mutation_clears_seat_selection_in_same_write_path() -> None:
    for status in ("retired", "dead"):
        engine = _engine()
        try:
            _room_id, campaign_id, character_id, seat_id = _seed_selected_character(engine)
            campaigns_repo = CampaignRepository(engine)
            seats = SeatRepository(engine)

            updated = campaigns_repo.update_roster_status(
                campaign_id=campaign_id,
                character_id=character_id,
                status=status,
            )

            assert updated is not None
            assert updated.status == status
            assert seats.get(seat_id).selected_character_id is None
        finally:
            engine.dispose()


def test_roster_removal_clears_seat_selection_and_releases_character() -> None:
    engine = _engine()
    try:
        _room_id, campaign_id, character_id, seat_id = _seed_selected_character(engine)
        campaigns_repo = CampaignRepository(engine)
        seats = SeatRepository(engine)

        assert campaigns_repo.remove_roster_entry(
            campaign_id=campaign_id,
            character_id=character_id,
        )
        assert seats.get(seat_id).selected_character_id is None
    finally:
        engine.dispose()
