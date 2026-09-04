from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.content.schemas import ContentManifest
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.interop.character_export import (
    _pack_requirement,
    build_character_export,
    stable_key_refs_summary,
)
from test_p1f_character_creation import _seed


def test_m03b_stable_key_summary_counts_unique_refs_per_ownership_domain() -> None:
    assert stable_key_refs_summary(
        {"srd5.1:race:human", "srd5.1:spell:magic-missile"},
        {"srd5.1:spell:magic-missile", "srd5.1:condition:poisoned"},
    ) == 4


def test_m03b_legacy_export_uses_version_numbers_not_internal_version_uuids() -> None:
    client, engine = _seed()
    build = build_p0_fighter_wizard_fixture()
    state = build_p0_fighter_wizard_state(build)
    character = client.app.state.character_repository.create_character(
        name="Legacy Export",
        build=build,
        state=state,
        version_kind="legacy",
    )

    artifact = build_character_export(client.app.state.character_repository, character.id)
    raw = artifact.document.model_dump(mode="json")
    text = json.dumps(raw, sort_keys=True)

    assert raw["payload"]["current_version_no"] == 1
    assert raw["payload"]["versions"][0]["version_kind"] == "legacy"
    assert raw["payload"]["versions"][0]["builder_provenance"] is None
    assert "current_version_id" not in text
    assert "parent_version_id" not in text
    assert "superseded_by_version_id" not in text
    assert str(character.current_version_id) not in text
    engine.dispose()


def test_m03b_export_rejects_manifest_version_supplied_only_by_schema_default() -> None:
    implicit = ContentManifest.model_validate(
        {
            "id": "test-pack",
            "name": "Test Pack",
            "ruleset": "dnd5e-2014",
            "categories": [
                {"name": "features", "kind": "feature", "file": "features.json", "count": 0}
            ],
            "total_entries": 0,
        }
    )
    repository = SimpleNamespace(
        registry=SimpleNamespace(get_source_manifest=lambda pack: implicit)
    )
    with pytest.raises(RuntimeError, match="no explicit portability version"):
        _pack_requirement(repository, "test-pack")
