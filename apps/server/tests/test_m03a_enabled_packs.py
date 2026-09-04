from __future__ import annotations

import pytest

import app.content as content_module
import app.content.registry as registry_module
from app.config import Settings
from app.content.registry import ContentRegistry, ContentValidationError
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
PACKS_WITHOUT_XGE = tuple(pack for pack in FULL_PACKS if pack != "xge")
M03A_START_ENTRY_COUNT = 3186


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
    assert registry.get_optional("mtf:race-variant:baalzebul-tiefling") is None


def test_reference_into_disabled_pack_is_unresolved_not_corruption() -> None:
    registry = ContentRegistry.from_root(resolve_content_root(), ("srd5.1",))
    source = registry.get("srd5.1:class:fighter")
    probe = source.model_copy(
        update={
            "data": {
                "features": [
                    {"key": "xge:feature:m03-a-disabled-probe", "name": "Disabled Probe"}
                ]
            }
        }
    )
    entries = {probe.key: probe}

    ContentRegistry._validate_cross_references(
        (probe,),
        entries,
        enabled_pack_ids=frozenset({"srd5.1"}),
    )

    with pytest.raises(ContentValidationError, match="dangling reference"):
        ContentRegistry._validate_cross_references(
            (probe,),
            entries,
            enabled_pack_ids=frozenset({"srd5.1", "xge"}),
        )


@pytest.mark.parametrize(
    "packs",
    [
        ("srd5.1",),
        ("srd5.1", "scag"),
        PACKS_WITHOUT_XGE,
    ],
)
def test_application_registry_can_start_with_intentional_pack_subset(
    monkeypatch: pytest.MonkeyPatch,
    packs: tuple[str, ...],
) -> None:
    root = resolve_content_root()
    monkeypatch.setattr(registry_module.settings, "enabled_content_packs", packs)
    monkeypatch.setattr(registry_module, "resolve_content_root", lambda: root)
    monkeypatch.setattr(content_module, "resolve_content_root", lambda: root)

    registry = content_module.load_default_content_registry()
    assert registry.enabled_pack_ids == packs
    assert registry.get("srd5.1:race:human").name == "Human"
    assert registry.get_optional("xge:spell:wall-of-water") is None
    assert (root / "xge").is_dir()


def test_default_full_registry_matches_m03a_start_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = resolve_content_root()
    monkeypatch.setattr(registry_module.settings, "enabled_content_packs", FULL_PACKS)
    monkeypatch.setattr(registry_module, "resolve_content_root", lambda: root)

    registry = registry_module.load_default_content_registry()
    assert registry.enabled_pack_ids == FULL_PACKS
    assert len(registry) == M03A_START_ENTRY_COUNT


def test_registry_module_no_longer_owns_enabled_pack_constant() -> None:
    assert not hasattr(registry_module, "DEFAULT_CONTENT_PACKS")
