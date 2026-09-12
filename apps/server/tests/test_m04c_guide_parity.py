from __future__ import annotations

import inspect

from app.mcp import guide as guide_module
from app.mcp.guide import render_guide
from app.mcp.tools import tool_reference_rows


def _player_rules(guide: str, *, locale: str) -> str:
    if locale == "en":
        return guide.split("[Player rules]", 1)[1]
    return guide.split("【Player 守則】", 1)[1]


def test_guide_lists_every_tool_definition_with_required_params() -> None:
    rows = tool_reference_rows(None)
    for locale in ("en", "zh-TW"):
        guide = render_guide(locale)
        for row in rows:
            required = ", ".join(row["required_params"]) or "-"
            assert f"- {row['name']} | required: {required} |" in guide


def test_guide_module_has_no_hardcoded_catalog_tool_names() -> None:
    source = inspect.getsource(guide_module)
    for row in tool_reference_rows(None):
        assert f'"{row["name"]}"' not in source
        assert f"'{row['name']}'" not in source


def test_player_rules_do_not_mention_dm_only_tools() -> None:
    for locale in ("en", "zh-TW"):
        rules = _player_rules(render_guide(locale), locale=locale)
        assert "request_check" not in rules
        assert "post_narration" not in rules
        assert "set_stage_text" not in rules
        assert "post_action" in rules
        assert "roll_pending" in rules
