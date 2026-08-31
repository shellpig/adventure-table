from __future__ import annotations

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import CONTENT_PACKS_ROOT


VARIANTS = (
    "scag:race-variant:half-elf-moon-sun-descent",
    "scag:race-variant:half-elf-wood-descent",
    "scag:race-variant:half-elf-aquatic-descent",
    "scag:race-variant:half-elf-drow-descent",
)


def test_m01e_race_variant_names_are_required_and_have_zh_tw_overlays() -> None:
    registry = load_default_content_registry()
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)

    issues = catalog.completeness_issues(
        locales=("zh-TW", "en"),
        sources={"scag"},
        kinds={"race-variant"},
    )
    assert issues == ()

    for key in VARIANTS:
        parsed = registry.get(key)
        assert catalog.policy.is_required("scag", "race-variant", "name", "zh-TW")
        localized = catalog.resolve_name(key, "zh-TW")
        assert localized.missing_required is False
        assert localized.fallback_used is False
        assert localized.value != parsed.name
