from __future__ import annotations

from pathlib import Path

import pytest

import app.content.registry as registry_module
from app.content.registry import ContentRegistry, ContentValidationError
from app.paths import resolve_content_root


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
