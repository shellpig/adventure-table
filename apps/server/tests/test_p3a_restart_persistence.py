from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, insert, update

from app.db import metadata
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import (
    campaign_seats,
    campaigns,
    rooms,
    sessions,
)


def test_table_runtime_cursor_and_history_survive_engine_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "p3a-restart.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    metadata.create_all(engine)

    now = datetime.now(timezone.utc)
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    dm_seat_id = uuid4()

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="P3ARST0001",
                name="P3-A restart",
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
                controller_kind="none",
                controller_access_session_id=None,
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
                dm_controller_kind="none",
                dm_controller_access_session_id=None,
                started_at=now,
                ended_at=None,
                created_at=now,
            )
        )

    repository = TableEventRepository(engine)
    first = repository.append(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        kind="diagnostic.before-restart",
        acting_seat_id=None,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="system",
        visibility="public",
        recipient_seat_ids=(),
        payload_version=1,
        payload={"persisted": True},
        idempotency_key="before-restart",
    )
    assert first.seq == 1
    engine.dispose()

    reopened = create_engine(database_url)
    try:
        restarted_repository = TableEventRepository(reopened)
        runtime = restarted_repository.current_runtime(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
        )
        history = restarted_repository.list_after(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            after_seq=0,
            scan_limit=10,
        )

        assert runtime.revision == 1
        assert runtime.last_event_seq == 1
        assert [event.id for event in history] == [first.id]
        assert history[0].payload == {"persisted": True}
    finally:
        reopened.dispose()
