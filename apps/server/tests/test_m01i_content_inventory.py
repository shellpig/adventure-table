from __future__ import annotations

from app.paths import resolve_content_root

CONTENT_PACKS_ROOT = resolve_content_root()


from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.m01i_inventory import (
    EXPECTED_FIGHTING_STYLE_RELATIONS,
    EXPECTED_OPTIONAL_FEATURES_BY_CLASS,
    EXPECTED_PHB_MANEUVERS,
    EXPECTED_TCE_INVOCATIONS,
    EXPECTED_TCE_MANEUVERS,
    EXPECTED_TCE_METAMAGIC,
    EXPECTED_TCE_PACT_BOONS,
)


def test_m01i_machine_inventory_is_complete_and_stable() -> None:
    registry = load_default_content_registry()

    assert sum(len(items) for items in EXPECTED_OPTIONAL_FEATURES_BY_CLASS.values()) == 42
    assert len(set().union(*EXPECTED_FIGHTING_STYLE_RELATIONS.values())) == 7
    assert len(EXPECTED_TCE_MANEUVERS) == 7
    assert len(EXPECTED_PHB_MANEUVERS) == 16
    assert len(EXPECTED_TCE_METAMAGIC) == 2
    assert len(EXPECTED_TCE_PACT_BOONS) == 1
    assert len(EXPECTED_TCE_INVOCATIONS) == 8

    for entries in EXPECTED_OPTIONAL_FEATURES_BY_CLASS.values():
        for key in entries:
            assert registry.get(key).data.get("optional_class_feature") is not None

    for class_ref, expected_styles in EXPECTED_FIGHTING_STYLE_RELATIONS.items():
        actual = {
            entry.key
            for entry in registry.list_kind("feature", source="tce")
            if isinstance((pool := entry.data.get("choice_pool_option")), dict)
            and pool.get("pool") == "fighting-style"
            and class_ref in pool.get("eligible_class_refs", [])
        }
        assert actual == expected_styles


def test_m01i_shared_fighting_styles_keep_one_mechanical_identity() -> None:
    relations = EXPECTED_FIGHTING_STYLE_RELATIONS

    assert "tce:feature:blind-fighting" in relations["srd5.1:class:fighter"]
    assert "tce:feature:blind-fighting" in relations["srd5.1:class:paladin"]
    assert "tce:feature:blind-fighting" in relations["srd5.1:class:ranger"]
    assert "tce:feature:interception" in relations["srd5.1:class:fighter"]
    assert "tce:feature:interception" in relations["srd5.1:class:paladin"]


def test_m01i_new_feature_and_maneuver_rules_have_zh_tw_presentation() -> None:
    registry = load_default_content_registry()
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)
    keys = set().union(
        *EXPECTED_OPTIONAL_FEATURES_BY_CLASS.values(),
        *EXPECTED_FIGHTING_STYLE_RELATIONS.values(),
        EXPECTED_TCE_MANEUVERS,
        EXPECTED_TCE_METAMAGIC,
        EXPECTED_TCE_PACT_BOONS,
        EXPECTED_TCE_INVOCATIONS,
        EXPECTED_PHB_MANEUVERS,
    )

    for key in sorted(keys):
        entry = registry.get(key)
        name = catalog.resolve_name(key, "zh-TW")
        description = catalog.resolve_field(key, "data.desc.0", "zh-TW")
        assert not name.fallback_used, key
        assert isinstance(name.value, str) and name.value.strip(), key
        assert not description.fallback_used, key
        assert isinstance(description.value, str) and description.value.strip(), key
        assert name.value != entry.name, key
