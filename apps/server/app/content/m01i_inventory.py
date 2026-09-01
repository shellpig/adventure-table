from __future__ import annotations

from app.content.registry import ContentRegistry, ContentValidationError


EXPECTED_OPTIONAL_FEATURES_BY_CLASS: dict[str, frozenset[str]] = {
    "srd5.1:class:barbarian": frozenset(
        {
            "tce:feature:primal-knowledge",
            "tce:feature:instinctive-pounce",
        }
    ),
    "srd5.1:class:bard": frozenset(
        {
            "tce:feature:additional-bard-spells",
            "tce:feature:magical-inspiration",
            "tce:feature:bardic-versatility",
        }
    ),
    "srd5.1:class:cleric": frozenset(
        {
            "tce:feature:additional-cleric-spells",
            "tce:feature:cleric-harness-divine-power",
            "tce:feature:cleric-cantrip-versatility",
            "tce:feature:blessed-strikes",
        }
    ),
    "srd5.1:class:druid": frozenset(
        {
            "tce:feature:additional-druid-spells",
            "tce:feature:wild-companion",
            "tce:feature:druid-cantrip-versatility",
        }
    ),
    "srd5.1:class:fighter": frozenset(
        {
            "tce:feature:fighter-fighting-style-options",
            "tce:feature:fighter-martial-versatility",
            "tce:feature:fighter-maneuver-options",
        }
    ),
    "srd5.1:class:monk": frozenset(
        {
            "tce:feature:dedicated-weapon",
            "tce:feature:ki-fueled-attack",
            "tce:feature:quickened-healing",
            "tce:feature:focused-aim",
        }
    ),
    "srd5.1:class:paladin": frozenset(
        {
            "tce:feature:additional-paladin-spells",
            "tce:feature:paladin-fighting-style-options",
            "tce:feature:paladin-harness-divine-power",
            "tce:feature:paladin-martial-versatility",
        }
    ),
    "srd5.1:class:ranger": frozenset(
        {
            "tce:feature:deft-explorer",
            "tce:feature:favored-foe",
            "tce:feature:additional-ranger-spells",
            "tce:feature:ranger-fighting-style-options",
            "tce:feature:ranger-spellcasting-focus",
            "tce:feature:primal-awareness",
            "tce:feature:ranger-martial-versatility",
            "tce:feature:natures-veil",
        }
    ),
    "srd5.1:class:rogue": frozenset({"tce:feature:steady-aim"}),
    "srd5.1:class:sorcerer": frozenset(
        {
            "tce:feature:additional-sorcerer-spells",
            "tce:feature:sorcerous-versatility",
            "tce:feature:sorcerer-metamagic-options",
            "tce:feature:magical-guidance",
        }
    ),
    "srd5.1:class:warlock": frozenset(
        {
            "tce:feature:additional-warlock-spells",
            "tce:feature:warlock-pact-boon-options",
            "tce:feature:warlock-eldritch-invocation-options",
            "tce:feature:eldritch-versatility",
        }
    ),
    "srd5.1:class:wizard": frozenset(
        {
            "tce:feature:additional-wizard-spells",
            "tce:feature:cantrip-formulas",
        }
    ),
}

EXPECTED_FIGHTING_STYLE_RELATIONS: dict[str, frozenset[str]] = {
    "srd5.1:class:fighter": frozenset(
        {
            "tce:feature:blind-fighting",
            "tce:feature:interception",
            "tce:feature:superior-technique",
            "tce:feature:thrown-weapon-fighting",
            "tce:feature:unarmed-fighting",
        }
    ),
    "srd5.1:class:paladin": frozenset(
        {
            "tce:feature:blind-fighting",
            "tce:feature:blessed-warrior",
            "tce:feature:interception",
        }
    ),
    "srd5.1:class:ranger": frozenset(
        {
            "tce:feature:blind-fighting",
            "tce:feature:druidic-warrior",
            "tce:feature:thrown-weapon-fighting",
        }
    ),
}


def validate_m01i_inventory(registry: ContentRegistry) -> ContentRegistry:
    """Fail startup if the documented M01-I inventory silently drifts.

    Artificer is intentionally excluded here because M01-G/H own that class.
    The inventory is keyed by StableKey and relation data, never display name.
    """

    if "tce" not in registry.enabled_pack_ids:
        return registry

    actual_by_class: dict[str, set[str]] = {}
    style_by_class: dict[str, set[str]] = {
        class_ref: set() for class_ref in EXPECTED_FIGHTING_STYLE_RELATIONS
    }

    for entry in registry.list_kind("feature", source="tce"):
        optional = entry.data.get("optional_class_feature")
        if isinstance(optional, dict):
            parent = optional.get("parent_class_ref")
            if isinstance(parent, str):
                actual_by_class.setdefault(parent, set()).add(entry.key)

        pool = entry.data.get("choice_pool_option")
        if not isinstance(pool, dict) or pool.get("pool") != "fighting-style":
            continue
        eligible = pool.get("eligible_class_refs")
        if not isinstance(eligible, list):
            continue
        for class_ref in eligible:
            if class_ref in style_by_class:
                style_by_class[class_ref].add(entry.key)

    expected_classes = set(EXPECTED_OPTIONAL_FEATURES_BY_CLASS)
    unexpected_classes = set(actual_by_class) - expected_classes
    if unexpected_classes:
        raise ContentValidationError(
            "M01-I optional feature inventory has unexpected parent classes: "
            + ", ".join(sorted(unexpected_classes))
        )

    for class_ref, expected in EXPECTED_OPTIONAL_FEATURES_BY_CLASS.items():
        actual = frozenset(actual_by_class.get(class_ref, set()))
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ContentValidationError(
                f"M01-I optional feature inventory mismatch for {class_ref}: "
                f"missing={missing}, extra={extra}"
            )

    for class_ref, expected in EXPECTED_FIGHTING_STYLE_RELATIONS.items():
        actual = frozenset(style_by_class[class_ref])
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ContentValidationError(
                f"M01-I fighting style relation mismatch for {class_ref}: "
                f"missing={missing}, extra={extra}"
            )

    if sum(len(items) for items in EXPECTED_OPTIONAL_FEATURES_BY_CLASS.values()) != 42:
        raise ContentValidationError("M01-I maintained optional feature inventory must contain 42 entries")

    return registry
