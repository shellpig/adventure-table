from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.service import RoomService
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.tables import (
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
)
from app.persistence.rooms.workspace import RoomWorkspaceRepository


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


def _count(engine, table) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(table)) or 0)


def test_human_controller_session_is_restricted_but_room_hard_delete_cleans_seat_first() -> None:
    engine = _engine()
    room = RoomService(RoomRepository(engine)).create_room(
        CreateRoomRequest(name="Delete Me", password="secret")
    )
    campaign_id = uuid4()
    access_session_id = uuid4()
    seat_id = uuid4()
    now = datetime.now(timezone.utc)

    try:
        with engine.begin() as connection:
            connection.execute(
                insert(campaigns).values(
                    id=campaign_id,
                    room_id=room.room.id,
                    name="Campaign",
                    ruleset="dnd5e-2014",
                    status="active",
                )
            )
            connection.execute(
                insert(room_access_sessions).values(
                    id=access_session_id,
                    room_id=room.room.id,
                    authority="member",
                    token_hash=b"x" * 32,
                    display_name="Player",
                    created_at=now,
                    last_seen_at=now,
                    revoked_at=None,
                )
            )
            connection.execute(
                insert(campaign_seats).values(
                    id=seat_id,
                    campaign_id=campaign_id,
                    role="player",
                    label="Player",
                    controller_kind="human",
                    controller_access_session_id=access_session_id,
                    selected_character_id=None,
                    archived_at=None,
                )
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    delete(room_access_sessions).where(
                        room_access_sessions.c.id == access_session_id
                    )
                )

        assert _count(engine, campaign_seats) == 1
        assert _count(engine, room_access_sessions) >= 1

        RoomWorkspaceRepository(engine).hard_delete_room(room.room.id)

        assert _count(engine, campaign_seats) == 0
        assert _count(engine, campaigns) == 0
        assert _count(engine, room_access_sessions) == 0
        assert _count(engine, rooms) == 0
    finally:
        engine.dispose()
