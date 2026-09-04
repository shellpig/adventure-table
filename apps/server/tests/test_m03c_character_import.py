from __future__ import annotations

import copy
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

from app.content.registry import ContentRegistry
from app.interop.character_import import CharacterImportService
from app.paths import resolve_content_root
from app.persistence.builder_drafts import character_build_drafts
from app.persistence.character_imports import character_import_records
from app.persistence.characters import characters, character_versions
from test_p1f_character_creation import _seed


FIXTURE_ROOT = Path(__file__).parent / "data" / "m03"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def _post_document(client, document: dict, *, dry_run: bool = False):
    suffix = "?dry_run=true" if dry_run else ""
    return client.post(
        f"/api/characters/import{suffix}",
        content=json.dumps(document).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def _install_import_service(client, engine, registry) -> None:
    client.app.state.content_registry = registry
    client.app.state.character_import_service = CharacterImportService(engine, registry)


def test_m03c_preview_and_commit_rebuild_full_version_chain_as_new_character() -> None:
    client, engine = _seed()
    registry = client.app.state.content_registry
    _install_import_service(client, engine, registry)

    document = _fixture("fixture_low_level_srd.json")
    first = copy.deepcopy(document["payload"]["versions"][0])
    first["version_no"] = 1
    first["version_kind"] = "create"
    first["parent_version_no"] = None
    first["superseded_by_version_no"] = None
    second = copy.deepcopy(first)
    second["version_no"] = 2
    second["version_kind"] = "build_edit"
    second["parent_version_no"] = 1
    document["payload"]["versions"] = [first, second]
    document["payload"]["current_version_no"] = 2

    preview = _post_document(client, document, dry_run=True)
    assert preview.status_code == 200, preview.text
    assert preview.json()["landing_mode"] == "character"
    assert preview.json()["unresolved_ref_count"] == 0

    committed = _post_document(client, document)
    assert committed.status_code == 200, committed.text
    body = committed.json()
    assert body["landing_mode"] == "character"
    imported_id = UUID(body["character_id"])
    assert imported_id != UUID(document["envelope"]["source_character_id"])

    with engine.connect() as connection:
        rows = connection.execute(
            select(character_versions)
            .where(character_versions.c.character_id == imported_id)
            .order_by(character_versions.c.version_no)
        ).mappings().all()
        assert [row["version_no"] for row in rows] == [1, 2]
        assert rows[1]["parent_version_id"] == rows[0]["id"]
        assert connection.scalar(
            select(func.count(character_import_records.c.id)).where(
                character_import_records.c.character_id == imported_id
            )
        ) == 1

    duplicate = _post_document(client, document, dry_run=True)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["duplicate_hint"]["count"] == 1
    engine.dispose()


def test_m03c_missing_pack_lands_as_fresh_create_draft() -> None:
    client, engine = _seed()
    full_registry = client.app.state.content_registry
    enabled = tuple(pack for pack in full_registry.enabled_pack_ids if pack != "xge")
    registry = ContentRegistry.from_root(resolve_content_root(), enabled)
    _install_import_service(client, engine, registry)

    document = _fixture("fixture_xge_dependent.json")
    preview = _post_document(client, document, dry_run=True)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["landing_mode"] == "draft"
    assert body["unresolved_ref_count"] > 0
    assert any(item["pack"] == "xge" for item in body["unresolved_refs"])

    committed = _post_document(client, document)
    assert committed.status_code == 200, committed.text
    draft_id = UUID(committed.json()["draft_id"])
    with engine.connect() as connection:
        row = connection.execute(
            select(character_build_drafts).where(character_build_drafts.c.id == draft_id)
        ).mappings().one()
        assert row["mode"] == "create"
        assert row["character_id"] is None
        assert row["base_version_id"] is None
        level_three = row["draft_payload"]["level_choices"][2]
        assert level_three["subclass_ref"] is None
        record = connection.execute(
            select(character_import_records).where(
                character_import_records.c.draft_id == draft_id
            )
        ).mappings().one()
        assert record["landing_mode"] == "draft"
    engine.dispose()


def test_m03c_state_only_unresolved_ref_warns_history_loss() -> None:
    client, engine = _seed()
    full_registry = client.app.state.content_registry
    enabled = tuple(pack for pack in full_registry.enabled_pack_ids if pack != "xge")
    registry = ContentRegistry.from_root(resolve_content_root(), enabled)
    _install_import_service(client, engine, registry)

    document = _fixture("fixture_low_level_srd.json")
    document["payload"]["current_state"]["state_payload"]["conditions"] = [
        {"condition_ref": "xge:condition:portable-test-condition", "note": None}
    ]
    preview = _post_document(client, document, dry_run=True)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["landing_mode"] == "draft_with_history_loss"
    assert body["unresolved_refs"] == [
        {
            "stable_key": "xge:condition:portable-test-condition",
            "pack": "xge",
            "kind": "condition",
            "origin": "state",
            "version_no": None,
        }
    ]
    engine.dispose()


def test_m03c_unresolved_ref_without_provenance_is_rejected_atomically() -> None:
    client, engine = _seed()
    full_registry = client.app.state.content_registry
    enabled = tuple(pack for pack in full_registry.enabled_pack_ids if pack != "xge")
    registry = ContentRegistry.from_root(resolve_content_root(), enabled)
    _install_import_service(client, engine, registry)

    document = _fixture("fixture_legacy_no_provenance.json")
    document["payload"]["versions"][0]["build_payload"]["race_ref"] = "xge:race:portable-test-race"
    response = _post_document(client, document)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "draft_reconstruction_unavailable"

    with engine.connect() as connection:
        assert connection.scalar(select(func.count(character_import_records.c.id))) == 0
        assert connection.scalar(select(func.count(characters.c.id))) == 0
        assert connection.scalar(select(func.count(character_build_drafts.c.id))) == 0
    engine.dispose()


def test_m03c_pydantic_special_cases_keep_machine_codes() -> None:
    client, engine = _seed()
    _install_import_service(client, engine, client.app.state.content_registry)

    bad_kind = _fixture("fixture_bad_version_kind.json")
    response = _post_document(client, bad_kind, dry_run=True)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_version_kind"

    bad_status = _fixture("fixture_low_level_srd.json")
    bad_status["envelope"]["schema_status"] = "future"
    response = _post_document(client, bad_status, dry_run=True)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "unsupported_schema_status"
    engine.dispose()


def test_m03c_version_chain_rejections_leave_no_state() -> None:
    client, engine = _seed()
    _install_import_service(client, engine, client.app.state.content_registry)

    document = _fixture("fixture_low_level_srd.json")
    second = copy.deepcopy(document["payload"]["versions"][0])
    second["version_no"] = 3
    second["parent_version_no"] = 1
    document["payload"]["versions"].append(second)
    document["payload"]["current_version_no"] = 3

    response = _post_document(client, document)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "version_chain_gap"
    with engine.connect() as connection:
        assert connection.scalar(select(func.count(character_import_records.c.id))) == 0
        assert connection.scalar(select(func.count(characters.c.id))) == 0
    engine.dispose()
