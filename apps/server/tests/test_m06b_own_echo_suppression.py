from __future__ import annotations
 
import asyncio
from datetime import datetime, timezone
import time
from typing import NamedTuple
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_table_event_service
from app.api.rooms.table_event_wait import ProcessLocalTableEventNotifier
from app.db import metadata
from app.domain.rooms.ai_tools import AIToolApplicationService, WaitEventsInput
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEvent,
    TableEventAppend,
    TableEventNotifier,
    TableEventPage,
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


def create_m06b_fixture(
    notifier: TableEventNotifier | None = None,
) -> M06bFixture:
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

    service = TableEventService(TableEventRepository(engine), notifier=notifier)

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


def _append(
    fix: M06bFixture,
    actor: TableActorContext,
    kind: str,
    payload: dict[str, object],
) -> TableEvent:
    return fix.service.append_event(
        actor,
        TableEventAppend(kind=kind, visibility=TableEventVisibility.PUBLIC, payload=payload),
    )


def _regrant_dm_seat(
    fix: M06bFixture,
    *,
    new_grant_id: UUID,
    new_generation: int = 2,
) -> TableActorContext:
    now = datetime.now(timezone.utc)
    with fix.engine.begin() as conn:
        conn.execute(
            update(ai_controller_grants)
            .where(ai_controller_grants.c.id == fix.ai_dm_actor.ai_controller_grant_id)
            .values(status="revoked", revoked_at=now)
        )
        conn.execute(
            insert(ai_controller_grants).values(
                id=new_grant_id,
                room_id=fix.ai_dm_actor.room_id,
                campaign_id=fix.ai_dm_actor.campaign_id,
                seat_id=fix.ai_dm_actor.seat_id,
                role="dm",
                session_id=fix.ai_dm_actor.session_id,
                secret_hash=b"s2" * 16,
                secret_prefix="aidm2",
                generation=new_generation,
                status="active",
                pre_session_expires_at=None,
                handoff_return_access_session_id=None,
                temporary_instruction=None,
                created_at=now,
                bound_at=now,
                revoked_at=None,
                last_seen_at=None,
            )
        )
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == fix.ai_dm_actor.seat_id)
            .values(
                ai_controller_grant_id=new_grant_id,
                controller_epoch=new_generation,
            )
        )
        conn.execute(
            update(sessions)
            .where(sessions.c.id == fix.ai_dm_actor.session_id)
            .values(
                dm_controller_ai_grant_id=new_grant_id,
                dm_controller_generation=new_generation,
            )
        )
    return fix.service.resolve_ai_actor(
        room_id=fix.ai_dm_actor.room_id,
        campaign_id=fix.ai_dm_actor.campaign_id,
        session_id=fix.ai_dm_actor.session_id,
        grant_id=new_grant_id,
        generation=new_generation,
    )


def test_list_after_suppress_own_skips_ai_dm_echoes_and_advances_cursor() -> None:
    fix = create_m06b_fixture()

    _append(fix, fix.ai_dm_actor, "stage.updated", {"text": "The goblin lair entrance is dark."})
    _append(fix, fix.ai_dm_actor, "exploration.narration", {"text": "Water drips from stalactites above."})
    _append(fix, fix.ai_dm_actor, "world.entry.created", {"entry_id": "entry-1"})
    _append(fix, fix.ai_dm_actor, "world.context_changed", {"context": "active_scene"})
    e5 = _append(fix, fix.ai_dm_actor, "roll.requested", {"prompt": "Wisdom (Perception) DC 12"})

    page_suppressed = fix.service.list_after(
        fix.ai_dm_actor,
        after_seq=0,
        limit=10,
        suppress_own=True,
    )
    assert page_suppressed.events == []
    assert page_suppressed.cursor == e5.seq

    page_unsuppressed = fix.service.list_after(
        fix.ai_dm_actor,
        after_seq=0,
        limit=10,
        suppress_own=False,
    )
    assert len(page_unsuppressed.events) == 5
    assert [e.kind for e in page_unsuppressed.events] == [
        "stage.updated",
        "exploration.narration",
        "world.entry.created",
        "world.context_changed",
        "roll.requested",
    ]


def test_wait_suppress_own_keeps_waiting_past_own_echoes_until_timeout() -> None:
    notifier = ProcessLocalTableEventNotifier()
    fix = create_m06b_fixture(notifier=notifier)

    _append(fix, fix.ai_dm_actor, "stage.updated", {"text": "Stage text"})
    _append(fix, fix.ai_dm_actor, "exploration.narration", {"text": "Narration text"})
    _append(fix, fix.ai_dm_actor, "world.entry.created", {"entry_id": "e1"})
    _append(fix, fix.ai_dm_actor, "world.context_changed", {"context": "ctx"})
    e5 = _append(fix, fix.ai_dm_actor, "roll.requested", {"prompt": "Perception check"})

    start = time.perf_counter()
    page = asyncio.run(
        fix.service.wait_after(
            fix.ai_dm_actor,
            after_seq=0,
            limit=10,
            timeout=0.2,
            max_timeout=120.0,
            suppress_own=True,
        )
    )
    elapsed = time.perf_counter() - start

    assert page.events == []
    assert page.cursor == e5.seq
    assert elapsed >= 0.15


def test_wait_suppress_own_wakes_on_player_dialogue_after_own_echoes() -> None:
    notifier = ProcessLocalTableEventNotifier()
    fix = create_m06b_fixture(notifier=notifier)

    _append(fix, fix.ai_dm_actor, "stage.updated", {"text": "Stage text"})
    _append(fix, fix.ai_dm_actor, "exploration.narration", {"text": "Narration text"})

    async def delayed_player_write() -> None:
        await asyncio.sleep(0.08)
        await asyncio.to_thread(
            fix.service.append_event,
            fix.human_actor,
            TableEventAppend(
                kind="exploration.dialogue",
                visibility=TableEventVisibility.PUBLIC,
                payload={"text": "I ready my sword."},
            ),
        )

    async def run_wait() -> tuple[TableEventPage, float]:
        task = asyncio.create_task(delayed_player_write())
        start = time.perf_counter()
        page = await fix.service.wait_after(
            fix.ai_dm_actor,
            after_seq=0,
            limit=10,
            timeout=2.0,
            max_timeout=120.0,
            suppress_own=True,
        )
        elapsed = time.perf_counter() - start
        await task
        return page, elapsed

    page, elapsed = asyncio.run(run_wait())

    assert len(page.events) == 1
    assert page.events[0].kind == "exploration.dialogue"
    assert page.events[0].payload["text"] == "I ready my sword."
    assert page.cursor == 3
    assert elapsed < 1.0


def test_other_actor_events_are_returned() -> None:
    fix = create_m06b_fixture()

    _append(fix, fix.human_actor, "exploration.dialogue", {"text": "Human dialogue"})
    _append(fix, fix.ai_player_actor, "exploration.dialogue", {"text": "AI player dialogue"})
    _append(fix, fix.human_actor, "roll.resolved", {"total": 17})

    page = fix.service.list_after(
        fix.ai_dm_actor,
        after_seq=0,
        limit=10,
        suppress_own=True,
    )

    assert len(page.events) == 3
    assert [e.kind for e in page.events] == [
        "exploration.dialogue",
        "exploration.dialogue",
        "roll.resolved",
    ]


def test_non_whitelisted_own_events_are_returned() -> None:
    fix = create_m06b_fixture()

    binding = TableEventService._stored_binding(fix.ai_dm_actor)
    kinds_and_payloads = [
        ("combat.started", {"combat_id": str(uuid4())}),
        ("roll.requested", {"combat_id": str(uuid4()), "prompt": "Attack roll"}),
        ("roll.resolved", {"combat_id": str(uuid4()), "total": 19}),
        ("pending_action.created", {"action_id": str(uuid4())}),
        ("controller.changed", {"to": "new_controller"}),
        ("session.started", {"mode": "adventure"}),
    ]

    for kind, payload in kinds_and_payloads:
        fix.service.repository.append(
            room_id=fix.ai_dm_actor.room_id,
            campaign_id=fix.ai_dm_actor.campaign_id,
            session_id=fix.ai_dm_actor.session_id,
            kind=kind,
            acting_seat_id=fix.ai_dm_actor.seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode="self",
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload=payload,
            idempotency_key=None,
            expected_actor_binding=binding,
        )

    page = fix.service.list_after(
        fix.ai_dm_actor,
        after_seq=0,
        limit=10,
        suppress_own=True,
    )

    assert len(page.events) == 6
    assert [e.kind for e in page.events] == [k for k, _ in kinds_and_payloads]


def test_include_own_equivalent_to_unsuppressed() -> None:
    fix = create_m06b_fixture()

    _append(fix, fix.ai_dm_actor, "stage.updated", {"text": "Scene text"})
    _append(fix, fix.ai_dm_actor, "exploration.narration", {"text": "Narration text"})

    page_unsuppressed = asyncio.run(
        fix.service.wait_after(
            fix.ai_dm_actor,
            after_seq=0,
            limit=10,
            timeout=1.0,
            suppress_own=False,
        )
    )
    assert len(page_unsuppressed.events) == 2

    recorded_suppress_own: list[bool] = []

    class _SpyEventService:
        async def wait_after(
            self,
            actor: TableActorContext,
            *,
            after_seq: int,
            limit: int,
            timeout: float,
            max_timeout: float = 60.0,
            suppress_own: bool = False,
        ) -> TableEventPage:
            del timeout, max_timeout
            recorded_suppress_own.append(suppress_own)
            return TableEventPage(
                session_id=actor.session_id,
                after_seq=after_seq,
                cursor=after_seq,
                current_seq=after_seq,
                has_more=False,
                events=[],
            )

    class _StaticAIControllerService:
        def __init__(self, actor: TableActorContext) -> None:
            self.actor = actor

        def resolve_actor(self, token: str, *, touch: bool = True) -> TableActorContext:
            del token, touch
            return self.actor

    facade = AIToolApplicationService(
        ai_controller_service=_StaticAIControllerService(fix.ai_dm_actor),  # type: ignore[arg-type]
        session_service=None,  # type: ignore[arg-type]
        stage_service=None,  # type: ignore[arg-type]
        action_service=None,  # type: ignore[arg-type]
        roll_service=None,  # type: ignore[arg-type]
        state_service=None,  # type: ignore[arg-type]
        pending_action_service=None,  # type: ignore[arg-type]
        event_service=_SpyEventService(),  # type: ignore[arg-type]
        workspace_service=None,  # type: ignore[arg-type]
    )

    asyncio.run(
        facade.wait_for_event("fake-token", WaitEventsInput(include_own=True))
    )
    assert recorded_suppress_own == [False]

    asyncio.run(
        facade.wait_for_event("fake-token", WaitEventsInput())
    )
    assert recorded_suppress_own == [False, True]


def test_human_and_pending_paths_unchanged() -> None:
    fix = create_m06b_fixture()

    _append(fix, fix.ai_dm_actor, "stage.updated", {"text": "Scene text"})
    _append(fix, fix.ai_dm_actor, "exploration.narration", {"text": "Narration text"})

    human_page = fix.service.list_after(fix.human_actor, after_seq=0, limit=10)
    assert len(human_page.events) == 2

    ai_page = fix.service.list_after(fix.ai_dm_actor, after_seq=0, limit=10)
    assert len(ai_page.events) == 2

    human_wait_page = asyncio.run(
        fix.service.wait_after(fix.human_actor, after_seq=0, limit=10, timeout=1.0)
    )
    assert len(human_wait_page.events) == 2


def test_previous_controller_echoes_not_own_after_regrant() -> None:
    fix = create_m06b_fixture()

    e1 = _append(fix, fix.ai_dm_actor, "stage.updated", {"text": "Scene described by G1"})

    g2_id = uuid4()
    g2_actor = _regrant_dm_seat(fix, new_grant_id=g2_id, new_generation=2)

    page_g2 = fix.service.list_after(
        g2_actor,
        after_seq=0,
        limit=10,
        suppress_own=True,
    )
    assert len(page_g2.events) == 1
    assert page_g2.events[0].id == e1.id
    assert page_g2.events[0].kind == "stage.updated"

    e2 = _append(fix, g2_actor, "exploration.narration", {"text": "Narration by G2"})

    page_g2_after = fix.service.list_after(
        g2_actor,
        after_seq=page_g2.cursor,
        limit=10,
        suppress_own=True,
    )
    assert page_g2_after.events == []
    assert page_g2_after.cursor == e2.seq


def test_human_dm_writes_never_own_for_ai() -> None:
    fix = create_m06b_fixture()

    # The fixture's Human actor is a player. We append exploration.dialogue
    # from the human player actor, and stage.updated via repository with human binding.
    _append(fix, fix.human_actor, "exploration.dialogue", {"text": "Let us proceed through the door."})
    fix.service.repository.append(
        room_id=fix.human_actor.room_id,
        campaign_id=fix.human_actor.campaign_id,
        session_id=fix.human_actor.session_id,
        kind="stage.updated",
        acting_seat_id=fix.human_actor.seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="self",
        visibility="public",
        recipient_seat_ids=(),
        payload_version=1,
        payload={"text": "Human-updated stage text"},
        idempotency_key=None,
        expected_actor_binding=TableEventService._stored_binding(fix.human_actor),
    )

    dm_page = fix.service.list_after(
        fix.ai_dm_actor,
        after_seq=0,
        limit=10,
        suppress_own=True,
    )
    assert len(dm_page.events) == 2
    assert [e.kind for e in dm_page.events] == ["exploration.dialogue", "stage.updated"]

    player_page = fix.service.list_after(
        fix.ai_player_actor,
        after_seq=0,
        limit=10,
        suppress_own=True,
    )
    assert len(player_page.events) == 2
    assert [e.kind for e in player_page.events] == ["exploration.dialogue", "stage.updated"]


def test_legacy_null_stamp_events_are_returned() -> None:
    fix = create_m06b_fixture()

    stored = fix.service.repository.append(
        room_id=fix.ai_dm_actor.room_id,
        campaign_id=fix.ai_dm_actor.campaign_id,
        session_id=fix.ai_dm_actor.session_id,
        kind="stage.updated",
        acting_seat_id=fix.ai_dm_actor.seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="self",
        visibility="public",
        recipient_seat_ids=(),
        payload_version=1,
        payload={"text": "Pre-M06 legacy scene description"},
        idempotency_key=None,
        expected_actor_binding=None,
    )
    assert stored.acting_ai_controller_grant_id is None
    assert stored.acting_grant_generation is None

    page = fix.service.list_after(fix.ai_dm_actor, after_seq=0, limit=10, suppress_own=True)
    assert len(page.events) == 1
    assert page.events[0].id == stored.id
    assert page.events[0].kind == "stage.updated"


def test_player_visibility_unchanged_by_suppression() -> None:
    fix = create_m06b_fixture()

    fix.service.append_event(
        fix.ai_dm_actor,
        TableEventAppend(
            kind="stage.updated",
            visibility=TableEventVisibility.DM_ONLY,
            payload={"secret_note": "A hidden door is behind the altar."},
        ),
    )
    _append(fix, fix.ai_dm_actor, "exploration.narration", {"text": "You enter the stone chapel."})

    page_suppressed = fix.service.list_after(
        fix.ai_player_actor,
        after_seq=0,
        limit=10,
        suppress_own=True,
    )
    page_unsuppressed = fix.service.list_after(
        fix.ai_player_actor,
        after_seq=0,
        limit=10,
        suppress_own=False,
    )

    assert [e.kind for e in page_suppressed.events] == ["exploration.narration"]
    assert [e.kind for e in page_unsuppressed.events] == ["exploration.narration"]
    assert page_suppressed.events == page_unsuppressed.events
    assert page_suppressed.cursor == 2
    assert page_unsuppressed.cursor == 2
