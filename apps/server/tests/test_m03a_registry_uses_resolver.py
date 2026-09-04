from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

import app.content.registry as registry_module
from app.content.registry import ContentRegistry, ContentValidationError
from app.paths import resolve_content_root, resolve_srd_content_root


FULL_PACK_ENTRY_COUNTS = {
    "srd5.1": 1944,
    "phb2014": 384,
    "scag": 78,
    "gos": 4,
    "vgm": 64,
    "vrgr": 5,
    "tce": 401,
    "xge": 266,
    "mtf": 40,
}


def test_registry_module_no_longer_owns_legacy_root_constants() -> None:
    for name in (
        "REPOSITORY_ROOT",
        "CONTENT_PACKS_ROOT",
        "DEFAULT_CONTENT_ROOT",
        "DEFAULT_SRD_CONTENT_ROOT",
    ):
        assert not hasattr(registry_module, name)


def test_default_registry_uses_resolved_root_and_settings_pack_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, tuple[str, ...]]] = []
    sentinel = object()

    def fake_from_root(
        cls: type[ContentRegistry],
        content_root: Path,
        enabled_pack_ids: tuple[str, ...],
    ) -> object:
        calls.append((content_root, tuple(enabled_pack_ids)))
        return sentinel

    resolved = Path("/resolved/content")
    monkeypatch.setattr(registry_module, "resolve_content_root", lambda: resolved)
    monkeypatch.setattr(registry_module.settings, "enabled_content_packs", ("srd5.1", "mtf"))
    monkeypatch.setattr(ContentRegistry, "from_root", classmethod(fake_from_root))

    assert registry_module.load_default_content_registry() is sentinel
    assert calls == [(resolved, ("srd5.1", "mtf"))]


def test_environment_content_root_changes_actual_registry_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    custom_root = tmp_path / "data"
    custom_srd = custom_root / "srd5.1"
    shutil.copytree(resolve_srd_content_root(), custom_srd)
    manifest_path = custom_srd / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["name"] = "M03-A Temporary SRD"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setenv("ADVENTURE_TABLE_CONTENT_ROOT", str(custom_root))
    monkeypatch.setattr(registry_module.settings, "enabled_content_packs", ("srd5.1",))

    registry = registry_module.load_default_content_registry()
    assert registry.get_source_manifest("srd5.1").name == "M03-A Temporary SRD"
    assert registry.get("srd5.1:race:human").source_label == "M03-A Temporary SRD"


def test_default_full_registry_matches_m03a_start_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_root = resolve_content_root()
    monkeypatch.delenv("ADVENTURE_TABLE_CONTENT_ROOT", raising=False)
    monkeypatch.setattr(registry_module, "resolve_content_root", lambda: content_root)
    monkeypatch.setattr(
        registry_module.settings,
        "enabled_content_packs",
        tuple(FULL_PACK_ENTRY_COUNTS),
    )

    registry = registry_module.load_default_content_registry()
    assert registry.enabled_pack_ids == tuple(FULL_PACK_ENTRY_COUNTS)
    assert len(registry) == sum(FULL_PACK_ENTRY_COUNTS.values())
    for source, expected_count in FULL_PACK_ENTRY_COUNTS.items():
        manifest = registry.get_source_manifest(source)
        assert manifest.total_entries == expected_count


def test_settings_subset_loads_without_deleting_other_pack_directories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_root = resolve_content_root()
    monkeypatch.setattr(registry_module, "resolve_content_root", lambda: content_root)
    monkeypatch.setattr(registry_module.settings, "enabled_content_packs", ("srd5.1",))

    registry = registry_module.load_default_content_registry()
    assert registry.enabled_pack_ids == ("srd5.1",)
    assert registry.pack_count == 1
    assert registry.get_optional("phb2014:background:city-watch") is None
    assert (content_root / "phb2014").is_dir()


def test_settings_missing_pack_fails_explicitly_without_mutating_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_root = resolve_content_root()
    monkeypatch.setattr(registry_module, "resolve_content_root", lambda: content_root)
    monkeypatch.setattr(
        registry_module.settings,
        "enabled_content_packs",
        ("srd5.1", "m03-a-not-installed"),
    )

    with pytest.raises(ContentValidationError, match="enabled content pack directory is missing"):
        registry_module.load_default_content_registry()
