from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, insert, select, update

from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.rooms.table_runtime import session_events
from app.persistence.rooms.tables import (
    campaign_seats,
    campaigns,
    rooms,
    sessions,
)
from tests.test_m05b_history_reader_scope import M05BFixture, m05b_fixture


def test_previous_session_returns_latest_earlier_session_any_status(m05b_fixture: M05BFixture) -> None:
    fixture = m05b_fixture
    now = datetime.now(timezone.utc)
    campaign_id = uuid4()
    dm_seat_id = uuid4()

    with fixture.engine.begin() as conn:
        conn.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=fixture.room_id,
                name="T1 Campaign",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            update(rooms)
            .where(rooms.c.id == fixture.room_id)
            .values(active_campaign_id=campaign_id)
        )
        conn.execute(
            insert(campaign_seats).values(
                id=dm_seat_id,
                campaign_id=campaign_id,
                role="dm",
                label="DM Seat",
                controller_kind="human",
                controller_access_session_id=fixture.h_dm_access_id,
                controller_epoch=0,
                created_at=now,
                updated_at=now,
            )
        )

    h_dm_context = RoomAccessContext(
        room_id=fixture.room_id,
        access_session_id=fixture.h_dm_access_id,
        authority=RoomAccessAuthority.DM,
    )

    # s1: started, then abandoned
    s1 = fixture.session_service.start_session(fixture.room_id, campaign_id, h_dm_context)
    fixture.session_service.abandon_session(fixture.room_id, campaign_id, s1.id, h_dm_context)

    # s2: started, event appended, then ended
    s2 = fixture.session_service.start_session(fixture.room_id, campaign_id, h_dm_context)
    fixture.event_service.repository.append(
        room_id=fixture.room_id,
        campaign_id=campaign_id,
        session_id=s2.id,
        kind="exploration.narration",
        acting_seat_id=dm_seat_id,
        subject_seat_id=None,
        subject_character_id=None,
        execution_mode="self",
        visibility="public",
        recipient_seat_ids=(),
        payload_version=1,
        payload={"text": "s2 narration"},
        idempotency_key="s2-narr",
    )
    fixture.session_service.end_session(fixture.room_id, campaign_id, s2.id, h_dm_context)

    # s3: active
    s3 = fixture.session_service.start_session(fixture.room_id, campaign_id, h_dm_context)

    # Enforce strictly ascending started_at
    with fixture.engine.begin() as conn:
        conn.execute(
            update(sessions)
            .where(sessions.c.id == s1.id)
            .values(started_at=now)
        )
        conn.execute(
            update(sessions)
            .where(sessions.c.id == s2.id)
            .values(started_at=now + timedelta(seconds=10))
        )
        conn.execute(
            update(sessions)
            .where(sessions.c.id == s3.id)
            .values(started_at=now + timedelta(seconds=20))
        )

    # GET /sessions/{s3}/previous -> previous_session.id == s2 and previous_last_event_seq == s2's last_event_seq (> 0)
    res_s3 = fixture.client.get(
        f"/api/rooms/{fixture.room_id}/campaigns/{campaign_id}/sessions/{s3.id}/previous",
        headers={"Authorization": f"Bearer {fixture.tokens['h_dm']}"},
    )
    assert res_s3.status_code == 200
    data_s3 = res_s3.json()
    assert data_s3["session_id"] == str(s3.id)
    assert data_s3["previous_session"] is not None
    assert data_s3["previous_session"]["id"] == str(s2.id)
    assert data_s3["previous_session"]["status"] == "ended"
    s2_runtime = fixture.event_service.repository.current_runtime(
        room_id=fixture.room_id,
        campaign_id=campaign_id,
        session_id=s2.id,
    )
    assert data_s3["previous_last_event_seq"] == s2_runtime.last_event_seq
    assert data_s3["previous_last_event_seq"] > 0

    # GET /sessions/{s2}/previous -> s1 (status "abandoned")
    res_s2 = fixture.client.get(
        f"/api/rooms/{fixture.room_id}/campaigns/{campaign_id}/sessions/{s2.id}/previous",
        headers={"Authorization": f"Bearer {fixture.tokens['h_dm']}"},
    )
    assert res_s2.status_code == 200
    data_s2 = res_s2.json()
    assert data_s2["session_id"] == str(s2.id)
    assert data_s2["previous_session"] is not None
    assert data_s2["previous_session"]["id"] == str(s1.id)
    assert data_s2["previous_session"]["status"] == "abandoned"

    # GET /sessions/{s1}/previous -> previous_session is None and previous_last_event_seq == 0
    res_s1 = fixture.client.get(
        f"/api/rooms/{fixture.room_id}/campaigns/{campaign_id}/sessions/{s1.id}/previous",
        headers={"Authorization": f"Bearer {fixture.tokens['h_dm']}"},
    )
    assert res_s1.status_code == 200
    data_s1 = res_s1.json()
    assert data_s1["session_id"] == str(s1.id)
    assert data_s1["previous_session"] is None
    assert data_s1["previous_last_event_seq"] == 0


def test_previous_session_orders_by_started_at_then_id(m05b_fixture: M05BFixture) -> None:
    fixture = m05b_fixture
    now = datetime.now(timezone.utc)
    campaign_id = uuid4()
    dm_seat_id = uuid4()

    with fixture.engine.begin() as conn:
        conn.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=fixture.room_id,
                name="T2 Campaign",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            update(rooms)
            .where(rooms.c.id == fixture.room_id)
            .values(active_campaign_id=campaign_id)
        )
        conn.execute(
            insert(campaign_seats).values(
                id=dm_seat_id,
                campaign_id=campaign_id,
                role="dm",
                label="DM Seat",
                controller_kind="human",
                controller_access_session_id=fixture.h_dm_access_id,
                controller_epoch=0,
                created_at=now,
                updated_at=now,
            )
        )

    h_dm_context = RoomAccessContext(
        room_id=fixture.room_id,
        access_session_id=fixture.h_dm_access_id,
        authority=RoomAccessAuthority.DM,
    )

    s_a = fixture.session_service.start_session(fixture.room_id, campaign_id, h_dm_context)
    fixture.session_service.end_session(fixture.room_id, campaign_id, s_a.id, h_dm_context)
    s_b = fixture.session_service.start_session(fixture.room_id, campaign_id, h_dm_context)

    # Set identical started_at for both sessions
    same_time = datetime(2026, 9, 20, 10, 0, 0, tzinfo=timezone.utc)
    with fixture.engine.begin() as conn:
        conn.execute(
            update(sessions)
            .where(sessions.c.id.in_([s_a.id, s_b.id]))
            .values(started_at=same_time)
        )

    earlier, later = sorted([s_a, s_b], key=lambda s: s.id)

    res_later = fixture.client.get(
        f"/api/rooms/{fixture.room_id}/campaigns/{campaign_id}/sessions/{later.id}/previous",
        headers={"Authorization": f"Bearer {fixture.tokens['h_dm']}"},
    )
    assert res_later.status_code == 200
    data_later = res_later.json()
    assert data_later["session_id"] == str(later.id)
    assert data_later["previous_session"] is not None
    assert data_later["previous_session"]["id"] == str(earlier.id)

    res_earlier = fixture.client.get(
        f"/api/rooms/{fixture.room_id}/campaigns/{campaign_id}/sessions/{earlier.id}/previous",
        headers={"Authorization": f"Bearer {fixture.tokens['h_dm']}"},
    )
    assert res_earlier.status_code == 200
    data_earlier = res_earlier.json()
    assert data_earlier["session_id"] == str(earlier.id)
    assert data_earlier["previous_session"] is None
    assert data_earlier["previous_last_event_seq"] == 0


def test_previous_session_rejects_cross_campaign_and_cross_room(m05b_fixture: M05BFixture) -> None:
    fixture = m05b_fixture
    now = datetime.now(timezone.utc)

    # Another campaign in the same room
    other_campaign_id = uuid4()
    other_session_id = uuid4()
    dm_seat_other = uuid4()
    with fixture.engine.begin() as conn:
        conn.execute(
            insert(campaigns).values(
                id=other_campaign_id,
                room_id=fixture.room_id,
                name="Other Campaign",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaign_seats).values(
                id=dm_seat_other,
                campaign_id=other_campaign_id,
                role="dm",
                label="DM Other",
                controller_kind="none",
                controller_access_session_id=None,
                ai_controller_grant_id=None,
                controller_epoch=0,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(sessions).values(
                id=other_session_id,
                campaign_id=other_campaign_id,
                status="active",
                dm_seat_id=dm_seat_other,
                dm_controller_kind="none",
                started_at=now,
                ended_at=None,
            )
        )

    # Another room
    other_room_id = uuid4()
    other_room_campaign_id = uuid4()
    other_room_session_id = uuid4()
    other_room_dm_seat = uuid4()
    with fixture.engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                id=other_room_id,
                code="OTHR",
                name="Other Room",
                password_salt=b"s" * 32,
                password_hash=b"h" * 64,
                owner_key_hash=b"o" * 32,
                dm_key_hash=b"d" * 32,
                active_campaign_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaigns).values(
                id=other_room_campaign_id,
                room_id=other_room_id,
                name="Other Room Campaign",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            update(rooms)
            .where(rooms.c.id == other_room_id)
            .values(active_campaign_id=other_room_campaign_id)
        )
        conn.execute(
            insert(campaign_seats).values(
                id=other_room_dm_seat,
                campaign_id=other_room_campaign_id,
                role="dm",
                label="DM Other Room",
                controller_kind="none",
                controller_access_session_id=None,
                ai_controller_grant_id=None,
                controller_epoch=0,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(sessions).values(
                id=other_room_session_id,
                campaign_id=other_room_campaign_id,
                status="active",
                dm_seat_id=other_room_dm_seat,
                dm_controller_kind="none",
                started_at=now,
                ended_at=None,
            )
        )

    # Count rows before
    with fixture.engine.connect() as conn:
        sessions_count_before = conn.scalar(select(func.count()).select_from(sessions))
        events_count_before = conn.scalar(select(func.count()).select_from(session_events))

    # Cross-campaign in same room -> 404 session_not_found
    res_cc = fixture.client.get(
        f"/api/rooms/{fixture.room_id}/campaigns/{fixture.campaign_id}/sessions/{other_session_id}/previous",
        headers={"Authorization": f"Bearer {fixture.tokens['h1']}"},
    )
    assert res_cc.status_code == 404
    assert res_cc.json()["error"]["code"] == "session_not_found"

    # Cross-room -> 404 session_not_found
    res_cr = fixture.client.get(
        f"/api/rooms/{fixture.room_id}/campaigns/{fixture.campaign_id}/sessions/{other_room_session_id}/previous",
        headers={"Authorization": f"Bearer {fixture.tokens['h1']}"},
    )
    assert res_cr.status_code == 404
    assert res_cr.json()["error"]["code"] == "session_not_found"

    # Zero writes
    with fixture.engine.connect() as conn:
        sessions_count_after = conn.scalar(select(func.count()).select_from(sessions))
        events_count_after = conn.scalar(select(func.count()).select_from(session_events))
    assert sessions_count_before == sessions_count_after
    assert events_count_before == events_count_after


def test_previous_session_requires_history_scope_returns_404(m05b_fixture: M05BFixture) -> None:
    fixture = m05b_fixture
    with fixture.engine.connect() as conn:
        sessions_count_before = conn.scalar(select(func.count()).select_from(sessions))
        events_count_before = conn.scalar(select(func.count()).select_from(session_events))

    # Member controlling no seat -> 404 session_not_found (NOT 403)
    res_no_seat = fixture.client.get(
        f"/api/rooms/{fixture.room_id}/campaigns/{fixture.campaign_id}/sessions/{fixture.s2_id}/previous",
        headers={"Authorization": f"Bearer {fixture.tokens['h_no_seat']}"},
    )
    assert res_no_seat.status_code == 404
    assert res_no_seat.json()["error"]["code"] == "session_not_found"

    # Member controlling only archived seat -> 404 session_not_found (NOT 403)
    res_archived = fixture.client.get(
        f"/api/rooms/{fixture.room_id}/campaigns/{fixture.campaign_id}/sessions/{fixture.s2_id}/previous",
        headers={"Authorization": f"Bearer {fixture.tokens['h_archived']}"},
    )
    assert res_archived.status_code == 404
    assert res_archived.json()["error"]["code"] == "session_not_found"

    # Zero writes
    with fixture.engine.connect() as conn:
        sessions_count_after = conn.scalar(select(func.count()).select_from(sessions))
        events_count_after = conn.scalar(select(func.count()).select_from(session_events))
    assert sessions_count_before == sessions_count_after
    assert events_count_before == events_count_after


def test_previous_session_allows_seat_holder_not_in_base_session(m05b_fixture: M05BFixture) -> None:
    fixture = m05b_fixture
    # Verify P3 is not in s2 participants
    s2_snapshot = fixture.session_service.get_session(fixture.room_id, fixture.campaign_id, fixture.s2_id)
    participant_seat_ids = {p.seat_id for p in s2_snapshot.participants}
    assert fixture.p3_seat_id not in participant_seat_ids

    # H3 controls P3 -> 200 and points at s1
    res = fixture.client.get(
        f"/api/rooms/{fixture.room_id}/campaigns/{fixture.campaign_id}/sessions/{fixture.s2_id}/previous",
        headers={"Authorization": f"Bearer {fixture.tokens['h3']}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == str(fixture.s2_id)
    assert data["previous_session"] is not None
    assert data["previous_session"]["id"] == str(fixture.s1_id)
    s1_runtime = fixture.event_service.repository.current_runtime(
        room_id=fixture.room_id,
        campaign_id=fixture.campaign_id,
        session_id=fixture.s1_id,
    )
    assert data["previous_last_event_seq"] == s1_runtime.last_event_seq
    assert data["previous_last_event_seq"] > 0


def test_resume_recent_events_and_mcp_context_stay_single_session(m05b_fixture: M05BFixture) -> None:
    fixture = m05b_fixture
    # GET /sessions/active for a Seat holder (H1)
    res = fixture.client.get(
        f"/api/rooms/{fixture.room_id}/campaigns/{fixture.campaign_id}/sessions/active",
        headers={"Authorization": f"Bearer {fixture.tokens['h1']}"},
    )
    assert res.status_code == 200
    data = res.json()
    recent_events = data["recent_events"]
    assert recent_events is not None
    assert recent_events["session_id"] == str(fixture.s2_id)
    assert len(recent_events["events"]) > 0
    for event in recent_events["events"]:
        assert event["session_id"] == str(fixture.s2_id)

    # MCP get_session_context window path: assert on the domain method that builds its window (ai_tools.py)
    h_dm_context = RoomAccessContext(
        room_id=fixture.room_id,
        access_session_id=fixture.h_dm_access_id,
        authority=RoomAccessAuthority.DM,
    )
    actor_s2 = fixture.event_service.resolve_human_actor(
        room_id=fixture.room_id,
        campaign_id=fixture.campaign_id,
        session_id=fixture.s2_id,
        context=h_dm_context,
    )
    cursor = fixture.event_service.current_cursor(actor_s2)
    mcp_window = fixture.event_service.list_before(
        actor_s2,
        before_seq=cursor.last_event_seq + 1,
        limit=50,
    )
    assert mcp_window.session_id == fixture.s2_id
    assert len(mcp_window.events) > 0
    for event in mcp_window.events:
        assert event.session_id == fixture.s2_id
