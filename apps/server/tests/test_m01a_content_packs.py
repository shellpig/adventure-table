from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.registry import (
    ContentNotFoundError,
    ContentRegistry,
    ContentValidationError,
)
from app.content.schemas import ContentManifest
from app.domain.character.schemas import AbilityScores, CharacterBuild, require_stable_key
from app.domain.character_builder.compiler import _with_derived_content_sources
from app.paths import resolve_srd_content_root


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def entry(source: str, kind: str, index: str, name: str, data: dict[str, object]) -> dict[str, object]:
    return {
        "key": f"{source}:{kind}:{index}",
        "index": index,
        "name": name,
        "source": source,
        "ruleset": "dnd5e-2014",
        "data": {"index": index, "name": name, **data},
    }


def race(source: str, index: str, name: str) -> dict[str, object]:
    return entry(
        source,
        "race",
        index,
        name,
        {
            "speed": 30,
            "ability_bonuses": [],
            "languages": [],
            "traits": [],
            "subraces": [],
        },
    )


def feature(source: str, index: str, name: str) -> dict[str, object]:
    return entry(source, "feature", index, name, {})


def background(
    source: str,
    index: str,
    name: str,
    *,
    feature_ref: dict[str, object] | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "starting_proficiencies": [],
        "starting_equipment": [],
    }
    if feature_ref is not None:
        data["feature"] = feature_ref
    return entry(source, "background", index, name, data)


def write_pack(
    root: Path,
    pack_id: str,
    name: str,
    categories: dict[str, tuple[str, list[dict[str, object]]]],
    *,
    manifest_extra: dict[str, object] | None = None,
) -> Path:
    pack_root = root / pack_id
    pack_root.mkdir(parents=True)
    manifest_categories = []
    total = 0
    for category_name, (kind, entries) in categories.items():
        filename = f"{category_name}.json"
        write_json(pack_root / filename, entries)
        manifest_categories.append(
            {
                "name": category_name,
                "kind": kind,
                "file": filename,
                "count": len(entries),
            }
        )
        total += len(entries)
    manifest: dict[str, object] = {
        "id": pack_id,
        "name": name,
        "ruleset": "dnd5e-2014",
        "categories": manifest_categories,
        "total_entries": total,
    }
    if manifest_extra:
        manifest.update(manifest_extra)
    write_json(pack_root / "manifest.json", manifest)
    return pack_root


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "content"
    root.mkdir()
    shutil.copytree(resolve_srd_content_root(), root / "srd5.1")

    write_pack(
        root,
        "pack-a",
        "Fixture Pack A",
        {
            "races": (
                "race",
                [race("pack-a", "test-race", "Test Race A"), race("pack-a", "goblin", "Goblin A")],
            ),
            "features": ("feature", [feature("pack-a", "test-a", "Feature A")]),
        },
    )
    write_pack(
        root,
        "pack-b",
        "Fixture Pack B",
        {
            "backgrounds": (
                "background",
                [
                    background(
                        "pack-b",
                        "test-background",
                        "Test Background B",
                        feature_ref={"key": "pack-a:feature:test-a", "name": "Feature A"},
                    )
                ],
            ),
            "races": ("race", [race("pack-b", "goblin", "Goblin B")]),
            "features": ("feature", [feature("pack-b", "test-b", "Feature B")]),
        },
    )
    write_pack(
        root,
        "unlisted-pack",
        "Unlisted Fixture Pack",
        {"features": ("feature", [feature("unlisted-pack", "hidden", "Hidden")])},
    )
    return root


def test_legacy_srd_manifest_loads_unchanged() -> None:
    registry = ContentRegistry.from_directory(resolve_srd_content_root())

    assert registry.enabled_pack_ids == ("srd5.1",)
    assert registry.manifest.id == "srd5.1"
    assert registry.get("srd5.1:race:human").name == "Human"


def test_multi_pack_lookup_filter_metadata_and_cross_pack_reference(fixture_root: Path) -> None:
    registry = ContentRegistry.from_root(fixture_root, ("srd5.1", "pack-a", "pack-b"))

    assert registry.pack_count == 3
    assert registry.enabled_pack_ids == ("srd5.1", "pack-a", "pack-b")
    assert registry.get("pack-a:race:test-race").name == "Test Race A"
    assert registry.get("pack-b:background:test-background").name == "Test Background B"
    assert registry.source_label("pack-a") == "Fixture Pack A"
    assert registry.get_source_manifest("pack-b").name == "Fixture Pack B"

    race_keys = {item.key for item in registry.list_kind("race")}
    assert "srd5.1:race:human" in race_keys
    assert "pack-a:race:goblin" in race_keys
    assert "pack-b:race:goblin" in race_keys
    assert {item.key for item in registry.list_kind("race", source="pack-a")} == {
        "pack-a:race:test-race",
        "pack-a:race:goblin",
    }


def test_enabled_pack_list_is_explicit_and_does_not_scan_root(fixture_root: Path) -> None:
    registry = ContentRegistry.from_root(fixture_root, ("srd5.1", "pack-a"))

    assert registry.enabled_pack_ids == ("srd5.1", "pack-a")
    assert registry.get_optional("unlisted-pack:feature:hidden") is None
    assert registry.get_optional("pack-b:feature:test-b") is None


def test_installed_but_disabled_cross_pack_dependency_stays_unresolved(
    fixture_root: Path,
) -> None:
    """M03-A narrowed M01-A's original "cross-pack dependency must be enabled".

    M03-A requires subset registries (`Settings.enabled_content_packs`) to load
    without deleting pack directories, so a reference into a pack that ships but
    is deliberately disabled can no longer fail the load. It stays unresolved
    instead, which is what M03-C import preview classifies. The corruption half
    of the original contract is kept by the next test.
    """

    registry = ContentRegistry.from_root(fixture_root, ("srd5.1", "pack-b"))

    assert registry.enabled_pack_ids == ("srd5.1", "pack-b")
    assert "pack-a" in registry.installed_pack_ids
    assert registry.get_optional("pack-a:feature:test-a") is None
    assert registry.get("pack-b:background:test-background").name == "Test Background B"


def test_reference_to_uninstalled_pack_is_still_dangling(fixture_root: Path) -> None:
    """A source that ships nowhere is a bad StableKey, not a disabled dependency."""

    write_pack(
        fixture_root,
        "pack-c",
        "Fixture Pack C",
        {
            "backgrounds": (
                "background",
                [
                    background(
                        "pack-c",
                        "typo-background",
                        "Typo Background C",
                        feature_ref={
                            "key": "pack-typo:feature:test-a",
                            "name": "Feature A",
                        },
                    )
                ],
            )
        },
    )

    with pytest.raises(ContentValidationError, match="dangling reference"):
        ContentRegistry.from_root(fixture_root, ("srd5.1", "pack-c"))


def test_same_kind_and_index_can_coexist_across_sources(fixture_root: Path) -> None:
    registry = ContentRegistry.from_root(fixture_root, ("pack-a", "pack-b"))

    assert registry.get("pack-a:race:goblin").name == "Goblin A"
    assert registry.get("pack-b:race:goblin").name == "Goblin B"


def test_generic_manifest_can_omit_srd_specific_metadata(tmp_path: Path) -> None:
    pack_root = write_pack(
        tmp_path,
        "private-pack",
        "Private Pack",
        {"features": ("feature", [feature("private-pack", "one", "One")])},
    )

    registry = ContentRegistry.from_directory(pack_root)
    assert registry.get_source_manifest("private-pack").license is None
    assert registry.get_source_manifest("private-pack").extraction is None
    assert registry.get_source_manifest("private-pack").scope_guard is None


def test_generic_manifest_accepts_optional_license_and_extraction(tmp_path: Path) -> None:
    pack_root = write_pack(
        tmp_path,
        "licensed-pack",
        "Licensed Pack",
        {"features": ("feature", [feature("licensed-pack", "one", "One")])},
        manifest_extra={
            "license": {
                "spdx": "LicenseRef-Private",
                "source": "Private source",
                "license_url": "https://example.invalid/license",
                "attribution": "Private fixture",
            },
            "extraction": {
                "repository": "fixture/repository",
                "commit": "a" * 40,
                "license": "Custom",
                "license_url": "https://example.invalid/source-license",
            },
            "provenance": {"note": "fixture"},
            "usage": {"private": True},
        },
    )

    registry = ContentRegistry.from_directory(pack_root)
    manifest = registry.get_source_manifest("licensed-pack")
    assert manifest.license is not None
    assert manifest.license.spdx == "LicenseRef-Private"
    assert manifest.extraction is not None
    assert manifest.extraction.commit == "a" * 40


def test_malformed_optional_extraction_commit_is_rejected(tmp_path: Path) -> None:
    pack_root = write_pack(
        tmp_path,
        "bad-extraction",
        "Bad Extraction",
        {"features": ("feature", [feature("bad-extraction", "one", "One")])},
        manifest_extra={
            "extraction": {
                "repository": "fixture/repository",
                "commit": "not-a-commit",
                "license": "Custom",
                "license_url": "https://example.invalid/source-license",
            }
        },
    )

    with pytest.raises(ContentValidationError, match="invalid content manifest"):
        ContentRegistry.from_directory(pack_root)


def test_invalid_enabled_pack_id_is_rejected(fixture_root: Path) -> None:
    with pytest.raises(ContentValidationError, match="invalid enabled content pack id"):
        ContentRegistry.from_root(fixture_root, ("bad:pack",))


def test_source_mismatch_is_rejected(tmp_path: Path) -> None:
    pack_root = write_pack(
        tmp_path,
        "pack-a",
        "Pack A",
        {"features": ("feature", [feature("pack-a", "one", "One")])},
    )
    payload = json.loads((pack_root / "features.json").read_text(encoding="utf-8"))
    payload[0]["source"] = "pack-b"
    payload[0]["key"] = "pack-b:feature:one"
    write_json(pack_root / "features.json", payload)

    with pytest.raises(ContentValidationError, match="source"):
        ContentRegistry.from_directory(pack_root)


def test_duplicate_full_key_is_rejected(tmp_path: Path) -> None:
    pack_root = write_pack(
        tmp_path,
        "pack-a",
        "Pack A",
        {"features": ("feature", [feature("pack-a", "one", "One")])},
    )
    payload = json.loads((pack_root / "features.json").read_text(encoding="utf-8"))
    payload.append(payload[0])
    write_json(pack_root / "features.json", payload)
    manifest = json.loads((pack_root / "manifest.json").read_text(encoding="utf-8"))
    manifest["categories"][0]["count"] = 2
    manifest["total_entries"] = 2
    write_json(pack_root / "manifest.json", manifest)

    with pytest.raises(ContentValidationError, match="duplicate content key"):
        ContentRegistry.from_directory(pack_root)


def test_category_count_mismatch_is_rejected(tmp_path: Path) -> None:
    pack_root = write_pack(
        tmp_path,
        "pack-a",
        "Pack A",
        {"features": ("feature", [feature("pack-a", "one", "One")])},
    )
    manifest = json.loads((pack_root / "manifest.json").read_text(encoding="utf-8"))
    manifest["categories"][0]["count"] = 2
    manifest["total_entries"] = 2
    write_json(pack_root / "manifest.json", manifest)

    with pytest.raises(ContentValidationError, match="count mismatch"):
        ContentRegistry.from_directory(pack_root)


def test_wrong_kind_explicit_reference_is_rejected(tmp_path: Path) -> None:
    write_pack(
        tmp_path,
        "pack-a",
        "Pack A",
        {
            "features": ("feature", [feature("pack-a", "one", "One")]),
            "subraces": (
                "subrace",
                [
                    entry(
                        "pack-a",
                        "subrace",
                        "bad",
                        "Bad Subrace",
                        {
                            "race": {"key": "pack-a:feature:one", "name": "One"},
                        },
                    )
                ],
            ),
        },
    )

    with pytest.raises(ContentValidationError, match="wrong-kind reference"):
        ContentRegistry.from_root(tmp_path, ("pack-a",))


def test_unknown_legacy_api_route_and_url_index_mismatch_fail_fast(tmp_path: Path) -> None:
    pack_root = write_pack(
        tmp_path,
        "pack-a",
        "Pack A",
        {"features": ("feature", [feature("pack-a", "one", "One")])},
    )
    payload = json.loads((pack_root / "features.json").read_text(encoding="utf-8"))
    payload[0]["data"]["bad"] = {
        "index": "x",
        "name": "Bad",
        "url": "/api/2014/not-a-route/x",
    }
    write_json(pack_root / "features.json", payload)
    with pytest.raises(ContentValidationError, match="unknown legacy SRD API route"):
        ContentRegistry.from_directory(pack_root)

    payload[0]["data"]["bad"] = {
        "index": "x",
        "name": "Bad",
        "url": "/api/2014/features/y",
    }
    write_json(pack_root / "features.json", payload)
    with pytest.raises(ContentValidationError, match="URL/index mismatch"):
        ContentRegistry.from_directory(pack_root)


def test_stable_key_parser_and_legacy_reference_adapter() -> None:
    assert parse_stable_key("pack-a:race:goblin").source == "pack-a"
    assert reference_to_stable_key(
        {"index": "human", "name": "Human", "url": "/api/2014/races/human"}
    ) == "srd5.1:race:human"
    assert reference_to_stable_key(
        {"key": "pack-a:race:goblin", "name": "Goblin A"}
    ) == "pack-a:race:goblin"


def test_character_schema_accepts_generic_source_and_preserves_kind_validation() -> None:
    assert require_stable_key("pack-a:race:goblin", kinds={"race"}) == "pack-a:race:goblin"
    with pytest.raises(ValueError, match="reference kind"):
        require_stable_key("pack-a:spell:goblin", kinds={"race"})


def test_build_content_sources_are_derived_from_actual_references() -> None:
    build = CharacterBuild(
        content_sources=("client-injected",),
        race_ref="pack-a:race:goblin",
        background_ref="pack-b:background:test-background",
        character_level=1,
        class_progression=("srd5.1:class:fighter",),
        ability_scores=AbilityScores(
            strength=15,
            dexterity=14,
            constitution=13,
            intelligence=12,
            wisdom=10,
            charisma=8,
        ),
        hp_progression=(10,),
    )

    derived = _with_derived_content_sources(build)
    assert derived.content_sources == ("pack-a", "pack-b", "srd5.1")


def test_unknown_source_lookup_is_explicit(fixture_root: Path) -> None:
    registry = ContentRegistry.from_root(fixture_root, ("pack-a",))
    with pytest.raises(ContentNotFoundError):
        registry.get_source_manifest("pack-b")
