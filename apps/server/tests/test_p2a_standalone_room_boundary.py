from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest

from tests.m03e_support import loaded_standalone


def test_standalone_never_mounts_room_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        room_routes = [
            route.path
            for route in standalone.app.routes
            if isinstance(route, APIRoute) and route.path.startswith("/api/rooms")
        ]
        client = TestClient(standalone.app)
        create = client.post(
            "/api/rooms",
            json={"name": "Must Not Exist", "password": "secret pass"},
        )
        heartbeat = client.post(
            "/api/rooms/00000000-0000-0000-0000-000000000000/access/heartbeat"
        )
        capabilities = client.get("/api/meta/capabilities")

    assert room_routes == []
    assert create.status_code in {404, 405}
    assert heartbeat.status_code in {404, 405}
    assert capabilities.status_code == 200
    assert capabilities.json()["capabilities"]["room"] is False
