from __future__ import annotations

from app.mcp.tools import tool_reference_rows


def test_m04c_tool_descriptions_have_substantive_bilingual_sections() -> None:
    rows = tool_reference_rows(None)

    assert rows
    for row in rows:
        description = row["description"]
        english, separator, zh_tw = description.partition(" / ")

        assert separator == " / ", row["name"]
        assert len(english) >= 80, row["name"]
        assert "When to use:" in english, row["name"]
        assert "Key parameters and legal values:" in english, row["name"]
        assert "使用時機：" in zh_tw, row["name"]
        assert "關鍵參數與合法值：" in zh_tw, row["name"]
