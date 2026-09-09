from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.rooms.exploration import (
    ExplorationStageService,
    StageUpdateRequest,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService, TableEventSessionNotActiveError
from app.persistence.rooms.exploration import ExplorationRepository, session_stages
from app.persistence.rooms.table_runtime import (
    TableEventRepository,
    session_events,
    session_table_runtime,
)
from app.persistence.rooms.tables import (
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    session_participants,
    sessions,
)


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    return engine


def _seed_dm(engine) -> tuple[UUID, UUID, UUID, UUID]:
    now = datetime.now(timezone.utc)
    room_id, campaign_id, session_id, access_id, seat_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    with engine.begin() as connection:
        connection.execute(insert(rooms).values(
            id=room_id,
            code=f"P3B{uuid4().hex[:8].upper()}",
            name="Canonical Stage",
            password_salt=b"s" * 32,
            password_hash=b"p" * 64,
            owner_key_hash=b"o" * 32,
            dm_key_hash=b"d" * 32,
            active_campaign_id=None,
            created_at=now,
            updated_at=now,
        ))
        connection.execute(insert(room_access_sessions).values(
            id=access_id,
            room_id=room_id,
            authority="dm",
            token_hash=b"a" * 32,
            display_name="DM",
            created_at=now,
            last_seen_at=now,
            revoked_at=None,
        ))
        connection.execute(insert(campaigns).values(
            id=campaign_id,
            room_id=room_id,
            name="Campaign",
            ruleset="dnd5e-2014",
            status="active",
            created_at=now,
            updated_at=now,
        ))
        connection.execute(
            update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
        )
        connection.execute(insert(campaign_seats).values(
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
        ))
        connection.execute(insert(sessions).values(
            id=session_id,
            campaign_id=campaign_id,
            status="active",
            dm_seat_id=seat_id,
            dm_controller_kind="human",
            dm_controller_access_session_id=access_id,
            started_at=now,
            ended_at=None,
            created_at=now,
        ))
        connection.execute(insert(session_participants).values(
            id=uuid4(),
            session_id=session_id,
            seat_id=seat_id,
            role_snapshot="dm",
            controller_kind_at_join="human",
            controller_access_session_id_at_join=access_id,
            active_character_id=None,
            joined_at=now,
            left_at=None,
        ))
    return room_id, campaign_id, session_id, access_id


def _dm(events, room_id, campaign_id, session_id, access_id):
    return events.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        context=RoomAccessContext(
            room_id=room_id,
            access_session_id=access_id,
            authority=RoomAccessAuthority.DM,
        ),
    )


def test_stage_reuses_canonical_event_idempotency_before_session_status() -> None:
    engine = _engine()
    try:
        room_id, campaign_id, session_id, access_id = _seed_dm(engine)
        events = TableEventService(TableEventRepository(engine))
        service = ExplorationStageService(ExplorationRepository(engine), events)
        dm = _dm(events, room_id, campaign_id, session_id, access_id)
        request = StageUpdateRequest(
            expected_revision=0,
            text="Original Stage",
            idempotency_key="stable-stage",
        )

        first = service.replace_stage(dm, request)
        with engine.begin() as connection:
            connection.execute(
                update(sessions)
                .where(sessions.c.id == session_id)
                .values(status="ended", ended_at=datetime.now(timezone.utc))
            )

        replay = service.replace_stage(dm, request)
        assert replay == first

        with pytest.raises(TableEventSessionNotActiveError):
            service.replace_stage(
                dm,
                StageUpdateRequest(
                    expected_revision=1,
                    text="Must not commit",
                    idempotency_key="new-after-end",
                ),
            )

        with engine.connect() as connection:
            event_rows = connection.execute(
                select(session_events).where(session_events.c.session_id == session_id)
            ).mappings().all()
            runtime = connection.execute(
                select(session_table_runtime).where(
                    session_table_runtime.c.session_id == session_id
                )
            ).mappings().one()
            stage = connection.execute(
                select(session_stages).where(session_stages.c.session_id == session_id)
            ).mappings().one()

        assert len(event_rows) == 1
        assert event_rows[0]["seq"] == 1
        assert event_rows[0]["kind"] == "stage.updated"
        assert event_rows[0]["payload"]["stage_revision"] == 1
        assert runtime["revision"] == 1
        assert runtime["last_event_seq"] == 1
        assert stage["revision"] == 1
        assert stage["text"] == "Original Stage"
    finally:
        engine.dispose()
