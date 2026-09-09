from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, update
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.main import app
from app.persistence.rooms.tables import (
    campaign_seats,
    campaigns,
    rooms,
    session_participants,
    sessions,
)


_STATE_KEYS = (
    "character_engine",
    "room_service",
    "room_access_throttle",
    "table_event_notifier",
    "table_event_service",
    "exploration_stage_service",
    "exploration_action_service",
    "session_resume_service",
)


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    return engine


def _replace_app_state(engine):
    previous = {
        key: getattr(app.state, key)
        for key in _STATE_KEYS
        if hasattr(app.state, key)
    }
    for key in _STATE_KEYS:
        if hasattr(app.state, key):
            delattr(app.state, key)
    app.state.character_engine = engine
    return previous


def _restore_app_state(previous) -> None:
    for key in _STATE_KEYS:
        if hasattr(app.state, key):
            delattr(app.state, key)
    for key, value in previous.items():
        setattr(app.state, key, value)


def _seed_active_dm_session(
    engine,
    *,
    room_id: UUID,
    access_session_id: UUID,
) -> tuple[UUID, UUID]:
    now = datetime.now(timezone.utc)
    campaign_id, session_id, dm_seat_id = uuid4(), uuid4(), uuid4()
    with engine.begin() as connection:
        connection.execute(insert(campaigns).values(
            id=campaign_id,
            room_id=room_id,
            name="HTTP Integration Campaign",
            ruleset="dnd5e-2014",
            status="active",
            created_at=now,
            updated_at=now,
        ))
        connection.execute(
            update(rooms)
            .where(rooms.c.id == room_id)
            .values(active_campaign_id=campaign_id, updated_at=now)
        )
        connection.execute(insert(campaign_seats).values(
            id=dm_seat_id,
            campaign_id=campaign_id,
            role="dm",
            label="HTTP DM",
            controller_kind="human",
            controller_access_session_id=access_session_id,
            selected_character_id=None,
            archived_at=None,
            created_at=now,
            updated_at=now,
        ))
        connection.execute(insert(sessions).values(
            id=session_id,
            campaign_id=campaign_id,
            status="active",
            dm_seat_id=dm_seat_id,
            dm_controller_kind="human",
            dm_controller_access_session_id=access_session_id,
            started_at=now,
            ended_at=None,
            created_at=now,
        ))
        connection.execute(insert(session_participants).values(
            id=uuid4(),
            session_id=session_id,
            seat_id=dm_seat_id,
            role_snapshot="dm",
            controller_kind_at_join="human",
            controller_access_session_id_at_join=access_session_id,
            active_character_id=None,
            joined_at=now,
            left_at=None,
        ))
    return campaign_id, session_id


def test_real_room_token_reaches_real_stage_action_and_event_services() -> None:
    engine = _engine()
    previous = _replace_app_state(engine)
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/rooms",
                json={
                    "name": "P3-B HTTP Integration",
                    "password": "p3b-http-password",
                    "display_name": "HTTP DM",
                },
            )
            assert created.status_code == 201
            grant = created.json()
            room_id = UUID(grant["room"]["id"])
            access_session_id = UUID(grant["access_session_id"])
            token = grant["access_token"]
            campaign_id, session_id = _seed_active_dm_session(
                engine,
                room_id=room_id,
                access_session_id=access_session_id,
            )
            headers = {"Authorization": f"Bearer {token}"}
            prefix = (
                f"/api/rooms/{room_id}/campaigns/{campaign_id}"
                f"/sessions/{session_id}"
            )

            stage = client.put(
                f"{prefix}/stage",
                headers=headers,
                json={
                    "expected_revision": 0,
                    "text": "Real HTTP Stage",
                    "idempotency_key": "http-stage",
                },
            )
            assert stage.status_code == 200
            assert stage.json()["revision"] == 1
            assert stage.json()["text"] == "Real HTTP Stage"

            ooc = client.post(
                f"{prefix}/exploration",
                headers=headers,
                json={
                    "kind": "ooc",
                    "text": "Real HTTP OOC",
                    "idempotency_key": "http-ooc",
                },
            )
            assert ooc.status_code == 200
            assert ooc.json()["kind"] == "exploration.ooc"
            assert ooc.json()["seq"] == 2

            loaded = client.get(f"{prefix}/stage", headers=headers)
            assert loaded.status_code == 200
            assert loaded.json()["text"] == "Real HTTP Stage"

            event_page = client.get(
                f"{prefix}/events",
                params={"after": 0, "limit": 20},
                headers=headers,
            )
            assert event_page.status_code == 200
            assert [event["kind"] for event in event_page.json()["events"]] == [
                "stage.updated",
                "exploration.ooc",
            ]
    finally:
        _restore_app_state(previous)
        engine.dispose()
