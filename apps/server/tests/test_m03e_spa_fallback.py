from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from tests.m03e_support import loaded_standalone


def test_spa_history_fallback_serves_index_and_real_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        client = TestClient(standalone.app)
        sheet = client.get("/characters/00000000-0000-4000-8000-000000000001")
        asset = client.get("/assets/some.css")
        random_path = client.get("/random/path/without/api")

    assert sheet.status_code == 200
    assert "M03-E SPA" in sheet.text
    assert asset.status_code == 200
    assert "display: block" in asset.text
    assert random_path.status_code == 200
    assert "M03-E SPA" in random_path.text


def test_spa_fallback_never_turns_unknown_api_paths_into_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        client = TestClient(standalone.app)
        shallow = client.get("/api/some-not-exist")
        deep = client.get("/api/characters/deep/not-exist")

    assert shallow.status_code == 404
    assert deep.status_code == 404
    assert "M03-E SPA" not in shallow.text
    assert "M03-E SPA" not in deep.text
