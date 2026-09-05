from __future__ import annotations

from pathlib import Path

import pytest

from m03c_support import document, post_document, table_counts
from m03g_support import commit_fixture, standalone_client


def test_missing_xge_lands_as_persisted_builder_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = document("fixture_xge_dependent.json")
    with standalone_client(
        monkeypatch,
        tmp_path,
        disabled_pack="xge",
    ) as (standalone, _):
        preview = post_document(standalone, payload, dry_run=True)
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert preview_body["landing_mode"] == "draft"
        assert preview_body["unresolved_ref_count"] > 0
        assert {
            (entry["pack"], entry["origin"])
            for entry in preview_body["unresolved_refs"]
        } == {("xge", "build")}

        committed = post_document(standalone, payload)
        assert committed.status_code == 201, committed.text
        body = committed.json()
        assert body["landing_mode"] == "draft"
        assert body["character_id"] is None
        assert body["draft_id"] is not None

        draft = standalone.get(f"/api/character-builder/drafts/{body['draft_id']}")
        assert draft.status_code == 200, draft.text
        draft_payload = draft.json()["draft"]["draft_payload"]
        assert draft_payload["target_level"] == 3


def test_state_only_missing_ref_lands_as_history_loss_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = document("fixture_state_only_missing_inventory.json")
    with standalone_client(monkeypatch, tmp_path) as (standalone, _):
        preview = post_document(standalone, payload, dry_run=True)
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["landing_mode"] == "draft_with_history_loss"
        assert body["unresolved_ref_count"] > 0
        assert {entry["origin"] for entry in body["unresolved_refs"]} == {"state"}

        committed = post_document(standalone, payload)
        assert committed.status_code == 201, committed.text
        committed_body = committed.json()
        assert committed_body["landing_mode"] == "draft_with_history_loss"
        assert committed_body["character_id"] is None
        assert committed_body["draft_id"] is not None


def test_duplicate_hint_does_not_block_second_character(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = document("fixture_low_level_srd.json")
    with standalone_client(monkeypatch, tmp_path) as (standalone, _):
        first_id = commit_fixture(standalone, "fixture_low_level_srd.json")

        preview = post_document(standalone, payload, dry_run=True)
        assert preview.status_code == 200, preview.text
        duplicate_hint = preview.json()["duplicate_hint"]
        assert duplicate_hint is not None
        assert duplicate_hint["count"] == 1

        second = post_document(standalone, payload)
        assert second.status_code == 201, second.text
        second_id = second.json()["character_id"]
        assert second_id is not None
        assert second_id != first_id

        characters = standalone.get("/api/characters")
        assert characters.status_code == 200, characters.text
        ids = {entry["id"] for entry in characters.json()}
        assert {first_id, second_id}.issubset(ids)


def test_legacy_missing_pack_rejection_is_atomic_in_standalone_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = document("fixture_legacy_no_provenance.json")
    payload["payload"]["versions"][-1]["build_payload"]["race_ref"] = (
        "xge:race:portable-test-race"
    )
    with standalone_client(
        monkeypatch,
        tmp_path,
        disabled_pack="xge",
    ) as (standalone, module):
        # Initialize the standalone repository/engine before taking the atomicity snapshot.
        listed = standalone.get("/api/characters")
        assert listed.status_code == 200, listed.text
        engine = module.app.state.character_engine
        before = table_counts(engine)

        response = post_document(standalone, payload)
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "draft_reconstruction_unavailable"
        assert table_counts(engine) == before
