from __future__ import annotations

from dataclasses import dataclass

from app.mcp.tools import tool_reference_rows


@dataclass(frozen=True)
class GuideToolNames:
    context: str
    start: str
    character_context: str
    dialogue: str
    action: str
    ooc: str
    whisper_dm: str
    narration: str
    stage_text: str
    request_check: str
    roll_pending: str
    physical_roll: str
    quick_roll: str
    character_state: str
    pending_events: str
    wait_event: str


_EXPECTED = {
    "get_session_context",
    "start_session",
    "get_character_context",
    "post_dialogue",
    "post_action",
    "post_ooc",
    "whisper_dm",
    "post_narration",
    "set_stage_text",
    "request_check",
    "roll_pending",
    "submit_physical_roll",
    "quick_roll",
    "update_character_state",
    "get_pending_events",
    "wait_for_event",
}


def guide_tool_names() -> GuideToolNames:
    """Resolve guide-facing names by identity, never by catalog position."""

    available = {row["name"] for row in tool_reference_rows(None)}
    if available != _EXPECTED:
        missing = sorted(_EXPECTED - available)
        extra = sorted(available - _EXPECTED)
        raise RuntimeError(f"MCP tool catalog shape changed; missing={missing}, extra={extra}")
    return GuideToolNames(
        context="get_session_context",
        start="start_session",
        character_context="get_character_context",
        dialogue="post_dialogue",
        action="post_action",
        ooc="post_ooc",
        whisper_dm="whisper_dm",
        narration="post_narration",
        stage_text="set_stage_text",
        request_check="request_check",
        roll_pending="roll_pending",
        physical_roll="submit_physical_roll",
        quick_roll="quick_roll",
        character_state="update_character_state",
        pending_events="get_pending_events",
        wait_event="wait_for_event",
    )


__all__ = ["GuideToolNames", "guide_tool_names"]
