from __future__ import annotations

import inspect

from app.mcp import guide as guide_module
from app.mcp.guide import render_guide
from app.mcp.tools import tool_reference_rows


def _tool_lines(guide: str) -> set[str]:
    return {
        line.split(" | ", 1)[0].removeprefix("- ")
        for line in guide.splitlines()
        if line.startswith("- ") and " | required:" in line
    }


def _player_rules(guide: str, locale: str) -> str:
    marker = "[Player rules]" if locale == "en" else "【Player 守則】"
    tail = guide.split(marker, 1)[1]
    return tail.split("\n\n", 1)[0]


def test_guide_lists_every_tool_definition() -> None:
    expected = {row["name"] for row in tool_reference_rows(None)}
    for locale in ("en", "zh-TW"):
        assert _tool_lines(render_guide(locale)) == expected


def test_guide_has_no_unknown_tool_names() -> None:
    expected = {row["name"] for row in tool_reference_rows(None)}
    for locale in ("en", "zh-TW"):
        assert _tool_lines(render_guide(locale)) <= expected


def test_guide_module_has_no_hardcoded_tool_names() -> None:
    source = inspect.getsource(guide_module)
    for row in tool_reference_rows(None):
        assert f'"{row["name"]}"' not in source
        assert f"'{row['name']}'" not in source


def test_guide_required_params_match_schema() -> None:
    rows = tool_reference_rows(None)
    for locale in ("en", "zh-TW"):
        guide = render_guide(locale)
        for row in rows:
            required = ", ".join(row["required_params"]) or "-"
            assert f"- {row['name']} | required: {required} |" in guide


def test_player_rules_do_not_mention_dm_tools() -> None:
    for locale in ("en", "zh-TW"):
        rules = _player_rules(render_guide(locale), locale)
        for forbidden in ("request_check", "post_narration", "set_stage_text"):
            assert forbidden not in rules
        for expected in (
            "post_action",
            "roll_pending",
            "quick_roll",
            "update_character_state",
            "whisper_dm",
        ):
            assert expected in rules
