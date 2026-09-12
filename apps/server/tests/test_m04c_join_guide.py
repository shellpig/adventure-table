from __future__ import annotations

import asyncio

from app.domain.rooms.ai_tools import WaitEventsInput
from app.mcp.guide import WAIT_RETRY_COUNT, WAIT_TIMEOUT_SECONDS, render_briefing, render_guide
from app.mcp.server import mcp_guide
from app.mcp.tools import tool_reference_rows


def test_m04c_guide_tracks_wait_schema_and_retry_policy() -> None:
    schema_max = WaitEventsInput.model_json_schema()["properties"]["timeout"]["maximum"]

    assert WAIT_TIMEOUT_SECONDS == schema_max == 120
    assert WAIT_RETRY_COUNT == 5

    for locale in ("en", "zh-TW"):
        guide = render_guide(locale)
        assert "/mcp" in guide
        assert "get_session_context" in guide
        assert "wait_for_event" in guide
        assert "120" in guide
        assert "5" in guide


def test_m04c_guide_covers_all_supported_join_paths_and_role_rules() -> None:
    guide_en = render_guide("en")
    guide_zh = render_guide("zh-TW")

    assert "ChatGPT Web / connector" in guide_en
    assert "MCP client (Bearer)" in guide_en
    assert "raw HTTP" in guide_en
    assert "Minimal outbound client example" in guide_en
    assert "curl -sS -X POST" in guide_en
    assert "Mcp-Session-Id" in guide_en
    assert "initialize is not required" in guide_en
    assert "post_narration" in guide_en
    assert "request_check" in guide_en
    assert "post_dialogue" in guide_en
    assert "post_action" in guide_en
    assert "Player does not have request_check" in guide_en

    assert "ChatGPT Web／connector" in guide_zh
    assert "MCP client（Bearer）" in guide_zh
    assert "純 HTTP" in guide_zh
    assert "DM 回應玩家時一律用 post_narration" in guide_zh
    assert "Player 沒有 request_check" in guide_zh


def test_m04c_briefing_is_mode_specific_and_scope_safe() -> None:
    pre_session = render_briefing(role="dm", mode="pre_session")
    dm = render_briefing(role="dm", mode="active_session")
    player = render_briefing(role="player", mode="active_session")

    assert "start_session" in pre_session
    assert "Refresh" in pre_session
    assert "/mcp/guide" in pre_session

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


def test_m04c_tool_reference_rows_are_derived_from_catalog_contract() -> None:
    all_rows = {row["name"]: row for row in tool_reference_rows(None)}
    player_rows = {row["name"] for row in tool_reference_rows("player")}
    dm_rows = {row["name"] for row in tool_reference_rows("dm")}

    assert "request_check" in dm_rows
    assert "request_check" not in player_rows
    assert "post_narration" in dm_rows
    assert "post_narration" not in player_rows
    assert "post_dialogue" in player_rows
    assert "wait_for_event" in player_rows & dm_rows

    wait_description = all_rows["wait_for_event"]["description"]
    assert "Key parameters and legal values" in wait_description
    assert "timeout (range=0.0..120.0; default=30.0)" in wait_description
    assert "Allowed roles" in wait_description
    assert "關鍵參數與合法值" in wait_description
    assert "可用角色" in wait_description

    request_description = all_rows["request_check"]["description"]
    assert "enum=" in request_description


def test_m04c_guide_endpoint_is_public_and_has_stable_locale_error() -> None:
    response = asyncio.run(mcp_guide("en"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert b"Adventure Table AI Join Guide" in response.body

    invalid = asyncio.run(mcp_guide("ja"))
    assert invalid.status_code == 400
    assert b"mcp_guide_locale_unsupported" in invalid.body
