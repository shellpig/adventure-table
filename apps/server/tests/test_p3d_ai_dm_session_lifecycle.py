from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select, update

from app.db import metadata
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.persistence.characters import characters
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.sessions import (
    SessionAlreadyActivePersistenceError,
    SessionRepository,
    SessionStartControllerMismatchPersistenceError,
)
from app.persistence.rooms.tables import (
    active_character_session_leases,
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    session_participants,
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
            session_participants,
            active_character_session_leases,
            ai_controller_grants,
        ],
    )
    return engine


def _seed_campaign(connection):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, dm_seat_id = uuid4(), uuid4(), uuid4()
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code="P3DAIS",
            name="AI Session",
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
            name="Campaign",
            ruleset="dnd5e-2014",
            status="active",
        )
    )
    connection.execute(update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id))
    connection.execute(
        insert(campaign_seats).values(
            id=dm_seat_id,
            campaign_id=campaign_id,
            role="dm",
            label="AI DM",
            controller_kind="none",
            controller_access_session_id=None,
            ai_controller_grant_id=None,
            controller_epoch=0,
            selected_character_id=None,
            archived_at=None,
        )
    )
    return room_id, campaign_id, dm_seat_id


def test_ai_dm_start_binds_pre_session_grant_once_and_finalize_revokes_it() -> None:
    engine = _engine()
    grants = AIControllerGrantRepository(engine)
    sessions_repo = SessionRepository(engine)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            room_id, campaign_id, dm_seat_id = _seed_campaign(connection)
        token = mint_ai_controller_token()
        grant = grants.mint_pre_session_dm(
            grant_id=token.grant_id,
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=dm_seat_id,
            secret_hash=token.secret_hash,
            secret_prefix=token.display_hint,
            expires_at=now + timedelta(minutes=5),
            now=now,
        )

        started = sessions_repo.start_from_ai_dm_grant(
            room_id=room_id,
            campaign_id=campaign_id,
            grant_id=grant.id,
            generation=grant.generation,
        )
        assert started.dm_controller_kind == "ai"
        assert started.dm_controller_ai_grant_id == grant.id
        assert started.dm_controller_generation == grant.generation

        bound = grants.get(grant.id)
        assert bound is not None
        assert bound.session_id == started.id
        assert bound.pre_session_expires_at is None
        assert bound.bound_at is not None

        with pytest.raises(SessionAlreadyActivePersistenceError):
            sessions_repo.start_from_ai_dm_grant(
                room_id=room_id,
                campaign_id=campaign_id,
                grant_id=grant.id,
                generation=grant.generation,
            )

        finalized = sessions_repo.finalize(started.id, status="ended")
        assert finalized is not None
        assert finalized.status == "ended"
        revoked = grants.get(grant.id)
        assert revoked is not None
        assert revoked.status == "revoked"
        assert revoked.revoked_at is not None
        assert revoked.temporary_instruction is None
    finally:
        engine.dispose()


def test_ai_dm_start_rechecks_expiry_and_current_seat_epoch_before_creating_session() -> None:
    engine = _engine()
    grants = AIControllerGrantRepository(engine)
    sessions_repo = SessionRepository(engine)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            room_id, campaign_id, dm_seat_id = _seed_campaign(connection)
        token = mint_ai_controller_token()
        grant = grants.mint_pre_session_dm(
            grant_id=token.grant_id,
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=dm_seat_id,
            secret_hash=token.secret_hash,
            secret_prefix=token.display_hint,
            expires_at=now + timedelta(minutes=5),
            now=now,
        )
        with engine.begin() as connection:
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == dm_seat_id)
                .values(controller_epoch=grant.generation + 1)
            )

        with pytest.raises(SessionStartControllerMismatchPersistenceError):
            sessions_repo.start_from_ai_dm_grant(
                room_id=room_id,
                campaign_id=campaign_id,
                grant_id=grant.id,
                generation=grant.generation,
            )
        with engine.connect() as connection:
            assert connection.scalar(select(sessions.c.id)) is None

        with engine.begin() as connection:
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == dm_seat_id)
                .values(controller_epoch=grant.generation)
            )
            connection.execute(
                update(ai_controller_grants)
                .where(ai_controller_grants.c.id == grant.id)
                .values(pre_session_expires_at=now - timedelta(seconds=1))
            )
        with pytest.raises(SessionStartControllerMismatchPersistenceError):
            sessions_repo.start_from_ai_dm_grant(
                room_id=room_id,
                campaign_id=campaign_id,
                grant_id=grant.id,
                generation=grant.generation,
            )
        with engine.connect() as connection:
            assert connection.scalar(select(sessions.c.id)) is None
    finally:
        engine.dispose()
