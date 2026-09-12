from __future__ import annotations

from uuid import uuid4

from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.mcp.tools import tool_catalog, tool_reference_rows

PLAYER_ACTIVE = {
    "get_session_context", "get_character_context", "post_dialogue", "post_action",
    "post_ooc", "whisper_dm", "roll_pending", "submit_physical_roll", "quick_roll",
    "update_character_state", "get_pending_events", "wait_for_event",
}
# The DM catalog is one fixed set before and after start_session (2026-09-12
# revision): a connector that snapshots tools/list in the Lobby must not need a
# Refresh once the Session starts. State gating lives in call_tool.
DM_CATALOG = {
    "get_session_context", "start_session", "post_dialogue", "post_action", "post_ooc",
    "post_narration", "set_stage_text", "request_check", "roll_pending",
    "submit_physical_roll", "update_character_state", "get_pending_events", "wait_for_event",
}


def _auth(role: str, active: bool) -> AIControllerAuthView:
    return AIControllerAuthView(
        grant_id=uuid4(), room_id=uuid4(), campaign_id=uuid4(), seat_id=uuid4(),
        role=role, session_id=uuid4() if active else None, generation=1,
        is_current_dm=role == "dm" and active, temporary_instruction=None,
    )


def test_every_description_has_en_and_zh() -> None:
    for row in tool_reference_rows(None):
        description = row["description"]
        assert "When to use:" in description
        assert "使用時機：" in description
        assert "Key parameters and legal values:" in description
        assert "關鍵參數與合法值：" in description


def test_description_minimum_length() -> None:
    for row in tool_reference_rows(None):
        english = row["description"].split(" / ", 1)[0]
        assert len(english) >= 80, (row["name"], len(english))


def test_every_tool_has_specific_when_to_use_text() -> None:
    when_sections = {}
    for row in tool_reference_rows(None):
        description = row["description"]
        section = description.split("When to use:", 1)[1].split("Key parameters", 1)[0].strip()
        assert row["name"] not in section
        when_sections[row["name"]] = section
    assert len(set(when_sections.values())) == len(when_sections)


def test_role_scoped_catalog_is_fixed_per_role() -> None:
    assert {item["name"] for item in tool_catalog(_auth("player", True))} == PLAYER_ACTIVE
    assert {item["name"] for item in tool_catalog(_auth("dm", True))} == DM_CATALOG
    assert tool_catalog(_auth("dm", False)) == tool_catalog(_auth("dm", True))
    assert "quick_roll" not in DM_CATALOG
    assert "whisper_dm" not in DM_CATALOG
    assert "start_session" not in PLAYER_ACTIVE


def test_descriptions_state_when_the_call_is_accepted() -> None:
    rows = {row["name"]: row["description"] for row in tool_reference_rows(None)}
    assert "afterwards it returns pre_session_only" in rows["start_session"]
    assert "before and after the Session starts" in rows["get_session_context"]
    for name in DM_CATALOG - {"get_session_context", "start_session"}:
        assert "active_session_required" in rows[name], name
        assert "active_session_required" in rows[name].split(" / ", 1)[1], name


def test_request_check_description_prevents_duplicate_roll_narration() -> None:
    description = {
        row["name"]: row["description"] for row in tool_reference_rows(None)
    }["request_check"]
    assert "automatically posts" in description
    assert "自動" in description
    assert "do not call post_narration" in description
    assert "不要只為重複要求" in description
