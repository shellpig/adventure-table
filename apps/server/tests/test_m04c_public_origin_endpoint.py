"""M04-C: the Human UI reads the configured public MCP origin so the AI Join
Kit can print a remote URL next to the browser-origin (local) URL."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.config import settings
from app.mcp import router
from app.mcp.server import router as server_router

PUBLIC = "https://table.example.ts.net"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_public_origin_endpoint_returns_configured_origin_without_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "mcp_public_origin", PUBLIC + "/")

    response = _client().get("/api/mcp/public-origin")

    assert response.status_code == 200
    assert response.json() == {"public_origin": PUBLIC}


def test_public_origin_endpoint_returns_null_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "mcp_public_origin", None)

    response = _client().get("/api/mcp/public-origin")

    assert response.status_code == 200
    assert response.json() == {"public_origin": None}


def test_public_origin_endpoint_needs_no_auth_and_no_db() -> None:
    route = next(
        route for route in server_router.routes
        if isinstance(route, APIRoute) and route.path == "/api/mcp/public-origin"
    )
    assert route.dependant.dependencies == []
    assert route.methods == {"GET"}


def test_standalone_has_no_public_origin_route(tmp_path, monkeypatch) -> None:
    from tests.m03e_support import loaded_standalone

    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        assert TestClient(standalone.app).get("/api/mcp/public-origin").status_code == 404
