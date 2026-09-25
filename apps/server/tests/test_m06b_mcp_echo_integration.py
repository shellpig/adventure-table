from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_content_registry, get_database_engine
from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.rooms.access import generate_secret, hash_secret
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.main import app
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    campaign_adventure_links,
)
from app.persistence.characters import (
    character_states,
    character_versions,
    characters,
)
from app.persistence.combat.tables import combat_entries
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    room_characters,
    rooms,
    session_participants,
    sessions,
)
from tests.test_p4e_mcp_combat_lifecycle import _mcp_call

_CONTENT_REGISTRY = load_default_content_registry()

# Cached per-app services / engines must be rebuilt against this test's engine;
# anything another test left behind would point at a different database.
_CACHED_STATE_SUFFIXES = ("_service", "_repository", "_notifier", "_engine", "_throttle")


@dataclass(frozen=True)
class IntegrationFixture:
    engine: Engine
    client: TestClient
    room_id: UUID
    campaign_id: UUID
    session_id: UUID
    ai_dm_token: str
    ai_dm_grant_id: UUID
    ai_player_token: str
    ai_player_grant_id: UUID
    human_token: str
    human_access_id: UUID
    dm_seat_id: UUID
    human_seat_id: UUID
    ai_player_seat_id: UUID
    human_char_id: UUID
    ai_char_id: UUID
    adv_entry_id: UUID


def _create_sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


@pytest.fixture
def integration_fixture():
    engine = _create_sqlite_engine()
    now = datetime.now(timezone.utc)
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()

    human_access_id = uuid4()
    human_token = generate_secret()

    ai_dm_minted = mint_ai_controller_token()
    ai_player_minted = mint_ai_controller_token()

    dm_seat_id = uuid4()
    human_seat_id = uuid4()
    ai_player_seat_id = uuid4()

    human_char_id = uuid4()
    ai_char_id = uuid4()
    human_version_id = uuid4()
    ai_version_id = uuid4()

    adv_def_id = uuid4()
    adv_entry_id = uuid4()

    build_payload = build_p0_fighter_wizard_fixture().model_dump(mode="json")
    state_payload = build_p0_fighter_wizard_state().model_dump(mode="json")

    with engine.begin() as conn:
        conn.execute(
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
        conn.execute(
            insert(room_access_sessions).values(
                id=human_access_id,
                room_id=room_id,
                authority="member",
                token_hash=hash_secret(human_token),
                display_name="Human Player",
                created_at=now,
                last_seen_at=now,
            )
        )
        conn.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="M06B Test Campaign",
                ruleset="dnd5e-2014",
                status="active",
            )
        )
        conn.execute(
            update(rooms)
            .where(rooms.c.id == room_id)
            .values(active_campaign_id=campaign_id)
        )
        for cid, vid, cname in (
            (human_char_id, human_version_id, "Human Char"),
            (ai_char_id, ai_version_id, "AI Char"),
        ):
            conn.execute(
                insert(characters).values(
                    id=cid,
                    name=cname,
                    ruleset="dnd5e-2014",
                    current_version_id=vid,
                    created_at=now,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(character_versions).values(
                    id=vid,
                    character_id=cid,
                    version_no=1,
                    build_payload=build_payload,
                    created_at=now,
                )
            )
            conn.execute(
                insert(character_states).values(
                    character_id=cid,
                    state_revision=1,
                    state_payload=state_payload,
                    updated_at=now,
                )
            )
            conn.execute(
                insert(room_characters).values(
                    room_id=room_id,
                    character_id=cid,
                    created_at=now,
                )
            )

        conn.execute(
            insert(campaign_seats).values(
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
                        "id": human_seat_id,
                        "campaign_id": campaign_id,
                        "role": "player",
                        "label": "Human Player Seat",
                        "controller_kind": "human",
                        "controller_access_session_id": human_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "selected_character_id": human_char_id,
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
                        "selected_character_id": ai_char_id,
                        "archived_at": None,
                    },
                ]
            )
        )
        conn.execute(
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
        conn.execute(
            insert(session_participants).values(
                [
                    {
                        "id": uuid4(),
                        "session_id": session_id,
                        "seat_id": human_seat_id,
                        "role_snapshot": "player",
                        "controller_kind_at_join": "human",
                        "controller_access_session_id_at_join": human_access_id,
                        "controller_ai_grant_id_at_join": None,
                        "controller_generation_at_join": None,
                        "active_character_id": human_char_id,
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
                        "active_character_id": ai_char_id,
                        "joined_at": now,
                        "left_at": None,
                    },
                ]
            )
        )
        conn.execute(
            insert(ai_controller_grants).values(
                [
                    {
                        "id": ai_dm_minted.grant_id,
                        "room_id": room_id,
                        "campaign_id": campaign_id,
                        "seat_id": dm_seat_id,
                        "role": "dm",
                        "session_id": session_id,
                        "secret_hash": ai_dm_minted.secret_hash,
                        "secret_prefix": ai_dm_minted.display_hint,
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
                        "id": ai_player_minted.grant_id,
                        "room_id": room_id,
                        "campaign_id": campaign_id,
                        "seat_id": ai_player_seat_id,
                        "role": "player",
                        "session_id": session_id,
                        "secret_hash": ai_player_minted.secret_hash,
                        "secret_prefix": ai_player_minted.display_hint,
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
                ]
            )
        )
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == dm_seat_id)
            .values(
                controller_kind="ai",
                ai_controller_grant_id=ai_dm_minted.grant_id,
            )
        )
        conn.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == ai_player_seat_id)
            .values(
                controller_kind="ai",
                ai_controller_grant_id=ai_player_minted.grant_id,
            )
        )
        conn.execute(
            update(sessions)
            .where(sessions.c.id == session_id)
            .values(
                dm_controller_kind="ai",
                dm_controller_ai_grant_id=ai_dm_minted.grant_id,
                dm_controller_generation=1,
            )
        )
        conn.execute(
            update(session_participants)
            .where(session_participants.c.seat_id == ai_player_seat_id)
            .values(
                controller_kind_at_join="ai",
                controller_ai_grant_id_at_join=ai_player_minted.grant_id,
                controller_generation_at_join=1,
            )
        )
        conn.execute(
            insert(adventure_definitions).values(
                id=adv_def_id,
                room_id=room_id,
                name="Test Adventure",
                ruleset="dnd5e-2014",
                status="finalized",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(adventure_entries).values(
                id=adv_entry_id,
                adventure_id=adv_def_id,
                kind="scene",
                title="Adventure Scene",
                data_json={},
                visibility="public",
                sort_order=0,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaign_adventure_links).values(
                campaign_id=campaign_id,
                adventure_id=adv_def_id,
                sort_order=0,
                attached_at=now,
            )
        )

    saved_state = dict(app.state._state)
    saved_overrides = dict(app.dependency_overrides)
    for key in [key for key in app.state._state if key.endswith(_CACHED_STATE_SUFFIXES)]:
        del app.state._state[key]

    app.state.character_engine = engine
    app.state.content_registry = _CONTENT_REGISTRY
    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_content_registry] = lambda: _CONTENT_REGISTRY

    client = TestClient(app)
    fixture_ctx = IntegrationFixture(
        engine=engine,
        client=client,
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        ai_dm_token=ai_dm_minted.plaintext,
        ai_dm_grant_id=ai_dm_minted.grant_id,
        ai_player_token=ai_player_minted.plaintext,
        ai_player_grant_id=ai_player_minted.grant_id,
        human_token=human_token,
        human_access_id=human_access_id,
        dm_seat_id=dm_seat_id,
        human_seat_id=human_seat_id,
        ai_player_seat_id=ai_player_seat_id,
        human_char_id=human_char_id,
        ai_char_id=ai_char_id,
        adv_entry_id=adv_entry_id,
    )

    try:
        yield fixture_ctx
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved_overrides)
        app.state._state.clear()
        app.state._state.update(saved_state)
        engine.dispose()


def _execute_dm_echo_writes(fix: IntegrationFixture) -> None:
    _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "set_stage_text",
        {"text": "A dark cave opens before you.", "expected_revision": 0, "idempotency_key": "stg-1"},
    )
    _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "post_narration",
        {"text": "Cold mist drifts from the mouth.", "idempotency_key": "nar-1"},
    )
    _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "world_create_entry",
        {"entry": {"kind": "scene", "title": "Cave Entrance", "state": {"kind": "scene"}}, "idempotency_key": "wce-1"},
    )
    _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "world_set_current_context",
        {"patch": {"expected_revision": 0, "current_situation": "Standing at cave entrance"}, "idempotency_key": "wscc-1"},
    )
    _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "request_check",
        {
            "target_seat_ids": [str(fix.human_seat_id)],
            "request_type": "skill",
            "skill_ref": "perception",
            "dc": 12,
            "idempotency_key": "chk-1",
        },
    )


def test_mcp_dm_echoes_do_not_wake_wait(integration_fixture: IntegrationFixture) -> None:
    fix = integration_fixture
    _execute_dm_echo_writes(fix)

    # Own echo writes should not wake wait_for_event; it times out and returns empty events
    # while advancing the cursor to the last written event sequence (seq 5).
    wait_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "wait_for_event",
        {"after_seq": 0, "timeout": 0.2},
    )
    wait_data = wait_res["structuredContent"]["data"]
    assert wait_data["events"] == []
    assert wait_data["cursor"] == 5

    # Human player posts dialogue through the Human REST route
    rest_resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/exploration",
        json={
            "kind": "dialogue",
            "text": "I ready my sword and step inside.",
            "subject_seat_id": str(fix.human_seat_id),
            "idempotency_key": "human-dial-1",
        },
        headers={"Authorization": f"Bearer {fix.human_token}"},
    )
    assert rest_resp.status_code == 200

    # AI DM wait_for_event(after_seq=5) returns exactly that one dialogue
    wait_res2 = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "wait_for_event",
        {"after_seq": wait_data["cursor"], "timeout": 0.2},
    )
    wait_data2 = wait_res2["structuredContent"]["data"]
    assert len(wait_data2["events"]) == 1
    event0 = wait_data2["events"][0]
    assert event0["kind"] == "exploration.dialogue"
    assert event0["payload"]["text"] == "I ready my sword and step inside."


def test_mcp_include_own_returns_dm_echoes(integration_fixture: IntegrationFixture) -> None:
    fix = integration_fixture
    _execute_dm_echo_writes(fix)

    wait_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "wait_for_event",
        {"after_seq": 0, "include_own": True, "timeout": 0},
    )
    wait_data = wait_res["structuredContent"]["data"]
    assert len(wait_data["events"]) == 5
    assert [e["kind"] for e in wait_data["events"]] == [
        "stage.updated",
        "exploration.narration",
        "world.entry.created",
        "world.context_changed",
        "roll.requested",
    ]


def test_mcp_get_pending_events_and_human_events_include_dm_echoes(
    integration_fixture: IntegrationFixture,
) -> None:
    fix = integration_fixture
    _execute_dm_echo_writes(fix)

    pending_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "get_pending_events",
        {"after_seq": 0},
    )
    pending_data = pending_res["structuredContent"]["data"]
    assert len(pending_data["events"]) == 5
    assert [e["kind"] for e in pending_data["events"]] == [
        "stage.updated",
        "exploration.narration",
        "world.entry.created",
        "world.context_changed",
        "roll.requested",
    ]

    human_resp = fix.client.get(
        f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/events?after=0",
        headers={"Authorization": f"Bearer {fix.human_token}"},
    )
    assert human_resp.status_code == 200
    human_events = human_resp.json()["events"]
    # Human player receives player-visible events; world.context_changed is dm_only
    assert len(human_events) == 4
    assert [e["kind"] for e in human_events] == [
        "stage.updated",
        "exploration.narration",
        "world.entry.created",
        "roll.requested",
    ]


def test_mcp_other_actor_writes_wake_ai_dm(integration_fixture: IntegrationFixture) -> None:
    fix = integration_fixture

    # 1. AI DM requests a check
    rc_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "request_check",
        {
            "target_seat_ids": [str(fix.human_seat_id)],
            "request_type": "skill",
            "skill_ref": "perception",
            "dc": 10,
            "idempotency_key": "chk-p4",
        },
    )
    roll_req_id = rc_res["structuredContent"]["data"]["requests"][0]["id"]
    cursor = 1

    # 2. AI player posts dialogue via MCP
    _mcp_call(
        fix.client,
        fix.ai_player_token,
        "post_dialogue",
        {"text": "I watch the corridor.", "idempotency_key": "ai-dial-4"},
    )

    # 3. Human player posts dialogue via REST
    human_dial_resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/exploration",
        json={
            "kind": "dialogue",
            "text": "I search the chest.",
            "subject_seat_id": str(fix.human_seat_id),
            "idempotency_key": "human-dial-4",
        },
        headers={"Authorization": f"Bearer {fix.human_token}"},
    )
    assert human_dial_resp.status_code == 200

    # 4. Human player resolves the roll request
    roll_resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/rolls/formal",
        json={
            "roll_request_id": str(roll_req_id),
            "source": "server",
            "idempotency_key": "roll-res-4",
        },
        headers={"Authorization": f"Bearer {fix.human_token}"},
    )
    assert roll_resp.status_code == 200

    # 5. AI DM wait_for_event(after_seq=cursor) returns all 3 other-actor writes
    wait_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "wait_for_event",
        {"after_seq": cursor, "timeout": 0},
    )
    wait_events = wait_res["structuredContent"]["data"]["events"]
    assert [e["kind"] for e in wait_events] == [
        "exploration.dialogue",
        "exploration.dialogue",
        "roll.resolved",
    ]


def test_mcp_combat_events_not_suppressed(integration_fixture: IntegrationFixture) -> None:
    fix = integration_fixture

    enemy_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "combat_create_quick_enemy",
        {"name": "Goblin Scout", "armor_class": 13, "max_hp": 7, "idempotency_key": "enemy-5"},
    )
    monster_instance_id = enemy_res["structuredContent"]["data"]["id"]

    start_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "combat_start",
        {"include_active_party": True, "idempotency_key": "start-5"},
    )
    assert start_res["isError"] is False

    add_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "combat_add_monster",
        {"monster_instance_id": monster_instance_id, "idempotency_key": "add-gob-5"},
    )
    entries = add_res["structuredContent"]["data"]["entries"]

    req_init_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "combat_request_initiative",
        {"idempotency_key": "req-init-5"},
    )
    requests = req_init_res["structuredContent"]["data"]["requests"]
    assert len(requests) >= 2

    for req in requests:
        _mcp_call(
            fix.client,
            fix.ai_dm_token,
            "combat_roll_initiative",
            {"roll_request_id": req["id"], "idempotency_key": f"roll-init-{req['id']}"},
        )

    with fix.engine.connect() as conn:
        rows = conn.execute(
            select(combat_entries.c.id, combat_entries.c.initiative_total)
            .where(combat_entries.c.status == "active")
        ).all()
        ordered_ids = [
            str(r[0])
            for r in sorted(rows, key=lambda r: (-int(r[1] or 0), str(r[0])))
        ]
    res_final = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "combat_finalize_initiative",
        {"ordered_entry_ids": ordered_ids, "idempotency_key": "final-5"},
    )
    assert res_final.get("isError") is False, res_final

    res_adv = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "combat_advance_turn",
        {"idempotency_key": "adv-5"},
    )
    assert res_adv.get("isError") is False, res_adv

    # AI DM wait_for_event from beginning receives combat.* events and in-combat roll.requested
    wait_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "wait_for_event",
        {"after_seq": 0, "timeout": 0},
    )
    events = wait_res["structuredContent"]["data"]["events"]
    assert len(events) > 0

    combat_kinds = [e["kind"] for e in events if e["kind"].startswith("combat.")]
    assert "combat.started" in combat_kinds
    assert "combat.turn_advanced" in combat_kinds

    in_combat_rolls = [
        e
        for e in events
        if e["kind"] == "roll.requested" and "combat_id" in e.get("payload", {})
    ]
    assert len(in_combat_rolls) > 0


def test_mcp_player_wait_gets_no_extra_secrets(integration_fixture: IntegrationFixture) -> None:
    fix = integration_fixture

    # 1. AI DM posts dm_only fact
    _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "world_create_entry",
        {
            "entry": {
                "kind": "fact",
                "body": "Secret treasure hidden in the floorboards.",
                "visibility": "dm_only",
                "state": {"kind": "fact"},
            },
            "idempotency_key": "secret-fact-6",
        },
    )

    # 2. AI DM posts public narration
    _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "post_narration",
        {"text": "The candle flickers in the draft.", "idempotency_key": "pub-narr-6"},
    )

    # 3. AI player wait_for_event without include_own returns only public narration
    p_wait1 = _mcp_call(
        fix.client,
        fix.ai_player_token,
        "wait_for_event",
        {"after_seq": 0, "timeout": 0},
    )
    p_events1 = p_wait1["structuredContent"]["data"]["events"]
    assert len(p_events1) == 1
    assert p_events1[0]["kind"] == "exploration.narration"
    assert p_events1[0]["payload"]["text"] == "The candle flickers in the draft."

    # 4. AI player wait_for_event with include_own=True STILL returns only public narration
    p_wait2 = _mcp_call(
        fix.client,
        fix.ai_player_token,
        "wait_for_event",
        {"after_seq": 0, "include_own": True, "timeout": 0},
    )
    p_events2 = p_wait2["structuredContent"]["data"]["events"]
    assert len(p_events2) == 1
    assert p_events2[0]["kind"] == "exploration.narration"

    # 5. AI DM sees both events with include_own=True
    dm_wait = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "wait_for_event",
        {"after_seq": 0, "include_own": True, "timeout": 0},
    )
    dm_events = dm_wait["structuredContent"]["data"]["events"]
    assert len(dm_events) == 2

    # 6. No returned event JSON contains the internal AI actor stamp keys
    for event_dict in p_events1 + p_events2 + dm_events:
        assert "acting_ai_controller_grant_id" not in event_dict
        assert "acting_grant_generation" not in event_dict


# Per-kind significant payload keys identifying or describing the mutation
# (ids, revision, text, title/body, status, values). The rule asserted is:
# for each significant key present in the event payload, its value (or leaf values)
# must appear within the structured tool response data.
SIGNIFICANT_PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    "stage.updated": ("text", "stage_revision"),
    "exploration.narration": ("text",),
    "exploration.dialogue": ("text",),
    "exploration.action": ("text",),
    "exploration.ooc": ("text",),
    "exploration.whisper_dm": ("text",),
    "roll.requested": ("roll_group_id",),
    "world.entry.created": ("entry_id", "entry_kind", "revision"),
    "world.entry.updated": ("entry_id", "entry_kind", "revision"),
    "world.entry.archived": ("entry_id", "entry_kind", "revision"),
    "world.override.created": ("override_id", "adventure_entry_id", "revision"),
    "world.override.updated": ("override_id", "adventure_entry_id", "revision"),
    "world.override.cleared": ("override_id", "adventure_entry_id", "revision"),
    "world.context_changed": ("revision",),
    "world.action.resolved": ("action", "entry_id"),
    "character.state.updated": ("changed_fields",),
    "roll.quick": ("formula", "total"),
}


def _value_in_data(val: object, data: object) -> bool:
    if data == val or str(data) == str(val):
        return True
    if isinstance(data, dict):
        if str(val) in data:
            return True
        return any(_value_in_data(val, v) for v in data.values())
    if isinstance(data, (list, tuple)):
        return any(_value_in_data(val, item) for item in data)
    return False


@pytest.mark.parametrize(
    "kind",
    [
        "stage.updated",
        "exploration.narration",
        "exploration.dialogue",
        "exploration.action",
        "exploration.ooc",
        "exploration.whisper_dm",
        "roll.requested",
        "world.entry.created",
        "world.entry.updated",
        "world.entry.archived",
        "world.override.created",
        "world.override.updated",
        "world.override.cleared",
        "world.context_changed",
        "world.action.resolved",
        "character.state.updated",
        "roll.quick",
    ],
)
def test_whitelisted_tool_results_cover_event_payload(
    kind: str,
    integration_fixture: IntegrationFixture,
) -> None:
    fix = integration_fixture

    cursor_before = _mcp_call(
        fix.client, fix.ai_dm_token, "get_pending_events", {"after_seq": 0}
    )["structuredContent"]["data"]["cursor"]

    caller_token = fix.ai_dm_token
    tool_name = ""
    tool_args: dict[str, object] = {}

    if kind == "stage.updated":
        tool_name = "set_stage_text"
        tool_args = {"text": "A sunlit meadow.", "expected_revision": 0, "idempotency_key": "t7-stg"}
    elif kind == "exploration.narration":
        tool_name = "post_narration"
        tool_args = {"text": "The river flows gently.", "idempotency_key": "t7-narr"}
    elif kind == "exploration.dialogue":
        caller_token = fix.ai_player_token
        tool_name = "post_dialogue"
        tool_args = {"text": "I think we should rest here.", "idempotency_key": "t7-dial"}
    elif kind == "exploration.action":
        caller_token = fix.ai_player_token
        tool_name = "post_action"
        tool_args = {"text": "I set up a campfire.", "idempotency_key": "t7-act"}
    elif kind == "exploration.ooc":
        tool_name = "post_ooc"
        tool_args = {"text": "Ten minute break everyone.", "idempotency_key": "t7-ooc"}
    elif kind == "exploration.whisper_dm":
        caller_token = fix.ai_player_token
        tool_name = "whisper_dm"
        tool_args = {"text": "I am keeping my eye on the door.", "idempotency_key": "t7-whisper"}
    elif kind == "roll.requested":
        tool_name = "request_check"
        tool_args = {
            "target_seat_ids": [str(fix.human_seat_id)],
            "request_type": "skill",
            "skill_ref": "perception",
            "dc": 14,
            "idempotency_key": "t7-rc",
        }
    elif kind == "world.entry.created":
        tool_name = "world_create_entry"
        tool_args = {
            "entry": {"kind": "scene", "title": "Crystal Cave", "state": {"kind": "scene"}},
            "idempotency_key": "t7-wc",
        }
    elif kind == "world.entry.updated":
        setup_res = _mcp_call(
            fix.client,
            fix.ai_dm_token,
            "world_create_entry",
            {
                "entry": {"kind": "npc", "title": "Old Sage", "state": {"kind": "npc"}},
                "idempotency_key": "t7-wu-setup",
            },
        )
        entry_id = setup_res["structuredContent"]["data"]["id"]
        cursor_before = _mcp_call(
            fix.client, fix.ai_dm_token, "get_pending_events", {"after_seq": 0}
        )["structuredContent"]["data"]["cursor"]
        tool_name = "world_update_entry"
        tool_args = {
            "entry_id": entry_id,
            "patch": {"expected_revision": 1, "title": "Ancient Sage"},
            "idempotency_key": "t7-wu",
        }
    elif kind == "world.entry.archived":
        setup_res = _mcp_call(
            fix.client,
            fix.ai_dm_token,
            "world_create_entry",
            {
                "entry": {"kind": "npc", "title": "Wandering Merchant", "state": {"kind": "npc"}},
                "idempotency_key": "t7-wa-setup",
            },
        )
        entry_id = setup_res["structuredContent"]["data"]["id"]
        cursor_before = _mcp_call(
            fix.client, fix.ai_dm_token, "get_pending_events", {"after_seq": 0}
        )["structuredContent"]["data"]["cursor"]
        tool_name = "world_archive_entry"
        tool_args = {
            "entry_id": entry_id,
            "expected_revision": 1,
            "idempotency_key": "t7-wa",
        }
    elif kind == "world.override.created":
        tool_name = "world_set_override"
        tool_args = {
            "intent": {
                "adventure_entry_id": str(fix.adv_entry_id),
                "note": "Initial override note",
                "state": {"kind": "scene"},
            },
            "idempotency_key": "t7-woc",
        }
    elif kind == "world.override.updated":
        setup_res = _mcp_call(
            fix.client,
            fix.ai_dm_token,
            "world_set_override",
            {
                "intent": {
                    "adventure_entry_id": str(fix.adv_entry_id),
                    "note": "Initial note",
                    "state": {"kind": "scene"},
                },
                "idempotency_key": "t7-wou-setup",
            },
        )
        override_id = setup_res["structuredContent"]["data"]["id"]
        cursor_before = _mcp_call(
            fix.client, fix.ai_dm_token, "get_pending_events", {"after_seq": 0}
        )["structuredContent"]["data"]["cursor"]
        tool_name = "world_set_override"
        tool_args = {
            "intent": {
                "adventure_entry_id": str(fix.adv_entry_id),
                "expected_override_id": override_id,
                "expected_revision": 1,
                "note": "Updated override note",
            },
            "idempotency_key": "t7-wou",
        }
    elif kind == "world.override.cleared":
        setup_res = _mcp_call(
            fix.client,
            fix.ai_dm_token,
            "world_set_override",
            {
                "intent": {
                    "adventure_entry_id": str(fix.adv_entry_id),
                    "note": "To be cleared",
                    "state": {"kind": "scene"},
                },
                "idempotency_key": "t7-wocl-setup",
            },
        )
        override_id = setup_res["structuredContent"]["data"]["id"]
        cursor_before = _mcp_call(
            fix.client, fix.ai_dm_token, "get_pending_events", {"after_seq": 0}
        )["structuredContent"]["data"]["cursor"]
        tool_name = "world_clear_override"
        tool_args = {
            "intent": {
                "adventure_entry_id": str(fix.adv_entry_id),
                "expected_override_id": override_id,
                "expected_revision": 1,
            },
            "idempotency_key": "t7-wocl",
        }
    elif kind == "world.context_changed":
        tool_name = "world_set_current_context"
        tool_args = {
            "patch": {"expected_revision": 0, "current_situation": "Storm approaching"},
            "idempotency_key": "t7-wctx",
        }
    elif kind == "world.action.resolved":
        tool_name = "world_resolve_action"
        tool_args = {
            "request": {
                "change": {
                    "action": "create_entry",
                    "payload": {
                        "kind": "fact",
                        "body": "The river is sacred to locals.",
                        "state": {"kind": "fact"},
                    },
                },
                "narration": "You recall that the river is sacred.",
            },
            "idempotency_key": "t7-war",
        }
    elif kind == "character.state.updated":
        caller_token = fix.ai_player_token
        tool_name = "update_character_state"
        tool_args = {
            "patch": {"current_hp": 8, "idempotency_key": "t7-hp"},
        }
    elif kind == "roll.quick":
        caller_token = fix.ai_player_token
        tool_name = "quick_roll"
        tool_args = {
            "dice_count": 1,
            "die_sides": 20,
            "flat_adjustment": 3,
            "idempotency_key": "t7-qr",
        }
    else:
        pytest.fail(f"Unhandled whitelisted kind: {kind}")

    tool_res = _mcp_call(fix.client, caller_token, tool_name, tool_args)
    assert tool_res["isError"] is False
    tool_data = tool_res["structuredContent"]["data"]

    events_res = _mcp_call(
        fix.client, fix.ai_dm_token, "get_pending_events", {"after_seq": cursor_before}
    )
    events = events_res["structuredContent"]["data"]["events"]
    matching_events = [e for e in events if e["kind"] == kind]
    assert len(matching_events) >= 1, f"Expected event of kind {kind} to be recorded"
    target_event = matching_events[-1]
    payload = target_event["payload"]

    significant_keys = SIGNIFICANT_PAYLOAD_KEYS[kind]
    for key in significant_keys:
        assert key in payload, f"Key '{key}' missing from payload of event '{kind}'"
        val = payload[key]
        if isinstance(val, (list, tuple)):
            for item in val:
                assert _value_in_data(item, tool_data), (
                    f"Payload item '{item}' from '{key}' in event '{kind}' missing in tool result"
                )
        else:
            assert _value_in_data(val, tool_data), (
                f"Payload value '{val}' for '{key}' in event '{kind}' missing in tool result"
            )
