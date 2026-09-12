from __future__ import annotations

import inspect
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.domain.rooms.ai_tools import AIToolApplicationService
from app.mcp.guide import WAIT_RETRY_COUNT, render_briefing, render_guide
from app.mcp.protocol import CACHE_SCOPE, CACHE_TTL_MS, MCP_PROTOCOL_VERSION, result_payload
from app.mcp.server import mcp_guide
from app.mcp.tools import tool_catalog, tool_reference_rows
from tests.m03e_support import loaded_standalone


PLAYER_ACTIVE_TOOLS = {
    "get_session_context",
    "get_character_context",
    "post_dialogue",
    "post_action",
    "post_ooc",
    "whisper_dm",
    "roll_pending",
    "submit_physical_roll",
    "quick_roll",
    "update_character_state",
    "get_pending_events",
    "wait_for_event",
}
DM_ACTIVE_TOOLS = {
    "get_session_context",
    "post_dialogue",
    "post_action",
    "post_ooc",
    "post_narration",
    "set_stage_text",
    "request_check",
    "roll_pending",
    "submit_physical_roll",
    "update_character_state",
    "get_pending_events",
    "wait_for_event",
}


def _auth(*, role: str, active: bool) -> AIControllerAuthView:
    return AIControllerAuthView(
        grant_id=uuid4(),
        room_id=uuid4(),
        campaign_id=uuid4(),
        seat_id=uuid4(),
        role=role,
        session_id=uuid4() if active else None,
        generation=1,
        is_current_dm=role == "dm" and active,
        temporary_instruction="Keep the lantern lit.",
    )


def test_m04c_public_guide_is_static_secret_free_and_db_independent() -> None:
    handler_source = inspect.getsource(mcp_guide)
    assert "Depends(" not in handler_source
    assert "database" not in handler_source.lower()

    for locale in ("en", "zh-TW"):
        guide = render_guide(locale)
        assert "<AI_JOIN_TOKEN>" in guide
        assert "at_ai_" not in guide
        assert "secret_hash" not in guide
        assert "token_hint" not in guide
        assert "Keep the lantern lit." not in guide


def test_m04c_standalone_app_does_not_mount_web_guide(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        response = TestClient(standalone.app).get("/mcp/guide?locale=en")

    assert response.status_code == 404


def test_m04c_active_tool_catalogs_are_exact_and_role_scoped() -> None:
    player_tools = {tool["name"] for tool in tool_catalog(_auth(role="player", active=True))}
    dm_tools = {tool["name"] for tool in tool_catalog(_auth(role="dm", active=True))}

    assert player_tools == PLAYER_ACTIVE_TOOLS
    assert dm_tools == DM_ACTIVE_TOOLS
    assert "request_check" not in player_tools
    assert "post_narration" not in player_tools
    assert "quick_roll" not in dm_tools
    assert "whisper_dm" not in dm_tools


def test_m04c_pre_session_dm_catalog_stays_minimal() -> None:
    names = {tool["name"] for tool in tool_catalog(_auth(role="dm", active=False))}
    assert names == {"get_session_context", "start_session"}


def test_m04c_tool_reference_and_wire_catalog_share_descriptions() -> None:
    auth = _auth(role="player", active=True)
    wire = {tool["name"]: tool for tool in tool_catalog(auth)}
    reference = {row["name"]: row for row in tool_reference_rows("player")}

    assert set(wire) == PLAYER_ACTIVE_TOOLS
    for name, tool in wire.items():
        assert tool["description"] == reference[name]["description"]
        assert "When to use" in tool["description"]
        assert "Key parameters and legal values" in tool["description"]
        assert "Allowed roles" in tool["description"]
        assert "使用時機" in tool["description"]
        assert "關鍵參數與合法值" in tool["description"]
        assert "可用角色" in tool["description"]


def test_m04c_briefings_are_role_scoped_and_keep_temp_instruction_separate() -> None:
    dm = render_briefing(role="dm", mode="active_session")
    player = render_briefing(role="player", mode="active_session")
    pre = render_briefing(role="dm", mode="pre_session")

    assert "post_narration" in dm
    assert "request_check" in dm
    assert "quick_roll" not in dm
    assert "whisper_dm" not in dm

    assert "post_dialogue" in player
    assert "post_action" in player
    assert "roll_pending" in player
    assert "request_check" not in player
    assert "post_narration" not in player
    assert "set_stage_text" not in player

    assert "start_session" in pre
    assert "Keep the lantern lit." not in dm
    assert "Keep the lantern lit." not in player
    assert "Keep the lantern lit." not in pre

    context_source = inspect.getsource(AIToolApplicationService.get_session_context)
    assert '"briefing"' in context_source
    assert '"temporary_instruction"' in context_source


def test_m04c_wait_retry_count_is_guide_policy_not_server_counter() -> None:
    wait_source = inspect.getsource(AIToolApplicationService.wait_for_event)
    assert WAIT_RETRY_COUNT == 5
    assert "WAIT_RETRY_COUNT" not in wait_source
    assert "range(5)" not in wait_source
    assert "for " not in wait_source
    assert "while " not in wait_source


def test_m04c_discover_cache_contract_is_unchanged() -> None:
    payload = result_payload(
        "discover-1",
        {
            "supportedVersions": [MCP_PROTOCOL_VERSION],
            "capabilities": {"tools": {}},
            "instructions": "GET /mcp/guide",
        },
        cacheable=True,
    )

    assert payload["result"]["ttlMs"] == CACHE_TTL_MS == 30_000
    assert payload["result"]["cacheScope"] == CACHE_SCOPE == "private"
    assert payload["result"]["supportedVersions"] == ["2026-07-28"]
    assert payload["result"]["instructions"] == "GET /mcp/guide"
