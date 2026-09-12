from __future__ import annotations

import asyncio

from fastapi.routing import APIRoute

from app.domain.rooms.ai_tools import WaitEventsInput
from app.mcp.guide import render_guide
from app.mcp.server import mcp_guide, router


def _body(response) -> str:
    return response.body.decode("utf-8")


def test_guide_returns_plain_text_without_auth() -> None:
    response = asyncio.run(mcp_guide("en"))
    assert response.status_code == 200
    assert response.media_type == "text/plain"
    assert response.headers["cache-control"] == "public, max-age=300"


def test_guide_supports_both_locales() -> None:
    en = _body(asyncio.run(mcp_guide("en")))
    zh = _body(asyncio.run(mcp_guide("zh-TW")))
    assert en != zh
    assert "Adventure Table AI Join Guide" in en
    assert "Adventure Table AI 接入指引" in zh


def test_guide_rejects_unknown_locale() -> None:
    response = asyncio.run(mcp_guide("ja"))
    assert response.status_code == 400
    assert "mcp_guide_locale_unsupported" in _body(response)


def test_guide_contains_three_join_paths() -> None:
    for locale in ("en", "zh-TW"):
        guide = render_guide(locale)
        assert "connector" in guide
        assert "Bearer" in guide
        assert "POST /mcp" in guide


def test_guide_client_sample_has_applicability_notice() -> None:
    assert "web chat should use the connector" in render_guide("en")
    assert "網頁版 chat" in render_guide("zh-TW")


def test_guide_contains_contract_sections() -> None:
    for locale in ("en", "zh-TW"):
        guide = render_guide(locale)
        for expected in (
            "MCP-Protocol-Version: 2026-07-28",
            "Mcp-Method",
            "Mcp-Name",
            "io.modelcontextprotocol/protocolVersion",
            "io.modelcontextprotocol/clientCapabilities",
            "get_session_context",
            "wait_for_event",
            "ai_token_unauthorized",
            "structuredContent",
            "mcp_invalid_request",
        ):
            assert expected in guide


def test_guide_wait_rule_matches_cap() -> None:
    maximum = WaitEventsInput.model_json_schema()["properties"]["timeout"]["maximum"]
    assert maximum == 120.0
    for locale in ("en", "zh-TW"):
        guide = render_guide(locale)
        assert str(int(maximum)) in guide
        assert "5" in guide


def test_guide_contains_no_secret() -> None:
    for locale in ("en", "zh-TW"):
        guide = render_guide(locale)
        for forbidden in (
            "SECRET_TOKEN",
            "SECRET_DC",
            "at_ai_example_secret",
            "Keep the lantern lit.",
            "00000000-0000-0000-0000-000000000000",
        ):
            assert forbidden not in guide


def test_guide_does_not_touch_db() -> None:
    guide_route = next(
        route for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/mcp/guide"
    )
    assert guide_route.dependant.dependencies == []
    response = asyncio.run(mcp_guide("en"))
    assert response.status_code == 200


def test_standalone_has_no_mcp_guide_route(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from tests.m03e_support import loaded_standalone

    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        assert TestClient(standalone.app).get("/mcp/guide?locale=en").status_code == 404
