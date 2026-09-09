from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert, update
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableEventActorUnauthorizedError,
    TableEventAppend,
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


def test_event_append_revalidates_actor_inside_write_transaction() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    access_id = uuid4()
    seat_id = uuid4()

    try:
        with engine.begin() as connection:
            connection.execute(
                insert(rooms).values(
                    id=room_id,
                    code="P3AAUTH001",
                    name="P3-A auth",
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
                    id=access_id,
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
                    id=seat_id,
                    campaign_id=campaign_id,
                    role="dm",
                    label="DM",
                    controller_kind="human",
                    controller_access_session_id=access_id,
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
                    dm_seat_id=seat_id,
                    dm_controller_kind="human",
                    dm_controller_access_session_id=access_id,
                    started_at=now,
                    ended_at=None,
                    created_at=now,
                )
            )
            connection.execute(
                insert(session_participants).values(
                    id=uuid4(),
                    session_id=session_id,
                    seat_id=seat_id,
                    role_snapshot="dm",
                    controller_kind_at_join="human",
                    controller_access_session_id_at_join=access_id,
                    active_character_id=None,
                    joined_at=now,
                    left_at=None,
                )
            )

        service = TableEventService(TableEventRepository(engine))
        actor = service.resolve_human_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=RoomAccessContext(
                room_id=room_id,
                access_session_id=access_id,
                authority=RoomAccessAuthority.DM,
            ),
        )

        # The actor object is now stale. append_event must not trust this prior
        # resolution: persistence revalidates it while holding the Session lock.
        with engine.begin() as connection:
            connection.execute(
                update(room_access_sessions)
                .where(room_access_sessions.c.id == access_id)
                .values(revoked_at=datetime.now(timezone.utc))
            )

        with pytest.raises(TableEventActorUnauthorizedError):
            service.append_event(
                actor,
                TableEventAppend(kind="diagnostic.stale", payload={"must": "not-write"}),
            )
    finally:
        engine.dispose()
