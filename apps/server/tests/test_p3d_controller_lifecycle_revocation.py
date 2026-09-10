from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select, update

from app.db import metadata
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.persistence.characters import characters
from app.persistence.rooms.ai_controllers import (
    AIControllerGrantRepository,
    AIControllerGrantUnauthorizedPersistenceError,
)
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    sessions,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(
        engine,
        tables=[
            characters,
            rooms,
            room_access_sessions,
            campaigns,
            campaign_seats,
            sessions,
            ai_controller_grants,
        ],
    )
    return engine


def _seed_campaign(connection, *, room_id=None, active=True):
    now = datetime.now(timezone.utc)
    room_id = room_id or uuid4()
    campaign_id, dm_seat_id = uuid4(), uuid4()
    if connection.scalar(select(rooms.c.id).where(rooms.c.id == room_id)) is None:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code=str(room_id).replace("-", "")[:6].upper(),
                name="Lifecycle",
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
        insert(campaigns).values(
            id=campaign_id,
            room_id=room_id,
            name=str(campaign_id),
            ruleset="dnd5e-2014",
            status="active",
        )
    )
    connection.execute(
        insert(campaign_seats).values(
            id=dm_seat_id,
            campaign_id=campaign_id,
            role="dm",
            label="DM",
            controller_kind="none",
            controller_access_session_id=None,
            ai_controller_grant_id=None,
            controller_epoch=0,
            selected_character_id=None,
            archived_at=None,
        )
    )
    if active:
        connection.execute(
            update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
        )
    return room_id, campaign_id, dm_seat_id


def _mint(repo, *, room_id, campaign_id, seat_id, now):
    token = mint_ai_controller_token()
    return repo.mint_pre_session_dm(
        grant_id=token.grant_id,
        room_id=room_id,
        campaign_id=campaign_id,
        seat_id=seat_id,
        secret_hash=token.secret_hash,
        secret_prefix=token.display_hint,
        expires_at=now + timedelta(minutes=5),
        now=now,
    )


def test_dm_seat_ai_to_none_revokes_grant_and_advances_epoch_atomically() -> None:
    engine = _engine()
    grants = AIControllerGrantRepository(engine)
    seats = SeatRepository(engine)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            room_id, campaign_id, seat_id = _seed_campaign(connection)
        grant = _mint(grants, room_id=room_id, campaign_id=campaign_id, seat_id=seat_id, now=now)
        changed = seats.set_controller(
            seat_id=seat_id,
            controller_kind="none",
            controller_access_session_id=None,
        )
        assert changed is not None
        assert changed.controller_kind == "none"
        assert changed.ai_controller_grant_id is None
        assert changed.controller_epoch == grant.generation + 1
        stored = grants.get(grant.id)
        assert stored is not None and stored.status == "revoked"
        with pytest.raises(AIControllerGrantUnauthorizedPersistenceError):
            grants.resolve_current_scope(grant.id)
    finally:
        engine.dispose()


def test_archiving_ai_dm_seat_revokes_current_grant() -> None:
    engine = _engine()
    grants = AIControllerGrantRepository(engine)
    seats = SeatRepository(engine)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            room_id, campaign_id, seat_id = _seed_campaign(connection)
        grant = _mint(grants, room_id=room_id, campaign_id=campaign_id, seat_id=seat_id, now=now)
        archived = seats.archive(seat_id)
        assert archived is not None and archived.archived_at is not None
        assert archived.controller_epoch == grant.generation + 1
        stored = grants.get(grant.id)
        assert stored is not None and stored.status == "revoked"
    finally:
        engine.dispose()


def test_campaign_terminal_status_and_active_switch_revoke_unbound_dm_grants() -> None:
    engine = _engine()
    grants = AIControllerGrantRepository(engine)
    campaigns_repo = CampaignRepository(engine)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            room_id, first_campaign, first_seat = _seed_campaign(connection)
            _, second_campaign, _second_seat = _seed_campaign(
                connection,
                room_id=room_id,
                active=False,
            )
        first = _mint(
            grants,
            room_id=room_id,
            campaign_id=first_campaign,
            seat_id=first_seat,
            now=now,
        )
        assert campaigns_repo.select_active_campaign(
            room_id=room_id,
            campaign_id=second_campaign,
        )
        assert grants.get(first.id).status == "revoked"  # type: ignore[union-attr]
        with pytest.raises(AIControllerGrantUnauthorizedPersistenceError):
            grants.resolve_current_scope(first.id)

        assert campaigns_repo.select_active_campaign(
            room_id=room_id,
            campaign_id=first_campaign,
        )
        second = _mint(
            grants,
            room_id=room_id,
            campaign_id=first_campaign,
            seat_id=first_seat,
            now=now + timedelta(seconds=1),
        )
        completed = campaigns_repo.set_status(first_campaign, "completed")
        assert completed is not None and completed.status == "completed"
        assert grants.get(second.id).status == "revoked"  # type: ignore[union-attr]
    finally:
        engine.dispose()
