from __future__ import annotations

from pathlib import Path

import pytest

from m03c_support import post_document, seeded_import
from m03g_support import commit_fixture, export_character, standalone_client


def test_web_to_standalone_roundtrip_preserves_live_state_and_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_client, web_engine, _ = seeded_import()
    web_character_id = commit_fixture(web_client, "fixture_multiclass_mixed.json")
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

    web_export = export_character(web_client, web_character_id)
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

    with standalone_client(monkeypatch, tmp_path) as (standalone, _):
        preview = post_document(standalone, web_export, dry_run=True)
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert preview_body["landing_mode"] == "character"
        assert preview_body["unresolved_ref_count"] == 0

        committed = post_document(standalone, web_export)
        assert committed.status_code == 201, committed.text
        standalone_character_id = committed.json()["character_id"]
        assert standalone_character_id is not None

        standalone_export = export_character(standalone, standalone_character_id)
        assert standalone_export["envelope"]["source_app"]["channel"] == "standalone"
        assert standalone_export["payload"] == web_export["payload"]
        history = standalone.get(f"/api/characters/{standalone_character_id}/versions")
        assert history.status_code == 200, history.text
        assert [entry["version_no"] for entry in history.json()] == [1, 2]


def test_standalone_to_web_roundtrip_preserves_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with standalone_client(monkeypatch, tmp_path) as (standalone, _):
        standalone_character_id = commit_fixture(
            standalone,
            "fixture_xge_dependent.json",
        )
        standalone_export = export_character(standalone, standalone_character_id)
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

    web_export = export_character(web_client, web_character_id)
    assert web_export["envelope"]["source_app"]["channel"] == "web"
    assert web_export["payload"] == standalone_export["payload"]
    web_engine.dispose()
