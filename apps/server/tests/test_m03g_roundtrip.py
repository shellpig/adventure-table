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
from m03c_support import document, post_document, seeded_import


@contextmanager
def _standalone_client(
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


def _commit_fixture(client: TestClient, fixture_name: str) -> str:
    response = post_document(client, document(fixture_name))
    assert response.status_code == 201, response.text
    character_id = response.json()["character_id"]
    assert character_id is not None
    return character_id


def _export(client: TestClient, character_id: str) -> dict:
    response = client.get(f"/api/characters/{character_id}/export")
    assert response.status_code == 200, response.text
    return response.json()


def test_web_to_standalone_roundtrip_preserves_live_state_and_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_client, web_engine, _ = seeded_import()
    web_character_id = _commit_fixture(web_client, "fixture_multiclass_mixed.json")
    persisted = web_client.get(f"/api/characters/{web_character_id}")
    assert persisted.status_code == 200, persisted.text
    character = persisted.json()

    cleric_profile = next(
        profile
        for profile in character["build"]["spellcasting_profiles"]
        if profile["class_ref"] == "srd5.1:class:cleric"
        and profile["access_model"] == "prepared"
    )
    runtime_inventory = [
        *character["state"]["inventory_state"],
        {
            "entry_id": "inventory:runtime:m03g-dagger",
            "item_ref": "srd5.1:equipment:dagger",
            "quantity": 1,
            "equipped": False,
            "carried": True,
        },
    ]
    patch = web_client.patch(
        f"/api/characters/{web_character_id}/state",
        json={
            "expected_current_version_id": character["current_version_id"],
            "current_hp": character["state"]["current_hp"] - 3,
            "prepared_spells": [
                {
                    "spell_key": "srd5.1:spell:cure-wounds",
                    "source_profile_id": cleric_profile["profile_id"],
                }
            ],
            "inventory_state": runtime_inventory,
        },
    )
    assert patch.status_code == 200, patch.text

    web_export = _export(web_client, web_character_id)
    exported_state = web_export["payload"]["current_state"]["state_payload"]
    assert web_export["envelope"]["source_app"]["channel"] == "web"
    assert exported_state["prepared_spells"] == [
        {
            "spell_key": "srd5.1:spell:cure-wounds",
            "source_profile_id": cleric_profile["profile_id"],
            "source_access_entry_id": None,
        }
    ]
    assert any(
        item["entry_id"] == "inventory:runtime:m03g-dagger"
        for item in exported_state["inventory_state"]
    )
    web_engine.dispose()

    with _standalone_client(monkeypatch, tmp_path) as (standalone_client, _):
        preview = post_document(standalone_client, web_export, dry_run=True)
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert preview_body["landing_mode"] == "character"
        assert preview_body["unresolved_ref_count"] == 0

        committed = post_document(standalone_client, web_export)
        assert committed.status_code == 201, committed.text
        standalone_character_id = committed.json()["character_id"]
        assert standalone_character_id is not None

        standalone_export = _export(standalone_client, standalone_character_id)
        assert standalone_export["envelope"]["source_app"]["channel"] == "standalone"
        assert standalone_export["payload"] == web_export["payload"]
        history = standalone_client.get(
            f"/api/characters/{standalone_character_id}/versions"
        )
        assert history.status_code == 200, history.text
        assert [entry["version_no"] for entry in history.json()] == [1, 2]


def test_standalone_to_web_roundtrip_preserves_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _standalone_client(monkeypatch, tmp_path) as (standalone_client, _):
        standalone_character_id = _commit_fixture(
            standalone_client,
            "fixture_xge_dependent.json",
        )
        standalone_export = _export(standalone_client, standalone_character_id)
        assert standalone_export["envelope"]["source_app"]["channel"] == "standalone"
        assert standalone_export["payload"]["character"]["name"]
        assert standalone_export["payload"]["versions"][-1]["build_payload"][
            "character_level"
        ] == 3

    web_client, web_engine, _ = seeded_import()
    preview = post_document(web_client, standalone_export, dry_run=True)
    assert preview.status_code == 200, preview.text
    assert preview.json()["landing_mode"] == "character"
    assert preview.json()["unresolved_ref_count"] == 0

    committed = post_document(web_client, standalone_export)
    assert committed.status_code == 201, committed.text
    web_character_id = committed.json()["character_id"]
    assert web_character_id is not None

    web_export = _export(web_client, web_character_id)
    assert web_export["envelope"]["source_app"]["channel"] == "web"
    assert web_export["payload"] == standalone_export["payload"]
    web_engine.dispose()
