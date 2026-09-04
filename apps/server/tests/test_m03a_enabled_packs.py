from __future__ import annotations

import pytest

import app.content.registry as registry_module
from app.config import Settings
from app.paths import resolve_content_root


FULL_PACKS = (
    "srd5.1",
    "phb2014",
    "scag",
    "gos",
    "vgm",
    "vrgr",
    "tce",
    "xge",
    "mtf",
)


def _settings_with_pack_env(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> Settings:
    monkeypatch.delenv("ADVENTURE_TABLE_ENABLED_CONTENT_PACKS", raising=False)
    if value is not None:
        monkeypatch.setenv("ADVENTURE_TABLE_ENABLED_CONTENT_PACKS", value)
    return Settings(_env_file=None)


def test_enabled_content_packs_default_is_current_full_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _settings_with_pack_env(monkeypatch, None).enabled_content_packs == FULL_PACKS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("srd5.1,phb2014", ("srd5.1", "phb2014")),
        ("srd5.1, phb2014", ("srd5.1", "phb2014")),
        (" , ", FULL_PACKS),
        ("", FULL_PACKS),
    ],
)
def test_enabled_content_packs_csv_override_uses_nodecode(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected: tuple[str, ...],
) -> None:
    assert _settings_with_pack_env(monkeypatch, raw).enabled_content_packs == expected


def test_default_registry_respects_subset_without_removing_pack_directories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = resolve_content_root()
    monkeypatch.setattr(registry_module.settings, "enabled_content_packs", ("srd5.1", "phb2014"))
    monkeypatch.setattr(registry_module, "resolve_content_root", lambda: root)

    registry = registry_module.load_default_content_registry()
    assert registry.enabled_pack_ids == ("srd5.1", "phb2014")
    assert registry.pack_count == 2
    assert (root / "mtf").is_dir()
    assert registry.get_optional("mtf:race_variant:baalzebul-tiefling") is None


def test_registry_module_no_longer_owns_enabled_pack_constant() -> None:
    assert not hasattr(registry_module, "DEFAULT_CONTENT_PACKS")
