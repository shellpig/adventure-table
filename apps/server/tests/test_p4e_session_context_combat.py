from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.rooms.ai_controllers import get_ai_controller_service
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.domain.rooms.ai_guidance import BRIEFING_MAX_CHARS, render_briefing
from app.main import app
from app.mcp.guide import render_guide
from app.mcp.tools import tool_reference_rows
from tests.test_p4e_mcp_combat_context_and_effects import _mcp_call, mcp_combat_fixture


def test_1_no_active_combat(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        combat_ai_tool_service,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture

    client = TestClient(app)

    # End active combat using the AI DM token
    end_resp = _mcp_call(client, dm_token, "combat_end", {})
    assert end_resp["isError"] is False

    resp_dm = _mcp_call(client, dm_token, "get_session_context", {})
    assert resp_dm["isError"] is False
    data_dm = resp_dm["structuredContent"]["data"]
    assert data_dm["combat"] is None
    assert data_dm["briefing"] == render_briefing(role="dm", mode="active_session")
    assert data_dm["next_required_action"] == "set_stage_text"

    resp_pl = _mcp_call(client, player_token, "get_session_context", {})
    assert resp_pl["isError"] is False
    data_pl = resp_pl["structuredContent"]["data"]
    assert data_pl["combat"] is None
    assert data_pl["briefing"] == render_briefing(role="player", mode="active_session")
    assert data_pl["next_required_action"] == "wait_for_event"


def test_2_active_combat_dm_wire_call(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        combat_ai_tool_service,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture

    client = TestClient(app)
    resp = _mcp_call(client, dm_token, "get_session_context", {})
    assert resp["isError"] is False
    data = resp["structuredContent"]["data"]

    assert data["combat"] is not None
    combat_dict = data["combat"]
    for key in (
        "round",
        "current_turn_entry_id",
        "my_entry_ids",
        "pending_adjudications",
        "next_required_action",
    ):
        assert key in combat_dict

    assert data["next_required_action"] == combat_dict["next_required_action"]
    briefing = data["briefing"]
    assert "MANDATORY DM COMBAT LOOP" in briefing
    assert briefing.count("wait_for_event") >= 2

    serialized = json.dumps(resp)
    assert "rules_snapshot" not in serialized


def test_3_active_combat_player_wire_call_secrecy(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        combat_ai_tool_service,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture

    client = TestClient(app)
    resp = _mcp_call(client, player_token, "get_session_context", {})
    assert resp["isError"] is False
    data = resp["structuredContent"]["data"]

    assert data["combat"] is not None
    combat_dict = data["combat"]
    assert data["next_required_action"] == combat_dict["next_required_action"]

    combatants = combat_dict["combat"]["combatants"]
    monster_cb = next(c for c in combatants if c["subject_kind"] == "monster")
    char_cb = next(c for c in combatants if c["subject_kind"] == "character")

    monster_proj = monster_cb["projection"]
    forbidden_keys = [
        "current_hp",
        "max_hp",
        "temp_hp",
        "armor_class",
        "resources",
        "hidden_conditions",
        "dm_notes",
        "concentration",
    ]
    for key in forbidden_keys:
        assert key not in monster_proj, f"Forbidden key {key} leaked to player"

    char_proj = char_cb["projection"]
    assert char_proj["current_hp"] == 20

    for adj in combat_dict["pending_adjudications"]:
        assert adj.get("dm_hints") is None

    briefing = data["briefing"]
    assert "MANDATORY PLAYER COMBAT LOOP" in briefing
    dm_only_tools = [
        "combat_resolve_adjudication",
        "combat_open_reaction_window",
        "combat_resolve_aoe_spell",
        "combat_advance_turn",
    ]
    for tool in dm_only_tools:
        assert tool not in briefing, f"DM tool {tool} in player combat briefing"


def test_4_pre_session_dm_grant(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        combat_ai_tool_service,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture

    pre_auth = AIControllerAuthView(
        grant_id=uuid4(),
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        seat_id=table.dm_actor.seat_id,
        role="dm",
        session_id=None,
        generation=1,
        is_current_dm=False,
        temporary_instruction=None,
    )
    mock_ctrl = MagicMock()
    mock_ctrl.authenticate.return_value = pre_auth
    previous_override = app.dependency_overrides[get_ai_controller_service]
    app.dependency_overrides[get_ai_controller_service] = lambda: mock_ctrl

    try:
        client = TestClient(app)
        resp = _mcp_call(client, "fake-pre-session-token", "get_session_context", {})
        assert resp["isError"] is False
        data = resp["structuredContent"]["data"]
        assert data["mode"] == "pre_session"
        assert "combat" not in data
        assert data["briefing"] == render_briefing(role="dm", mode="pre_session")

        facade_res = combat_ai_tool_service.get_session_context("fake-pre-session-token", authenticated=pre_auth)
        assert facade_res["mode"] == "pre_session"
        assert "combat" not in facade_res
        assert facade_res["briefing"] == render_briefing(role="dm", mode="pre_session")
    finally:
        app.dependency_overrides[get_ai_controller_service] = previous_override


def test_5_guide_briefing_parity_and_length_cap() -> None:
    tokens_by_locale = {
        "en": {
            "current_turn": "current turn",
            "reaction_window": "reaction window",
            "adjudication": "adjudication",
            "wait": "wait_for_event",
        },
        "zh-TW": {
            "current_turn": "當前回合",
            "reaction_window": "反應窗口",
            "adjudication": "裁定",
            "wait": "wait_for_event",
        },
    }

    desc_row = next(r for r in tool_reference_rows(None) if r["name"] == "get_session_context")
    en_desc, zh_desc = desc_row["description"].split(" / ", 1)
    desc_by_locale = {
        "en": en_desc,
        "zh-TW": zh_desc,
    }

    for locale, tokens in tokens_by_locale.items():
        guide = render_guide(locale)
        assert tokens["current_turn"] in guide
        assert tokens["reaction_window"] in guide
        assert tokens["adjudication"] in guide
        assert tokens["wait"] in guide

        desc = desc_by_locale[locale]
        assert tokens["current_turn"] in desc
        assert tokens["reaction_window"] in desc
        assert tokens["adjudication"] in desc
        assert tokens["wait"] in desc

        for role in ("dm", "player"):
            briefing = render_briefing(role=role, mode="active_combat")
            assert tokens["current_turn"] in briefing
            assert tokens["reaction_window"] in briefing
            if role == "dm":
                assert tokens["adjudication"] in briefing
            assert tokens["wait"] in briefing
            assert len(briefing) <= BRIEFING_MAX_CHARS
