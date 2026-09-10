from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, select, update

from app.db import metadata
from app.domain.rooms.ai_controllers import (
    AIControllerService,
    AIControllerUnauthorizedError,
)
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import TableActorKind, TableEventService
from app.persistence.characters import characters
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository, session_events
from app.persistence.rooms.tables import campaign_seats, campaigns, rooms


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    return engine


def _seed_ai_dm_lobby(connection):
    now = datetime.now(timezone.utc)
    room_id, campaign_id, dm_seat_id = uuid4(), uuid4(), uuid4()
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code="P3DD2A",
            name="AI DM Journey",
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
    connection.execute(
        update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
    )
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


def test_ai_dm_token_start_actor_end_and_revoke_journey() -> None:
    engine = _engine()
    event_service = TableEventService(TableEventRepository(engine))
    controller_service = AIControllerService(
        AIControllerGrantRepository(engine),
        event_service,
    )
    session_service = SessionService(
        SessionRepository(engine),
        SessionLiveRepository(engine),
        event_service,
    )
    try:
        with engine.begin() as connection:
            room_id, campaign_id, dm_seat_id = _seed_ai_dm_lobby(connection)

        issued = controller_service.configure_pre_session_ai_dm(
            room_id=room_id,
            campaign_id=campaign_id,
            seat_id=dm_seat_id,
        )
        pre_session = controller_service.authenticate(issued.token)
        assert pre_session.session_id is None
        assert pre_session.role == "dm"
        with pytest.raises(AIControllerUnauthorizedError):
            controller_service.resolve_actor(issued.token)

        started = session_service.start_session_as_ai_dm(
            room_id,
            campaign_id,
            grant_id=issued.grant_id,
            generation=issued.generation,
        )
        assert started.dm_controller_kind == "ai"
        assert started.dm_controller_ai_grant_id == issued.grant_id
        assert started.dm_controller_generation == issued.generation

        actor = controller_service.resolve_actor(issued.token)
        assert actor.actor_kind is TableActorKind.AI
        assert actor.is_current_dm
        assert actor.session_id == started.id

        ended = session_service.end_session_actor(
            room_id,
            campaign_id,
            started.id,
            actor,
        )
        assert ended.status.value == "ended"

        with engine.connect() as connection:
            kinds = connection.scalars(
                select(session_events.c.kind)
                .where(session_events.c.session_id == started.id)
                .order_by(session_events.c.seq)
            ).all()
        assert kinds[-1] == "session.ended"

        with pytest.raises(AIControllerUnauthorizedError):
            controller_service.authenticate(issued.token)
    finally:
        engine.dispose()
