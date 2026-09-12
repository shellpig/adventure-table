from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from tests.m03e_support import loaded_standalone


def test_standalone_does_not_mount_mcp_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        app = standalone.app
        assert "/mcp" not in app.openapi()["paths"]

        response = TestClient(app).post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}},
        )
        # The standalone SPA history fallback registers GET /{full_path:path},
        # so an unmounted POST /mcp answers 405 whenever SPA assets exist and
        # 404 otherwise. Either way no MCP handler answered.
        assert response.status_code in {404, 405}
        assert "jsonrpc" not in response.text


def test_standalone_has_no_oauth_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        app = standalone.app
        paths = app.openapi()["paths"]
        oauth_paths = (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-authorization-server",
            "/mcp/oauth/register",
            "/mcp/oauth/authorize",
            "/mcp/oauth/token",
            "/mcp/oauth/revoke",
        )
        for path in oauth_paths:
            assert path not in paths

        client = TestClient(app)
        for path in oauth_paths:
            response = client.get(path) if path.startswith("/.well-known/") else client.post(path)
            assert response.status_code in {404, 405}
