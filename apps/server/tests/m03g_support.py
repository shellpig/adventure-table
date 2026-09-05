from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import importlib
from pathlib import Path
import sys
from types import ModuleType

from fastapi.testclient import TestClient
import pytest

from app import launcher
from app.config import settings
from m03c_support import document, post_document


@contextmanager
def standalone_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    disabled_pack: str | None = None,
) -> Iterator[tuple[TestClient, ModuleType]]:
    """Run the real standalone app against one migrated file-backed SQLite DB."""

    database_path = tmp_path / "adventure-table.sqlite3"
    spa_root = tmp_path / "web"
    assets = spa_root / "assets"
    assets.mkdir(parents=True)
    (spa_root / "index.html").write_text(
        "<html><body>M03-G integration SPA</body></html>",
        encoding="utf-8",
    )
    (assets / "app.css").write_text("body { display: block; }", encoding="utf-8")

    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("ADVENTURE_TABLE_SPA_ROOT", str(spa_root))
    if disabled_pack is not None:
        enabled = tuple(
            pack for pack in settings.enabled_content_packs if pack != disabled_pack
        )
        monkeypatch.setattr(settings, "enabled_content_packs", enabled)

    launcher.run_migrations()
    sys.modules.pop("app.standalone", None)
    standalone = importlib.import_module("app.standalone")
    try:
        with TestClient(standalone.app) as client:
            yield client, standalone
    finally:
        engine = getattr(standalone.app.state, "character_engine", None)
        if engine is not None:
            engine.dispose()
        sys.modules.pop("app.standalone", None)


def commit_fixture(client: TestClient, fixture_name: str) -> str:
    response = post_document(client, document(fixture_name))
    assert response.status_code == 201, response.text
    character_id = response.json()["character_id"]
    assert character_id is not None
    return character_id


def export_character(client: TestClient, character_id: str) -> dict:
    response = client.get(f"/api/characters/{character_id}/export")
    assert response.status_code == 200, response.text
    return response.json()
