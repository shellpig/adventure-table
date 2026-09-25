from __future__ import annotations

from datetime import datetime, timezone
from typing import NamedTuple
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_table_event_service
from app.db import metadata
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEvent,
    TableEventAppend,
    TableEventService,
    TableEventVisibility,
)
from app.main import app
from app.persistence.characters import characters
from app.persistence.rooms.table_runtime import (
    TableEventRepository,
    session_events,
)
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    session_participants,
    sessions,
)


class M06bFixture(NamedTuple):
    engine: Engine
    service: TableEventService
    human_actor: TableActorContext
    ai_dm_actor: TableActorContext
    ai_player_actor: TableActorContext


def create_m06b_fixture() -> M06bFixture:
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

    human_access_id = uuid4()
    ai_dm_grant_id = uuid4()
    ai_player_grant_id = uuid4()

    dm_seat_id = uuid4()
    human_player_seat_id = uuid4()
    ai_player_seat_id = uuid4()

    player_character_id_1 = uuid4()
    player_character_id_2 = uuid4()

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code=f"R{str(uuid4())[:7]}",
                name="M06B Test Room",
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
                id=human_access_id,
                room_id=room_id,
                authority="member",
                token_hash=b"t" * 32,
                display_name="Human Player",
                created_at=now,
                last_seen_at=now,
            )
        )
        connection.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="M06B Test Campaign",
                ruleset="dnd5e-2014",
                status="active",
            )
        )
        connection.execute(
            update(rooms)
            .where(rooms.c.id == room_id)
            .values(active_campaign_id=campaign_id)
        )
        connection.execute(
            insert(characters),
            [
                {
                    "id": player_character_id_1,
                    "name": "Human Char",
                    "ruleset": "dnd5e-2014",
                    "current_version_id": None,
                    "archived_at": None,
                },
                {
                    "id": player_character_id_2,
                    "name": "AI Char",
                    "ruleset": "dnd5e-2014",
                    "current_version_id": None,
                    "archived_at": None,
                },
            ],
        )
        connection.execute(
            insert(campaign_seats),
            [
                {
                    "id": dm_seat_id,
                    "campaign_id": campaign_id,
                    "role": "dm",
                    "label": "AI DM",
                    "controller_kind": "none",
                    "controller_access_session_id": None,
                    "ai_controller_grant_id": None,
                    "controller_epoch": 1,
                    "selected_character_id": None,
                    "archived_at": None,
                },
                {
                    "id": human_player_seat_id,
                    "campaign_id": campaign_id,
                    "role": "player",
                    "label": "Human Player Seat",
                    "controller_kind": "human",
                    "controller_access_session_id": human_access_id,
                    "ai_controller_grant_id": None,
                    "controller_epoch": 1,
                    "selected_character_id": player_character_id_1,
                    "archived_at": None,
                },
                {
                    "id": ai_player_seat_id,
                    "campaign_id": campaign_id,
                    "role": "player",
                    "label": "AI Player Seat",
                    "controller_kind": "none",
                    "controller_access_session_id": None,
                    "ai_controller_grant_id": None,
                    "controller_epoch": 1,
                    "selected_character_id": player_character_id_2,
                    "archived_at": None,
                },
            ],
        )
        connection.execute(
            insert(sessions).values(
                id=session_id,
                campaign_id=campaign_id,
                status="active",
                dm_seat_id=dm_seat_id,
                dm_controller_kind="none",
                dm_controller_access_session_id=None,
                dm_controller_ai_grant_id=None,
                dm_controller_generation=None,
                started_at=now,
                ended_at=None,
            )
        )
        connection.execute(
            insert(session_participants),
            [
                {
                    "id": uuid4(),
                    "session_id": session_id,
                    "seat_id": human_player_seat_id,
                    "role_snapshot": "player",
                    "controller_kind_at_join": "human",
                    "controller_access_session_id_at_join": human_access_id,
                    "controller_ai_grant_id_at_join": None,
                    "controller_generation_at_join": None,
                    "active_character_id": player_character_id_1,
                    "joined_at": now,
                    "left_at": None,
                },
                {
                    "id": uuid4(),
                    "session_id": session_id,
                    "seat_id": ai_player_seat_id,
                    "role_snapshot": "player",
                    "controller_kind_at_join": "none",
                    "controller_access_session_id_at_join": None,
                    "controller_ai_grant_id_at_join": None,
                    "controller_generation_at_join": None,
                    "active_character_id": player_character_id_2,
                    "joined_at": now,
                    "left_at": None,
                },
            ],
        )
        connection.execute(
            insert(ai_controller_grants),
            [
                {
                    "id": ai_dm_grant_id,
                    "room_id": room_id,
                    "campaign_id": campaign_id,
                    "seat_id": dm_seat_id,
                    "role": "dm",
                    "session_id": session_id,
                    "secret_hash": b"s" * 32,
                    "secret_prefix": "aidm",
                    "generation": 1,
                    "status": "active",
                    "pre_session_expires_at": None,
                    "handoff_return_access_session_id": None,
                    "temporary_instruction": None,
                    "created_at": now,
                    "bound_at": now,
                    "revoked_at": None,
                    "last_seen_at": None,
                },
                {
                    "id": ai_player_grant_id,
                    "room_id": room_id,
                    "campaign_id": campaign_id,
                    "seat_id": ai_player_seat_id,
                    "role": "player",
                    "session_id": session_id,
                    "secret_hash": b"p" * 32,
                    "secret_prefix": "aipl",
                    "generation": 1,
                    "status": "active",
                    "pre_session_expires_at": None,
                    "handoff_return_access_session_id": human_access_id,
                    "temporary_instruction": None,
                    "created_at": now,
                    "bound_at": now,
                    "revoked_at": None,
                    "last_seen_at": None,
                },
            ],
        )
        connection.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == dm_seat_id)
            .values(
                controller_kind="ai",
                ai_controller_grant_id=ai_dm_grant_id,
            )
        )
        connection.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == ai_player_seat_id)
            .values(
                controller_kind="ai",
                ai_controller_grant_id=ai_player_grant_id,
            )
        )
        connection.execute(
            update(sessions)
            .where(sessions.c.id == session_id)
            .values(
                dm_controller_kind="ai",
                dm_controller_ai_grant_id=ai_dm_grant_id,
                dm_controller_generation=1,
            )
        )
        connection.execute(
            update(session_participants)
            .where(session_participants.c.seat_id == ai_player_seat_id)
            .values(
                controller_kind_at_join="ai",
                controller_ai_grant_id_at_join=ai_player_grant_id,
                controller_generation_at_join=1,
            )
        )

    service = TableEventService(TableEventRepository(engine))

    human_actor = service.resolve_human_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        context=RoomAccessContext(
            room_id=room_id,
            access_session_id=human_access_id,
            authority=RoomAccessAuthority.MEMBER,
            display_name="Human Player",
        ),
    )
    ai_dm_actor = service.resolve_ai_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        grant_id=ai_dm_grant_id,
        generation=1,
    )
    ai_player_actor = service.resolve_ai_actor(
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        grant_id=ai_player_grant_id,
        generation=1,
    )

    return M06bFixture(
        engine=engine,
        service=service,
        human_actor=human_actor,
        ai_dm_actor=ai_dm_actor,
        ai_player_actor=ai_player_actor,
    )


def test_ai_append_stamps_grant_and_generation() -> None:
    fix = create_m06b_fixture()

    event_dm = fix.service.append_event(
        fix.ai_dm_actor,
        TableEventAppend(
            kind="stage.updated",
            visibility=TableEventVisibility.PUBLIC,
            recipient_seat_ids=(),
            payload_version=1,
            payload={"text": "The goblin lair entrance is dark."},
        ),
    )

    with fix.engine.connect() as conn:
        row_dm = conn.execute(
            select(session_events).where(session_events.c.id == event_dm.id)
        ).mappings().one()

    assert row_dm["acting_ai_controller_grant_id"] == fix.ai_dm_actor.ai_controller_grant_id
    assert row_dm["acting_grant_generation"] == fix.ai_dm_actor.grant_generation

    stored_list = fix.service.repository.list_after(
        room_id=fix.ai_dm_actor.room_id,
        campaign_id=fix.ai_dm_actor.campaign_id,
        session_id=fix.ai_dm_actor.session_id,
        after_seq=0,
        scan_limit=10,
    )
    assert len(stored_list) == 1
    assert stored_list[0].acting_ai_controller_grant_id == fix.ai_dm_actor.ai_controller_grant_id
    assert stored_list[0].acting_grant_generation == fix.ai_dm_actor.grant_generation

    event_player = fix.service.append_event(
        fix.ai_player_actor,
        TableEventAppend(
            kind="exploration.action",
            visibility=TableEventVisibility.PUBLIC,
            recipient_seat_ids=(),
            payload_version=1,
            payload={"action": "I cast Light on my shield."},
        ),
    )

    with fix.engine.connect() as conn:
        row_player = conn.execute(
            select(session_events).where(session_events.c.id == event_player.id)
        ).mappings().one()

    assert row_player["acting_ai_controller_grant_id"] == fix.ai_player_actor.ai_controller_grant_id
    assert row_player["acting_grant_generation"] == fix.ai_player_actor.grant_generation

    stored_events = fix.service.repository.list_after(
        room_id=fix.ai_player_actor.room_id,
        campaign_id=fix.ai_player_actor.campaign_id,
        session_id=fix.ai_player_actor.session_id,
        after_seq=0,
        scan_limit=10,
    )
    assert len(stored_events) == 2
    assert stored_events[1].acting_ai_controller_grant_id == fix.ai_player_actor.ai_controller_grant_id
    assert stored_events[1].acting_grant_generation == fix.ai_player_actor.grant_generation


def test_human_append_leaves_stamp_null() -> None:
    fix = create_m06b_fixture()

    event = fix.service.append_event(
        fix.human_actor,
        TableEventAppend(
            kind="exploration.dialogue",
            visibility=TableEventVisibility.PUBLIC,
            recipient_seat_ids=(),
            payload_version=1,
            payload={"text": "Stay quiet, everyone."},
        ),
    )

    with fix.engine.connect() as conn:
        row = conn.execute(
            select(session_events).where(session_events.c.id == event.id)
        ).mappings().one()

    assert row["acting_ai_controller_grant_id"] is None
    assert row["acting_grant_generation"] is None

    stored = fix.service.repository.list_after(
        room_id=fix.human_actor.room_id,
        campaign_id=fix.human_actor.campaign_id,
        session_id=fix.human_actor.session_id,
        after_seq=0,
        scan_limit=10,
    )[0]
    assert stored.acting_ai_controller_grant_id is None
    assert stored.acting_grant_generation is None


def test_system_append_without_binding_leaves_stamp_null() -> None:
    fix = create_m06b_fixture()

    stored = fix.service.repository.append(
        room_id=fix.human_actor.room_id,
        campaign_id=fix.human_actor.campaign_id,
        session_id=fix.human_actor.session_id,
        kind="session.started",
        acting_seat_id=None,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="system",
        visibility="public",
        recipient_seat_ids=(),
        payload_version=1,
        payload={"note": "Session initialized by system"},
        idempotency_key=None,
        expected_actor_binding=None,
    )

    with fix.engine.connect() as conn:
        row = conn.execute(
            select(session_events).where(session_events.c.id == stored.id)
        ).mappings().one()

    assert row["acting_ai_controller_grant_id"] is None
    assert row["acting_grant_generation"] is None
    assert stored.acting_ai_controller_grant_id is None
    assert stored.acting_grant_generation is None


def test_idempotent_replay_returns_original_stamp() -> None:
    fix = create_m06b_fixture()
    key = "m06b-idempotent-test-key"

    request = TableEventAppend(
        kind="stage.updated",
        visibility=TableEventVisibility.PUBLIC,
        recipient_seat_ids=(),
        payload_version=1,
        payload={"text": "Scene description with idempotency key"},
        idempotency_key=key,
    )

    event_first = fix.service.append_event(fix.ai_dm_actor, request)
    event_replay = fix.service.append_event(fix.ai_dm_actor, request)

    assert event_first.id == event_replay.id
    assert event_first.seq == event_replay.seq

    with fix.engine.connect() as conn:
        rows = conn.execute(
            select(session_events).where(
                session_events.c.session_id == fix.ai_dm_actor.session_id
            )
        ).mappings().all()

    assert len(rows) == 1
    assert rows[0]["acting_ai_controller_grant_id"] == fix.ai_dm_actor.ai_controller_grant_id
    assert rows[0]["acting_grant_generation"] == fix.ai_dm_actor.grant_generation


def test_table_event_json_has_no_stamp_fields() -> None:
    assert "acting_ai_controller_grant_id" not in TableEvent.model_fields
    assert "acting_grant_generation" not in TableEvent.model_fields

    fix = create_m06b_fixture()

    event = fix.service.append_event(
        fix.ai_dm_actor,
        TableEventAppend(
            kind="stage.updated",
            visibility=TableEventVisibility.PUBLIC,
            recipient_seat_ids=(),
            payload_version=1,
            payload={"text": "A dark cave opens up before you."},
        ),
    )

    event_json = event.model_dump(mode="json")
    assert "acting_ai_controller_grant_id" not in event_json
    assert "acting_grant_generation" not in event_json

    page = fix.service.list_after(fix.ai_dm_actor, after_seq=0, limit=10)
    page_json = page.model_dump(mode="json")
    assert len(page_json["events"]) == 1
    assert "acting_ai_controller_grant_id" not in page_json["events"][0]
    assert "acting_grant_generation" not in page_json["events"][0]

    app.dependency_overrides[get_table_event_service] = lambda: fix.service
    app.dependency_overrides[get_room_access_context] = lambda: RoomAccessContext(
        room_id=fix.human_actor.room_id,
        access_session_id=fix.human_actor.access_session_id,
        authority=RoomAccessAuthority.MEMBER,
        display_name="Human Player",
    )
    try:
        client = TestClient(app)
        response = client.get(
            f"/api/rooms/{fix.human_actor.room_id}/campaigns/{fix.human_actor.campaign_id}/sessions/{fix.human_actor.session_id}/events?after=0&limit=10"
        )
        assert response.status_code == 200
        events_list = response.json()["events"]
        assert len(events_list) == 1
        for ev in events_list:
            assert "acting_ai_controller_grant_id" not in ev
            assert "acting_grant_generation" not in ev
    finally:
        app.dependency_overrides.pop(get_table_event_service, None)
        app.dependency_overrides.pop(get_room_access_context, None)
