from __future__ import annotations

import base64
from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, insert, select, text, update
from sqlalchemy.engine import Engine

from app.domain.rooms.exploration import (
    ExplorationActionService,
    ExplorationInputKind,
    ExplorationInputRequest,
    ExplorationStageService,
    StageImageUpload,
    StageUpdateRequest,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.rooms.exploration import (
    ExplorationRepository,
    room_stage_images,
    session_stages,
)
from app.persistence.rooms.exploration_messages import (
    ExplorationMessageRepository,
    session_messages,
)
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
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


POSTGRES_URL = os.environ.get("P3_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P3_POSTGRES_URL is only supplied by the P3 Non-E2E PostgreSQL job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    config.attributes["target_database_url"] = POSTGRES_URL
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


def _seed_session(engine: Engine):
    now = datetime.now(timezone.utc)
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    dm_access_id = uuid4()
    dm_seat_id = uuid4()

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="P3BPG0001",
                name="P3-B postgres",
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
                id=dm_access_id,
                room_id=room_id,
                authority="dm",
                token_hash=b"b" * 32,
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
                id=dm_seat_id,
                campaign_id=campaign_id,
                role="dm",
                label="DM",
                controller_kind="human",
                controller_access_session_id=dm_access_id,
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
                dm_controller_kind="human",
                dm_controller_access_session_id=dm_access_id,
                started_at=now,
                ended_at=None,
                created_at=now,
            )
        )
        connection.execute(
            insert(session_participants).values(
                id=uuid4(),
                session_id=session_id,
                seat_id=dm_seat_id,
                role_snapshot="dm",
                controller_kind_at_join="human",
                controller_access_session_id_at_join=dm_access_id,
                active_character_id=None,
                joined_at=now,
                left_at=None,
            )
        )
    return room_id, campaign_id, session_id, dm_access_id


def _dm_actor(
    event_service: TableEventService,
    *,
    room_id,
    campaign_id,
    session_id,
    dm_access_id,
):
    return event_service.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        context=RoomAccessContext(
            room_id=room_id,
            access_session_id=dm_access_id,
            authority=RoomAccessAuthority.DM,
        ),
    )


def _png_upload() -> StageImageUpload:
    raw = b"\x89PNG\r\n\x1a\nP3B-PG"
    return StageImageUpload(
        media_type="image/png",
        filename="postgres-stage.png",
        data_base64=base64.b64encode(raw).decode("ascii"),
    )


def test_p3b_postgres_migration_indexes_and_atomic_stage_event(postgres_engine: Engine) -> None:
    room_id, campaign_id, session_id, dm_access_id = _seed_session(postgres_engine)
    event_service = TableEventService(TableEventRepository(postgres_engine))
    stage_service = ExplorationStageService(
        ExplorationRepository(postgres_engine),
        event_service,
    )
    actor = _dm_actor(
        event_service,
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        dm_access_id=dm_access_id,
    )

    stage = stage_service.replace_stage(
        actor,
        StageUpdateRequest(
            expected_revision=0,
            text="PostgreSQL gate",
            image=_png_upload(),
            idempotency_key="pg-stage-1",
        ),
    )

    inspector = inspect(postgres_engine)
    assert {item["name"] for item in inspector.get_indexes("room_stage_images")} >= {
        "ix_room_stage_images_room_id"
    }
    assert {item["name"] for item in inspector.get_indexes("session_stages")} >= {
        "ix_session_stages_image_id"
    }

    with postgres_engine.connect() as connection:
        stage_row = connection.execute(
            select(session_stages).where(session_stages.c.session_id == session_id)
        ).mappings().one()
        event_row = connection.execute(
            select(session_events).where(session_events.c.session_id == session_id)
        ).mappings().one()
        runtime_row = connection.execute(
            select(session_table_runtime).where(
                session_table_runtime.c.session_id == session_id
            )
        ).mappings().one()
        image_row = connection.execute(
            select(room_stage_images).where(room_stage_images.c.id == stage.image_id)
        ).mappings().one()

    assert stage.revision == 1
    assert stage_row["revision"] == 1
    assert stage_row["text"] == "PostgreSQL gate"
    assert stage_row["image_id"] == stage.image_id
    assert image_row["room_id"] == room_id
    assert event_row["seq"] == 1
    assert event_row["kind"] == "stage.updated"
    assert event_row["payload"]["stage_revision"] == 1
    assert event_row["payload"]["image_id"] == str(stage.image_id)
    assert runtime_row["revision"] == 1
    assert runtime_row["last_event_seq"] == 1


def test_p3b_postgres_stale_dm_rejection_rolls_back_stage_event_and_image(
    postgres_engine: Engine,
) -> None:
    room_id, campaign_id, session_id, dm_access_id = _seed_session(postgres_engine)
    event_service = TableEventService(TableEventRepository(postgres_engine))
    stage_service = ExplorationStageService(
        ExplorationRepository(postgres_engine),
        event_service,
    )
    actor = _dm_actor(
        event_service,
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        dm_access_id=dm_access_id,
    )

    with postgres_engine.begin() as connection:
        connection.execute(
            update(room_access_sessions)
            .where(room_access_sessions.c.id == dm_access_id)
            .values(revoked_at=datetime.now(timezone.utc))
        )

    with pytest.raises(TableEventActorUnauthorizedError):
        stage_service.replace_stage(
            actor,
            StageUpdateRequest(
                expected_revision=0,
                text="Must rollback",
                image=_png_upload(),
                idempotency_key="pg-stale",
            ),
        )

    with postgres_engine.connect() as connection:
        assert connection.execute(
            select(session_stages).where(session_stages.c.session_id == session_id)
        ).mappings().one_or_none() is None
        assert connection.execute(
            select(session_events).where(session_events.c.session_id == session_id)
        ).mappings().one_or_none() is None
        assert connection.execute(
            select(session_table_runtime).where(
                session_table_runtime.c.session_id == session_id
            )
        ).mappings().one_or_none() is None
        assert connection.execute(
            select(room_stage_images).where(room_stage_images.c.room_id == room_id)
        ).mappings().all() == []


def test_p3b_postgres_message_event_and_cursor_commit_once_on_idempotent_replay(
    postgres_engine: Engine,
) -> None:
    room_id, campaign_id, session_id, dm_access_id = _seed_session(postgres_engine)
    event_service = TableEventService(TableEventRepository(postgres_engine))
    action_service = ExplorationActionService(
        ExplorationSubjectRepository(postgres_engine),
        ExplorationMessageRepository(postgres_engine),
        event_service,
    )
    actor = _dm_actor(
        event_service,
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        dm_access_id=dm_access_id,
    )
    request = ExplorationInputRequest(
        kind=ExplorationInputKind.NARRATION,
        text="PostgreSQL narration",
        idempotency_key="pg-message-1",
    )

    first = action_service.send(actor, request)
    replay = action_service.send(actor, request)

    assert replay.id == first.id
    assert replay.seq == first.seq == 1
    with postgres_engine.connect() as connection:
        messages = connection.execute(
            select(session_messages).where(session_messages.c.session_id == session_id)
        ).mappings().all()
        events = connection.execute(
            select(session_events).where(session_events.c.session_id == session_id)
        ).mappings().all()
        runtime = connection.execute(
            select(session_table_runtime).where(
                session_table_runtime.c.session_id == session_id
            )
        ).mappings().one()

    assert len(messages) == 1
    assert messages[0]["event_id"] == first.id
    assert messages[0]["kind"] == "narration"
    assert messages[0]["text"] == "PostgreSQL narration"
    assert len(events) == 1
    assert events[0]["id"] == first.id
    assert events[0]["kind"] == "exploration.narration"
    assert runtime["revision"] == 1
    assert runtime["last_event_seq"] == 1


def test_p3b_postgres_stale_actor_rolls_back_message_event_and_cursor(
    postgres_engine: Engine,
) -> None:
    room_id, campaign_id, session_id, dm_access_id = _seed_session(postgres_engine)
    event_service = TableEventService(TableEventRepository(postgres_engine))
    action_service = ExplorationActionService(
        ExplorationSubjectRepository(postgres_engine),
        ExplorationMessageRepository(postgres_engine),
        event_service,
    )
    actor = _dm_actor(
        event_service,
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        dm_access_id=dm_access_id,
    )

    with postgres_engine.begin() as connection:
        connection.execute(
            update(room_access_sessions)
            .where(room_access_sessions.c.id == dm_access_id)
            .values(revoked_at=datetime.now(timezone.utc))
        )

    with pytest.raises(TableEventActorUnauthorizedError):
        action_service.send(
            actor,
            ExplorationInputRequest(
                kind=ExplorationInputKind.NARRATION,
                text="Must not commit",
                idempotency_key="pg-message-stale",
            ),
        )

    with postgres_engine.connect() as connection:
        assert connection.execute(
            select(session_messages).where(session_messages.c.session_id == session_id)
        ).mappings().all() == []
        assert connection.execute(
            select(session_events).where(session_events.c.session_id == session_id)
        ).mappings().all() == []
        assert connection.execute(
            select(session_table_runtime).where(
                session_table_runtime.c.session_id == session_id
            )
        ).mappings().one_or_none() is None


def test_p3b_postgres_projection_failure_rolls_back_message_event_and_cursor(
    postgres_engine: Engine,
) -> None:
    room_id, campaign_id, session_id, dm_access_id = _seed_session(postgres_engine)
    repository = TableEventRepository(postgres_engine)
    binding = repository.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        access_session_id=dm_access_id,
    )
    assert binding is not None

    def failing_projection(connection, event_id, _event_seq) -> None:
        connection.execute(
            insert(session_messages).values(
                id=uuid4(),
                session_id=session_id,
                event_id=event_id,
                acting_seat_id=binding.seat_id,
                subject_seat_id=None,
                subject_character_id=None,
                execution_mode="self",
                kind="narration",
                text="Must rollback with callback",
                visibility="public",
                recipient_seat_ids=[],
                source_command=None,
            )
        )
        raise RuntimeError("projection failed")

    with pytest.raises(RuntimeError, match="projection failed"):
        repository.append(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            kind="exploration.narration",
            acting_seat_id=binding.seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode="self",
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={"type": "narration", "text": "Must rollback with callback"},
            idempotency_key="pg-projection-failure",
            expected_actor_binding=binding,
            transaction_projection=failing_projection,
        )

    with postgres_engine.connect() as connection:
        assert connection.execute(
            select(session_messages).where(session_messages.c.session_id == session_id)
        ).mappings().all() == []
        assert connection.execute(
            select(session_events).where(session_events.c.session_id == session_id)
        ).mappings().all() == []
        assert connection.execute(
            select(session_table_runtime).where(
                session_table_runtime.c.session_id == session_id
            )
        ).mappings().one_or_none() is None
