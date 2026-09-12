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


def guide_tool_names() -> GuideToolNames:
    """Return guide-facing names from the catalog order instead of duplicating literals."""

    names = [row["name"] for row in tool_reference_rows(None)]
    if len(names) != 16:
        raise RuntimeError("MCP tool catalog shape changed; update GuideToolNames mapping")
    return GuideToolNames(*names)


__all__ = ["GuideToolNames", "guide_tool_names"]
