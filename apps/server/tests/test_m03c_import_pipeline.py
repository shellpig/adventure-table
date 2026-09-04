from __future__ import annotations

import pytest

from app.interop.character_import import CharacterImportError
from app.interop.json_schema import CharacterExport
from m03c_support import document, seeded_import


def _preview(service, payload: dict):
    return service.preview(CharacterExport.model_validate(payload))


def test_full_registry_imports_low_level_fixture_as_character() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    result = _preview(service, document("fixture_low_level_srd.json"))
    assert result.landing_mode == "character"
    assert result.unresolved_refs == ()
    engine.dispose()


def test_missing_xge_lands_as_draft_with_build_origins() -> None:
    client, engine, _ = seeded_import(disabled_pack="xge")
    service = client.app.state.character_import_service
    result = _preview(service, document("fixture_xge_dependent.json"))
    assert result.landing_mode == "draft"
    assert result.unresolved_refs
    assert all(item.origin == "build" for item in result.unresolved_refs)
    assert all(item.version_no is not None for item in result.unresolved_refs)
    assert any(item.pack == "xge" for item in result.unresolved_refs)
    engine.dispose()


def test_missing_phb2014_lands_as_draft_with_exact_missing_pack() -> None:
    client, engine, _ = seeded_import(disabled_pack="phb2014")
    service = client.app.state.character_import_service
    result = _preview(service, document("fixture_multiclass_mixed.json"))
    assert result.landing_mode == "draft"
    assert result.unresolved_refs
    assert {item.pack for item in result.unresolved_refs} == {"phb2014"}
    engine.dispose()


def test_state_only_missing_inventory_warns_history_loss() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    result = _preview(service, document("fixture_state_only_missing_inventory.json"))
    assert result.landing_mode == "draft_with_history_loss"
    assert result.unresolved_refs
    assert {item.origin for item in result.unresolved_refs} == {"state"}
    engine.dispose()


def test_legacy_missing_provenance_cannot_reconstruct_draft() -> None:
    client, engine, _ = seeded_import(disabled_pack="xge")
    service = client.app.state.character_import_service
    payload = document("fixture_legacy_no_provenance.json")
    payload["payload"]["versions"][0]["build_payload"]["race_ref"] = "xge:race:portable-test-race"
    with pytest.raises(CharacterImportError) as caught:
        _preview(service, payload)
    assert caught.value.code == "draft_reconstruction_unavailable"
    engine.dispose()


def test_invalid_build_shape_is_rejected() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    payload = document()
    payload["payload"]["versions"][0]["build_payload"]["class_progression"] = [
        "srd5.1:race:human"
    ]
    with pytest.raises(CharacterImportError) as caught:
        _preview(service, payload)
    assert caught.value.code == "invalid_build_shape"
    engine.dispose()


def test_invalid_state_shape_is_rejected() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    payload = document()
    payload["payload"]["current_state"]["state_payload"]["conditions"] = [
        {"condition_ref": "srd5.1:spell:acid-arrow"}
    ]
    with pytest.raises(CharacterImportError) as caught:
        _preview(service, payload)
    assert caught.value.code == "state_shape_invalid"
    engine.dispose()


def test_invalid_builder_provenance_fixture_is_rejected() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    with pytest.raises(CharacterImportError) as caught:
        _preview(service, document("fixture_bad_builder_provenance.json"))
    assert caught.value.code == "invalid_builder_provenance"
    engine.dispose()


def test_ruleset_mismatch_fixture_is_rejected() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    with pytest.raises(CharacterImportError) as caught:
        _preview(service, document("fixture_bad_ruleset_mismatch.json"))
    assert caught.value.code == "ruleset_mismatch"
    engine.dispose()


def test_lineage_cycle_fixture_returns_cycle_code_before_direction_code() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    with pytest.raises(CharacterImportError) as caught:
        _preview(service, document("fixture_bad_lineage_cycle.json"))
    assert caught.value.code == "version_lineage_cycle"
    engine.dispose()


def test_lineage_self_reference_is_rejected() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    payload = document()
    payload["payload"]["versions"][0]["parent_version_no"] = 1
    with pytest.raises(CharacterImportError) as caught:
        _preview(service, payload)
    assert caught.value.code == "version_lineage_self_reference"
    engine.dispose()


def test_lineage_direction_is_rejected_when_not_a_cycle() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    payload = document("fixture_bad_lineage_cycle.json")
    payload["payload"]["versions"][1]["parent_version_no"] = None
    with pytest.raises(CharacterImportError) as caught:
        _preview(service, payload)
    assert caught.value.code == "version_lineage_direction_invalid"
    engine.dispose()


def test_resolved_but_semantically_invalid_build_refs_are_rejected() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    payload = document()
    build = payload["payload"]["versions"][0]["build_payload"]
    build["race_ref"] = "srd5.1:race:elf"
    build["subrace_ref"] = "srd5.1:subrace:hill-dwarf"
    with pytest.raises(CharacterImportError) as caught:
        _preview(service, payload)
    assert caught.value.code == "build_references_invalid"
    engine.dispose()


def test_resolved_but_inconsistent_state_is_rejected() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    payload = document()
    payload["payload"]["current_state"]["state_payload"]["current_hp"] = 999
    with pytest.raises(CharacterImportError) as caught:
        _preview(service, payload)
    assert caught.value.code == "state_inconsistent_with_build"
    engine.dispose()
