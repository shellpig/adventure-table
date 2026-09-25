from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.domain.combat.event_projection import project_combat_event_payload
from app.domain.rooms.ai_event_projection import (
    DICE_DETAIL_KEYS,
    compact_roll_resolved,
)
from tests.test_m06b_mcp_echo_integration import (
    IntegrationFixture,
    _mcp_call,
    integration_fixture,
)

# Keep the imported fixture discoverable by pytest
_ = integration_fixture


@pytest.mark.parametrize(
    ("is_dm", "expected_keys"),
    [
        (False, {"roll_request_id", "total", "formula", "natural", "visibility"}),
        (
            True,
            {
                "roll_request_id",
                "total",
                "formula",
                "natural",
                "visibility",
                "dc",
                "outcome",
            },
        ),
    ],
    ids=["player_projection", "dm_projection"],
)
def test_compact_drops_dice_detail_and_adds_natural(
    is_dm: bool,
    expected_keys: set[str],
) -> None:
    payload = {
        "roll_request_id": str(uuid4()),
        "source": "server",
        "formula": "1d20+3",
        "raw_dice": [14],
        "kept_dice": [14],
        "base_modifier": 3,
        "flat_adjustment": 0,
        "total": 17,
        "visibility": "public",
    }
    compacted = compact_roll_resolved(
        payload,
        dc=15 if is_dm else None,
        auto_fail=False,
        is_current_dm=is_dm,
    )
    assert set(compacted.keys()) == expected_keys
    assert compacted["natural"] == 14
    assert compacted["total"] == 17
    assert compacted["formula"] == "1d20+3"
    assert compacted["visibility"] == "public"
    for detail_key in DICE_DETAIL_KEYS:
        assert detail_key not in compacted
    if is_dm:
        assert compacted["dc"] == 15
        assert compacted["outcome"] == "success"
    else:
        assert "dc" not in compacted
        assert "outcome" not in compacted


@pytest.mark.parametrize(
    ("kind_name", "extra_payload", "extra_expected"),
    [
        (
            "attack",
            {
                "combat_id": "c-101",
                "action_id": "a-202",
                "roll_result_id": "r-303",
                "attacker_entry_id": "entry-atk",
                "target_entry_id": "entry-tgt",
                "target_is_hostile": True,
                "target_injury_level": "injured",
                "attack_resolution": {"hit": True, "critical": False, "total": 19},
            },
            {
                "combat_id": "c-101",
                "action_id": "a-202",
                "roll_result_id": "r-303",
                "attacker_entry_id": "entry-atk",
                "target_entry_id": "entry-tgt",
                "target_is_hostile": True,
                "target_injury_level": "injured",
                "attack_resolution": {"hit": True, "critical": False, "total": 19},
            },
        ),
        (
            "initiative",
            {
                "combat_id": "c-404",
                "roll_result_id": "r-505",
                "combat_entry_ids": ["entry-1", "entry-2"],
            },
            {
                "combat_id": "c-404",
                "roll_result_id": "r-505",
                "combat_entry_ids": ["entry-1", "entry-2"],
            },
        ),
    ],
    ids=["attack_style_payload", "initiative_style_payload"],
)
def test_compact_keeps_combat_keys(
    kind_name: str,
    extra_payload: dict[str, object],
    extra_expected: dict[str, object],
) -> None:
    del kind_name
    base_payload = {
        "roll_request_id": "req-999",
        "source": "server",
        "formula": "1d20+2",
        "raw_dice": [17],
        "kept_dice": [17],
        "base_modifier": 2,
        "flat_adjustment": 0,
        "total": 19,
        "visibility": "public",
        **extra_payload,
    }
    compacted = compact_roll_resolved(
        base_payload,
        dc=None,
        auto_fail=False,
        is_current_dm=False,
    )
    for detail_key in DICE_DETAIL_KEYS:
        assert detail_key not in compacted
    for k, v in extra_expected.items():
        assert compacted[k] == v
    assert compacted["natural"] == 17
    assert compacted["total"] == 19


@pytest.mark.parametrize(
    ("total", "dc", "auto_fail", "expected_dc", "expected_outcome"),
    [
        (15, 15, False, 15, "success"),
        (18, 15, False, 15, "success"),
        (14, 15, False, 15, "failure"),
        (18, 15, True, 15, "failure"),
        (10, 15, True, 15, "failure"),
        (15, None, False, None, None),
        (15, None, True, None, None),
    ],
    ids=[
        "dc_success_exact",
        "dc_success_above",
        "dc_failure_below",
        "dc_auto_fail_overrides_high_total",
        "dc_auto_fail_low_total",
        "dc_none_auto_fail_false",
        "dc_none_auto_fail_true",
    ],
)
def test_dm_outcome_matrix(
    total: int,
    dc: int | None,
    auto_fail: bool,
    expected_dc: int | None,
    expected_outcome: str | None,
) -> None:
    payload = {
        "roll_request_id": "req-matrix",
        "source": "server",
        "formula": "1d20",
        "raw_dice": [total],
        "kept_dice": [total],
        "base_modifier": 0,
        "flat_adjustment": 0,
        "total": total,
        "visibility": "public",
    }
    compacted = compact_roll_resolved(
        payload,
        dc=dc,
        auto_fail=auto_fail,
        is_current_dm=True,
    )
    assert compacted["dc"] == expected_dc
    assert compacted["outcome"] == expected_outcome


@pytest.mark.parametrize(
    ("formula", "kept_dice", "expected_natural"),
    [
        ("1d20+5", [14], 14),
        ("2d20kh1+2", [18], 18),
        ("2d20kl1-1", [3], 3),
        ("1d20", [20], 20),
        ("1d20", [1], 1),
        ("1d6+2", [4], None),
        ("1d200+1", [50], None),
        ("2d20+1", [10, 15], None),
        ("1d20+3", None, None),
    ],
    ids=[
        "single_d20_plus",
        "advantage_plus",
        "disadvantage_minus",
        "nat20",
        "nat1",
        "non_d20_formula",
        "d200_not_d20",
        "multiple_kept_dice",
        "missing_kept_dice_enemy_hidden",
    ],
)
def test_natural_matches_kept_die(
    formula: str,
    kept_dice: list[int] | None,
    expected_natural: int | None,
) -> None:
    payload: dict[str, object] = {
        "roll_request_id": "req-nat",
        "source": "server",
        "formula": formula,
        "base_modifier": 0,
        "flat_adjustment": 0,
        "total": 15,
        "visibility": "public",
    }
    if kept_dice is not None:
        payload["raw_dice"] = list(kept_dice)
        payload["kept_dice"] = list(kept_dice)
    compacted = compact_roll_resolved(
        payload,
        dc=None,
        auto_fail=False,
        is_current_dm=False,
    )
    assert compacted["natural"] == expected_natural


def _request_and_resolve_check(
    fix: IntegrationFixture,
    *,
    dc: int | None,
    key_prefix: str,
) -> tuple[str, dict[str, object]]:
    req_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "request_check",
        {
            "target_seat_ids": [str(fix.ai_player_seat_id)],
            "request_type": "skill" if dc is not None else "ability",
            "skill_ref": "perception" if dc is not None else None,
            "ability_ref": None if dc is not None else "strength",
            "dc": dc,
            "idempotency_key": f"{key_prefix}-chk",
        },
    )
    req_id = req_res["structuredContent"]["data"]["requests"][0]["id"]
    resolve_res = _mcp_call(
        fix.client,
        fix.ai_player_token,
        "roll_pending",
        {
            "roll_request_id": req_id,
            "idempotency_key": f"{key_prefix}-roll",
        },
    )
    return req_id, resolve_res["structuredContent"]["data"]


def test_mcp_wait_compacts_roll_resolved_for_dm_and_player(
    integration_fixture: IntegrationFixture,
) -> None:
    fix = integration_fixture

    req_id_dc, _ = _request_and_resolve_check(fix, dc=14, key_prefix="c5-dc")
    req_id_nodc, _ = _request_and_resolve_check(fix, dc=None, key_prefix="c5-nodc")

    dm_wait = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "wait_for_event",
        {"after_seq": 0, "timeout": 0.1},
    )
    dm_events = dm_wait["structuredContent"]["data"]["events"]
    dm_rolls = {
        e["payload"]["roll_request_id"]: e["payload"]
        for e in dm_events
        if e["kind"] == "roll.resolved"
    }

    assert req_id_dc in dm_rolls
    roll_dc_dm = dm_rolls[req_id_dc]
    assert set(roll_dc_dm.keys()) == {
        "roll_request_id",
        "total",
        "formula",
        "natural",
        "visibility",
        "dc",
        "outcome",
    }
    assert roll_dc_dm["dc"] == 14
    expected_outcome = "success" if roll_dc_dm["total"] >= 14 else "failure"
    assert roll_dc_dm["outcome"] == expected_outcome
    for key in DICE_DETAIL_KEYS:
        assert key not in roll_dc_dm

    assert req_id_nodc in dm_rolls
    roll_nodc_dm = dm_rolls[req_id_nodc]
    assert set(roll_nodc_dm.keys()) == {
        "roll_request_id",
        "total",
        "formula",
        "natural",
        "visibility",
        "dc",
        "outcome",
    }
    assert roll_nodc_dm["dc"] is None
    assert roll_nodc_dm["outcome"] is None
    for key in DICE_DETAIL_KEYS:
        assert key not in roll_nodc_dm

    player_wait = _mcp_call(
        fix.client,
        fix.ai_player_token,
        "wait_for_event",
        {"after_seq": 0, "timeout": 0.1},
    )
    player_events = player_wait["structuredContent"]["data"]["events"]
    player_rolls = {
        e["payload"]["roll_request_id"]: e["payload"]
        for e in player_events
        if e["kind"] == "roll.resolved"
    }

    for req_id in (req_id_dc, req_id_nodc):
        assert req_id in player_rolls
        p_roll = player_rolls[req_id]
        assert set(p_roll.keys()) == {
            "roll_request_id",
            "total",
            "formula",
            "natural",
            "visibility",
        }
        assert "dc" not in p_roll
        assert "outcome" not in p_roll
        for key in DICE_DETAIL_KEYS:
            assert key not in p_roll


def test_mcp_pending_and_human_paths_keep_full_roll_payload(
    integration_fixture: IntegrationFixture,
) -> None:
    fix = integration_fixture

    req_id, _ = _request_and_resolve_check(fix, dc=15, key_prefix="c6")

    pending_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "get_pending_events",
        {"after_seq": 0, "limit": 50},
    )
    pending_events = pending_res["structuredContent"]["data"]["events"]
    pending_roll = next(
        e["payload"]
        for e in pending_events
        if e["kind"] == "roll.resolved" and e["payload"]["roll_request_id"] == req_id
    )
    for key in DICE_DETAIL_KEYS:
        assert key in pending_roll, f"Expected {key} in get_pending_events roll.resolved"

    human_res = fix.client.get(
        f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/events?after_seq=0&limit=50",
        headers={"Authorization": f"Bearer {fix.human_token}"},
    )
    assert human_res.status_code == 200
    human_events = human_res.json()["events"]
    human_roll = next(
        e["payload"]
        for e in human_events
        if e["kind"] == "roll.resolved" and e["payload"]["roll_request_id"] == req_id
    )
    for key in DICE_DETAIL_KEYS:
        assert key in human_roll, f"Expected {key} in human GET /events roll.resolved"


def test_mcp_wait_queries_roll_requests_once_per_page(
    integration_fixture: IntegrationFixture,
) -> None:
    fix = integration_fixture

    req_id_1, _ = _request_and_resolve_check(fix, dc=12, key_prefix="c7-1")
    req_id_2, _ = _request_and_resolve_check(fix, dc=16, key_prefix="c7-2")

    ai_service = fix.client.app.state.ai_tool_application_service
    roll_service = ai_service.roll_service
    calls: list[tuple[object, set[UUID]]] = []
    original_method = roll_service.request_outcome_inputs

    def spy_request_outcome_inputs(actor, request_ids):
        calls.append((actor, set(request_ids)))
        return original_method(actor, request_ids)

    roll_service.request_outcome_inputs = spy_request_outcome_inputs
    try:
        wait_res = _mcp_call(
            fix.client,
            fix.ai_dm_token,
            "wait_for_event",
            {"after_seq": 0, "timeout": 0.1},
        )
    finally:
        roll_service.request_outcome_inputs = original_method

    events = wait_res["structuredContent"]["data"]["events"]
    resolved_in_wait = [
        e
        for e in events
        if e["kind"] == "roll.resolved"
        and e["payload"]["roll_request_id"] in (req_id_1, req_id_2)
    ]
    assert len(resolved_in_wait) == 2
    assert len(calls) == 1
    _actor, queried_ids = calls[0]
    assert queried_ids == {UUID(req_id_1), UUID(req_id_2)}


def test_mcp_combat_roll_projection_keeps_enemy_secrecy(
    integration_fixture: IntegrationFixture,
) -> None:
    fix = integration_fixture

    enemy_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "combat_create_quick_enemy",
        {"name": "Goblin Scout", "armor_class": 13, "max_hp": 7, "idempotency_key": "c8-enemy"},
    )
    monster_instance_id = enemy_res["structuredContent"]["data"]["id"]

    start_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "combat_start",
        {"include_active_party": True, "idempotency_key": "c8-start"},
    )
    assert start_res["isError"] is False

    add_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "combat_add_monster",
        {"monster_instance_id": monster_instance_id, "idempotency_key": "c8-add-monster"},
    )
    assert add_res["isError"] is False

    req_init_res = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "combat_request_initiative",
        {"idempotency_key": "c8-req-init"},
    )
    requests = req_init_res["structuredContent"]["data"]["requests"]
    assert len(requests) >= 2

    monster_req_id = None
    for req in requests:
        _mcp_call(
            fix.client,
            fix.ai_dm_token,
            "combat_roll_initiative",
            {"roll_request_id": req["id"], "idempotency_key": f"c8-roll-init-{req['id']}"},
        )
        if req.get("target_combat_entry_id") is not None:
            monster_req_id = req["id"]

    # AI player wait_for_event vs get_pending_events
    wait_res = _mcp_call(
        fix.client,
        fix.ai_player_token,
        "wait_for_event",
        {"after_seq": 0, "timeout": 0.1},
    )
    wait_events = wait_res["structuredContent"]["data"]["events"]

    pending_res = _mcp_call(
        fix.client,
        fix.ai_player_token,
        "get_pending_events",
        {"after_seq": 0, "limit": 100},
    )
    pending_events = pending_res["structuredContent"]["data"]["events"]

    # If monster_req_id was found, assert on that specific roll; otherwise on any combat roll.resolved
    wait_rolls = [
        e["payload"]
        for e in wait_events
        if e["kind"] == "roll.resolved"
        and (monster_req_id is None or e["payload"].get("roll_request_id") == monster_req_id)
    ]
    pending_rolls = {
        e["payload"]["roll_request_id"]: e["payload"]
        for e in pending_events
        if e["kind"] == "roll.resolved"
    }

    assert len(wait_rolls) > 0
    for w_roll in wait_rolls:
        req_id = w_roll["roll_request_id"]
        assert req_id in pending_rolls
        p_roll = pending_rolls[req_id]

        # Compact roll has no key that get_pending_events lacks, except natural
        assert set(w_roll.keys()) - {"natural"} <= set(p_roll.keys())
        assert "dc" not in w_roll
        assert "outcome" not in w_roll
        for detail_key in DICE_DETAIL_KEYS:
            assert detail_key not in w_roll

    # Also assert the unit-level secrecy projection:
    monster_attack_payload = {
        "roll_request_id": str(uuid4()),
        "source": "server",
        "formula": "1d20+5",
        "raw_dice": [16],
        "kept_dice": [16],
        "base_modifier": 5,
        "flat_adjustment": 0,
        "total": 21,
        "visibility": "public",
        "target_is_hostile": True,
        "combat_id": str(uuid4()),
        "target_ac": 15,
        "before_hp": 30,
        "after_hp": 22,
    }
    projected = project_combat_event_payload(
        "roll.resolved",
        monster_attack_payload,
        audience="player",
    )
    for secret_key in ("target_ac", "before_hp", "after_hp"):
        assert secret_key not in projected

    compacted = compact_roll_resolved(
        projected,
        dc=15,
        auto_fail=False,
        is_current_dm=False,
    )
    assert "dc" not in compacted
    assert "outcome" not in compacted
    for secret_key in ("target_ac", "before_hp", "after_hp"):
        assert secret_key not in compacted
    for detail_key in DICE_DETAIL_KEYS:
        assert detail_key not in compacted
