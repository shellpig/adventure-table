from __future__ import annotations

from app.mcp.protocol import CACHE_SCOPE, CACHE_TTL_MS, MCP_PROTOCOL_VERSION, result_payload
from app.mcp.server import _discover_instructions


def test_discover_instructions_use_absolute_origin_and_guide() -> None:
    instructions = _discover_instructions("https://table.example")
    assert "get_session_context" in instructions
    assert "https://table.example/mcp/guide?locale=en" in instructions
    assert "https://table.example/mcp/guide?locale=zh-TW" in instructions


def test_discover_cache_contract_is_unchanged() -> None:
    payload = result_payload(
        "discover-1",
        {
            "supportedVersions": [MCP_PROTOCOL_VERSION],
            "capabilities": {"tools": {}},
            "instructions": _discover_instructions("https://table.example"),
        },
        cacheable=True,
    )
    assert payload["result"]["ttlMs"] == CACHE_TTL_MS == 30_000
    assert payload["result"]["cacheScope"] == CACHE_SCOPE == "private"
    assert payload["result"]["supportedVersions"] == ["2026-07-28"]
