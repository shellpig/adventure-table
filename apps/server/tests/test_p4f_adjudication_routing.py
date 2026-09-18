from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.domain.combat.ai_tools import next_combat_action
from app.main import app
from app.mcp.guide import render_guide
from app.persistence.rooms.table_runtime import session_events
from tests.test_p4e_mcp_combat_context_and_effects import _mcp_call, mcp_combat_fixture


@pytest.mark.parametrize(
    ("kind", "expected_hint"),
    [
        ("range", "adjudicate_attack"),
        ("reach", "adjudicate_special_attack"),
        ("affected_targets", "resolve_aoe_spell"),
        ("opportunity_attack", "resolve_adjudication"),
        ("special", "resolve_adjudication"),
    ],
)
def test_next_combat_action_dm_five_kinds(kind: str, expected_hint: str) -> None:
    hint = next_combat_action(
        is_dm=True,
        current_turn_entry_id=uuid4(),
        current_turn_is_monster=False,
        my_entry_ids=frozenset(),
        pending_adjudication_kinds=(kind,),
        has_open_reaction=False,
        has_pending_roll=False,
    )
    assert hint == expected_hint


def test_next_combat_action_dm_first_kind_precedence_and_unknown() -> None:
    # First kind in tuple determines hint
    hint = next_combat_action(
        is_dm=True,
        current_turn_entry_id=uuid4(),
        current_turn_is_monster=False,
        my_entry_ids=frozenset(),
        pending_adjudication_kinds=("reach", "range"),
        has_open_reaction=False,
        has_pending_roll=False,
    )
    assert hint == "adjudicate_special_attack"

    # Unknown kind raises ValueError
    with pytest.raises(ValueError, match="Unknown adjudication kind: invalid_kind"):
        next_combat_action(
            is_dm=True,
            current_turn_entry_id=uuid4(),
            current_turn_is_monster=False,
            my_entry_ids=frozenset(),
            pending_adjudication_kinds=("invalid_kind",),
            has_open_reaction=False,
            has_pending_roll=False,
        )


def test_next_combat_action_player_branch_unchanged() -> None:
    my_id = uuid4()
    # Player with pending adjudication AND pending roll still gets roll_pending
    assert (
        next_combat_action(
            is_dm=False,
            current_turn_entry_id=my_id,
            current_turn_is_monster=False,
            my_entry_ids=frozenset({my_id}),
            pending_adjudication_kinds=("range",),
            has_open_reaction=True,
            has_pending_roll=True,
        )
        == "roll_pending"
    )
    # Open reaction when no pending roll
    assert (
        next_combat_action(
            is_dm=False,
            current_turn_entry_id=my_id,
            current_turn_is_monster=False,
            my_entry_ids=frozenset({my_id}),
            pending_adjudication_kinds=("range",),
            has_open_reaction=True,
            has_pending_roll=False,
        )
        == "respond_to_reaction"
    )
    # Current turn when no reaction or roll
    assert (
        next_combat_action(
            is_dm=False,
            current_turn_entry_id=my_id,
            current_turn_is_monster=False,
            my_entry_ids=frozenset({my_id}),
            pending_adjudication_kinds=("range",),
            has_open_reaction=False,
            has_pending_roll=False,
        )
        == "take_turn"
    )
    # Waiting for event
    assert (
        next_combat_action(
            is_dm=False,
            current_turn_entry_id=uuid4(),
            current_turn_is_monster=False,
            my_entry_ids=frozenset({my_id}),
            pending_adjudication_kinds=("range",),
            has_open_reaction=False,
            has_pending_roll=False,
        )
        == "wait_for_event"
    )


def test_adjudication_routing_mcp_journey(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        facade,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture

    client = TestClient(app)

    # 1. Player requests an attack without range (Quick Combat range_confirmed=True opens range adjudication)
    attacks_res = _mcp_call(
        client,
        player_token,
        "combat_list_attacks",
        {"entry_id": str(char_entry_id)},
    )
    assert attacks_res["isError"] is False
    source_ref = attacks_res["structuredContent"]["data"]["attacks"][0]["source_ref"]

    attack_res = _mcp_call(
        client,
        player_token,
        "combat_request_attack",
        {
            "attacker_entry_id": str(char_entry_id),
            "target_entry_id": str(mage_entry_id),
            "source_ref": source_ref,
            "range_confirmed": True,
            "idempotency_key": "p4f-journey-attack",
        },
    )
    assert attack_res["isError"] is False
    action_id = attack_res["structuredContent"]["data"]["action_id"]

    # 2. DM get_combat_context -> next_required_action == "adjudicate_attack"
    dm_ctx = _mcp_call(client, dm_token, "get_combat_context", {})
    assert dm_ctx["isError"] is False
    assert dm_ctx["structuredContent"]["data"]["next_required_action"] == "adjudicate_attack"

    # 3. DM calls combat_resolve_adjudication on that action_id
    # -> isError True, error.code == "table_conflict", error.detail contains "combat_adjudicate_attack", error.messages keys == {"en", "zh-TW"}
    resolve_err = _mcp_call(
        client,
        dm_token,
        "combat_resolve_adjudication",
        {"action_id": action_id, "trigger": True},
    )
    assert resolve_err["isError"] is True
    err = resolve_err["structuredContent"]["error"]
    assert err["code"] == "table_conflict"
    assert "detail" in err
    assert "combat_adjudicate_attack" in err["detail"]
    assert set(err["messages"].keys()) == {"en", "zh-TW"}

    # 4. DM calls combat_adjudicate_attack(in_range=True) -> succeeds
    adjudicate_res = _mcp_call(
        client,
        dm_token,
        "combat_adjudicate_attack",
        {
            "action_id": action_id,
            "in_range": True,
            "idempotency_key": "p4f-journey-adjudicate",
        },
    )
    assert adjudicate_res["isError"] is False

    # 5. next_required_action is no longer "adjudicate_attack"
    dm_ctx_after = _mcp_call(client, dm_token, "get_combat_context", {})
    assert dm_ctx_after["isError"] is False
    assert dm_ctx_after["structuredContent"]["data"]["next_required_action"] != "adjudicate_attack"


def test_player_adjudication_tools_rejected_zero_events(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        facade,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture

    client = TestClient(app)

    with table.engine.connect() as conn:
        events_before = conn.scalar(
            select(func.count()).select_from(session_events).where(
                session_events.c.session_id == table.session_id
            )
        )

    # Player calls combat_resolve_adjudication -> rejected
    resolve_res = _mcp_call(
        client,
        player_token,
        "combat_resolve_adjudication",
        {"action_id": str(uuid4()), "trigger": True},
    )
    assert resolve_res["isError"] is True
    assert resolve_res["structuredContent"]["error"]["code"] == "permission_denied"

    # Player calls combat_adjudicate_attack -> rejected
    adjudicate_res = _mcp_call(
        client,
        player_token,
        "combat_adjudicate_attack",
        {"action_id": str(uuid4()), "in_range": True},
    )
    assert adjudicate_res["isError"] is True
    assert adjudicate_res["structuredContent"]["error"]["code"] == "permission_denied"

    with table.engine.connect() as conn:
        events_after = conn.scalar(
            select(func.count()).select_from(session_events).where(
                session_events.c.session_id == table.session_id
            )
        )

    assert events_before == events_after


def test_guide_combat_paragraph_contains_adjudication_tools() -> None:
    # zh-TW
    guide_zh = render_guide("zh-TW")
    assert "【戰鬥】" in guide_zh
    combat_zh = guide_zh.split("【戰鬥】", 1)[1].split("\n\n", 1)[0]
    assert "combat_adjudicate_attack" in combat_zh
    assert "combat_adjudicate_special_attack" in combat_zh
    assert "combat_resolve_aoe_spell" in combat_zh
    assert "combat_resolve_adjudication" in combat_zh

    # en
    guide_en = render_guide("en")
    assert "[Combat]" in guide_en
    combat_en = guide_en.split("[Combat]", 1)[1].split("\n\n", 1)[0]
    assert "combat_adjudicate_attack" in combat_en
    assert "combat_adjudicate_special_attack" in combat_en
    assert "combat_resolve_aoe_spell" in combat_en
    assert "combat_resolve_adjudication" in combat_en
