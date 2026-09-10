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
        assert response.status_code == 404
