from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.api.meta import Capabilities
from app.main import app as web_app
from tests.m03e_support import loaded_standalone


def test_web_capabilities_are_m03_safe_defaults() -> None:
    response = TestClient(web_app).get("/api/meta/capabilities")

    assert response.status_code == 200
    payload = Capabilities.model_validate(response.json())
    assert payload.channel == "web"
    assert payload.database_path is None
    assert payload.capabilities.character_builder is True
    assert payload.capabilities.character_import_export is True
    assert payload.capabilities.room is False
    assert payload.capabilities.campaign is False
    assert payload.capabilities.session is False


def test_standalone_capabilities_identify_channel_and_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        response = TestClient(standalone.app).get("/api/meta/capabilities")

    assert response.status_code == 200
    payload = Capabilities.model_validate(response.json())
    assert payload.channel == "standalone"
    assert payload.capabilities.character_builder is True
    assert payload.capabilities.character_import_export is True
    assert payload.capabilities.room is False
    assert payload.database_path == str((tmp_path / "adventure-table.sqlite3").resolve())
