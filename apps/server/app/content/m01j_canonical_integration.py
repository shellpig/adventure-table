from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from app.content import m01j_reference_fixes as _fixes
from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.m01j_reference_content import M01JReferenceRegistry
from app.content.registry import ContentRegistry, ContentValidationError


def _require(registry: ContentRegistry, ref: str, *, kind: str | None = None):
    entry = registry.get_optional(ref)
    if entry is None:
        raise ContentValidationError(f"M01-J canonical integration is missing {ref}")
    if kind is not None and parse_stable_key(entry.key).kind != kind:
        raise ContentValidationError(f"M01-J canonical integration expected {kind}: {ref}")
    return entry


def _subfeature_option_refs(
    registry: ContentRegistry,
    feature_ref: str,
) -> tuple[str, ...]:
    """Validate and expose an SRD feature_specific choose-one option set.

    These choices already flow through character_builder.structural. M01-J must
    not create a second selector for them merely because the PHB source identity
    dedupes onto an SRD subclass.
    """

    feature = _require(registry, feature_ref, kind="feature")
    feature_specific = feature.data.get("feature_specific")
    if not isinstance(feature_specific, dict):
        raise ContentValidationError(f"{feature_ref}: feature_specific is missing")
    subfeature = feature_specific.get("subfeature_options")
    if not isinstance(subfeature, dict) or subfeature.get("choose") != 1:
        raise ContentValidationError(f"{feature_ref}: expected a choose-one subfeature option set")
    source = subfeature.get("from")
    if not isinstance(source, dict) or source.get("option_set_type") != "options_array":
        raise ContentValidationError(f"{feature_ref}: subfeature option source is invalid")
    raw_options = source.get("options")
    if not isinstance(raw_options, list):
        raise ContentValidationError(f"{feature_ref}: subfeature options are missing")

    refs: list[str] = []
    for raw in raw_options:
        if not isinstance(raw, dict) or raw.get("option_type") != "reference":
            continue
        item = raw.get("item")
        if not isinstance(item, dict):
            continue
        try:
            ref = reference_to_stable_key(item, kinds={"feature"})
        except ValueError as exc:
            raise ContentValidationError(f"{feature_ref}: invalid subfeature reference") from exc
        if ref is None:
            raise ContentValidationError(f"{feature_ref}: unresolved subfeature reference")
        _require(registry, ref, kind="feature")
        refs.append(ref)
    refs = list(dict.fromkeys(refs))
    if len(refs) < 2:
        raise ContentValidationError(f"{feature_ref}: expected at least two subfeature options")
    return tuple(refs)


def _persistent_choice(
    *,
    key: str,
    feature_ref: str,
    label: str,
    level: int,
    option_refs: Iterable[str],
) -> dict[str, Any]:
    return {
        "choice_key": key,
        "feature_ref": feature_ref,
        "minimum_class_level": level,
        "choose_total": 1,
        "progression": (),
        "option_refs": tuple(option_refs),
        "option_minimum_levels": {},
        "label": label,
    }


def _merge_persistent_choices(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    choices: Iterable[dict[str, Any]],
) -> None:
    subclass = _require(registry, subclass_ref, kind="subclass")
    current = [
        deepcopy(raw)
        for raw in subclass.data.get("persistent_choices", [])
        if isinstance(raw, dict)
    ]
    by_key = {
        raw.get("choice_key"): index
        for index, raw in enumerate(current)
        if isinstance(raw.get("choice_key"), str)
    }
    for choice in choices:
        key = choice.get("choice_key")
        if not isinstance(key, str) or not key:
            raise ContentValidationError(f"{subclass_ref}: invalid canonical choice key")
        normalized = deepcopy(choice)
        if key in by_key:
            current[by_key[key]] = normalized
        else:
            by_key[key] = len(current)
            current.append(normalized)
    _fixes._update_subclass_data(registry, subclass_ref, persistent_choices=current)


def _merge_grant_choices(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    choices: Iterable[dict[str, Any]],
) -> None:
    subclass = _require(registry, subclass_ref, kind="subclass")
    current = [
        deepcopy(raw)
        for raw in subclass.data.get("grant_choices", [])
        if isinstance(raw, dict)
    ]
    by_key = {
        raw.get("choice_key"): index
        for index, raw in enumerate(current)
        if isinstance(raw.get("choice_key"), str)
    }
    for choice in choices:
        key = choice.get("choice_key")
        if not isinstance(key, str) or not key:
            raise ContentValidationError(f"{subclass_ref}: invalid canonical grant choice key")
        normalized = deepcopy(choice)
        if key in by_key:
            current[by_key[key]] = normalized
        else:
            by_key[key] = len(current)
            current.append(normalized)
    _fixes._update_subclass_data(registry, subclass_ref, grant_choices=current)


def _spell_has_class_source(registry: ContentRegistry, spell: Any) -> bool:
    raw_classes = spell.data.get("classes")
    if isinstance(raw_classes, list):
        for reference in raw_classes:
            if not isinstance(reference, dict):
                continue
            try:
                class_ref = reference_to_stable_key(reference, kinds={"class"})
            except ValueError:
                class_ref = None
            if class_ref is not None and registry.get_optional(class_ref) is not None:
                return True

    for class_entry in registry.list_kind("class"):
        spell_list = class_entry.data.get("spell_list")
        if not isinstance(spell_list, list):
            continue
        for reference in spell_list:
            if not isinstance(reference, dict):
                continue
            try:
                if reference_to_stable_key(reference, kinds={"spell"}) == spell.key:
                    return True
            except ValueError:
                continue
    return False


def _normalize_lore(registry: M01JReferenceRegistry) -> None:
    subclass_ref = "srd5.1:subclass:lore"
    # The SRD Bonus Proficiencies feature carries only prose, so M01-J supplies
    # its persistent skill selector. Additional Magical Secrets also needs a
    # source-aware SpellAccessEntry, which structural feature choices do not
    # compile, so both use the existing generic subclass grant infrastructure.
    skill_refs = tuple(sorted(entry.key for entry in registry.list_kind("skill")))
    if len(skill_refs) < 3:
        raise ContentValidationError("M01-J Lore has fewer than three installed skills")
    spell_refs = tuple(
        sorted(
            spell.key
            for spell in registry.list_kind("spell")
            if isinstance(spell.data.get("level"), int)
            and 0 <= int(spell.data["level"]) <= 3
            and _spell_has_class_source(registry, spell)
        )
    )
    if len(spell_refs) < 2:
        raise ContentValidationError("M01-J Lore has no legal Additional Magical Secrets options")
    _merge_grant_choices(
        registry,
        subclass_ref,
        (
            {
                "choice_key": "lore-bonus-proficiencies",
                "label": "College of Lore — Bonus Proficiencies",
                "minimum_class_level": 3,
                "choose_total": 3,
                "grant_target": "skill",
                "option_refs": skill_refs,
            },
            {
                "choice_key": "additional-magical-secrets",
                "label": "College of Lore — Additional Magical Secrets",
                "minimum_class_level": 6,
                "choose_total": 2,
                "grant_target": "spell",
                "option_refs": spell_refs,
                "access_type": "granted",
            },
        ),
    )


def _normalize_draconic_fixed_language(registry: M01JReferenceRegistry) -> None:
    subclass_ref = "srd5.1:subclass:draconic"
    ancestor_refs = _subfeature_option_refs(registry, "srd5.1:feature:dragon-ancestor")
    if len(ancestor_refs) != 10:
        raise ContentValidationError(
            f"M01-J Draconic Bloodline expected 10 structural dragon ancestors, got {len(ancestor_refs)}"
        )
    subclass = registry.get(subclass_ref)
    fixed = deepcopy(subclass.data.get("fixed_grants", {}))
    if not isinstance(fixed, dict):
        fixed = {}
    languages = [ref for ref in fixed.get("languages", ()) if isinstance(ref, str)]
    languages.append("srd5.1:language:draconic")
    _require(registry, "srd5.1:language:draconic", kind="language")
    fixed["languages"] = tuple(dict.fromkeys(languages))
    _fixes._update_subclass_data(registry, subclass_ref, fixed_grants=fixed)


def _validate_existing_structural_subclass_choices(registry: M01JReferenceRegistry) -> None:
    # These PHB identities map to SRD canonical subclasses whose persistent
    # choices are already represented by SRD feature_specific rules. Validate
    # the existing structural contract instead of duplicating it in M01-J.
    expected = {
        "srd5.1:feature:circle-of-the-land": 7,
        "srd5.1:feature:dragon-ancestor": 10,
        "srd5.1:feature:hunters-prey": 3,
        "srd5.1:feature:defensive-tactics": 3,
        "srd5.1:feature:multiattack": 2,
        "srd5.1:feature:superior-hunters-defense": 3,
    }
    for feature_ref, count in expected.items():
        refs = _subfeature_option_refs(registry, feature_ref)
        if len(refs) != count:
            raise ContentValidationError(
                f"{feature_ref}: expected {count} canonical structural options, got {len(refs)}"
            )


def _fighter_style_refs(registry: M01JReferenceRegistry) -> tuple[str, ...]:
    parent_ref = "srd5.1:feature:fighter-fighting-style"
    base_refs = _subfeature_option_refs(registry, parent_ref)
    for ref in base_refs:
        entry = registry.get(ref)
        data = dict(entry.data)
        # M01-I already uses this generic pool metadata for TCE fighting styles.
        # Give SRD style options the same identity so Champion's second style and
        # the level-1 Fighter style share the existing duplicate-selection gate.
        data["choice_pool_option"] = {
            "pool": "fighting-style",
            "eligible_class_refs": ("srd5.1:class:fighter",),
            "minimum_class_level": 1,
        }
        _fixes._replace_entry(registry, entry.model_copy(update={"data": data}))

    extra_refs: list[str] = []
    for feature in registry.list_kind("feature"):
        raw = feature.data.get("choice_pool_option")
        if not isinstance(raw, dict) or raw.get("pool") != "fighting-style":
            continue
        eligible = raw.get("eligible_class_refs", ())
        if isinstance(eligible, (list, tuple)) and "srd5.1:class:fighter" in eligible:
            extra_refs.append(feature.key)
    refs = tuple(dict.fromkeys((*base_refs, *sorted(extra_refs))))
    if len(refs) < len(base_refs):
        raise ContentValidationError("M01-J Champion Fighting Style pool normalization failed")
    return refs


def _normalize_champion(registry: M01JReferenceRegistry) -> None:
    feature_ref = "srd5.1:feature:additional-fighting-style"
    _require(registry, feature_ref, kind="feature")
    refs = _fighter_style_refs(registry)
    # Additional Fighting Style has no SRD feature_specific selector. Use the
    # generic M01-J persistent feature choice, while keeping the same pool option
    # identities as the core Fighter style selector.
    _merge_persistent_choices(
        registry,
        "srd5.1:subclass:champion",
        (
            _persistent_choice(
                key="champion-additional-fighting-style",
                feature_ref=feature_ref,
                label="Champion — Additional Fighting Style",
                level=10,
                option_refs=refs,
            ),
        ),
    )


def _validate_parent(subclass: Any, expected_class_ref: str) -> None:
    parent = subclass.data.get("class")
    if not isinstance(parent, dict):
        raise ContentValidationError(f"{subclass.key}: canonical subclass parent is missing")
    try:
        ref = reference_to_stable_key(parent, kinds={"class"})
    except ValueError as exc:
        raise ContentValidationError(f"{subclass.key}: invalid canonical subclass parent") from exc
    if ref != expected_class_ref:
        raise ContentValidationError(
            f"{subclass.key}: expected canonical parent {expected_class_ref}, got {ref}"
        )


def apply_m01j_canonical_integration(registry: ContentRegistry) -> ContentRegistry:
    """Complete PHB mechanics whose source identities dedupe onto SRD."""

    if not isinstance(registry, M01JReferenceRegistry):
        raise ContentValidationError("M01-J canonical integration requires M01JReferenceRegistry")
    expected_parents = {
        "srd5.1:subclass:lore": "srd5.1:class:bard",
        "srd5.1:subclass:land": "srd5.1:class:druid",
        "srd5.1:subclass:champion": "srd5.1:class:fighter",
        "srd5.1:subclass:hunter": "srd5.1:class:ranger",
        "srd5.1:subclass:draconic": "srd5.1:class:sorcerer",
    }
    for subclass_ref, parent_ref in expected_parents.items():
        _validate_parent(_require(registry, subclass_ref, kind="subclass"), parent_ref)

    _validate_existing_structural_subclass_choices(registry)
    _normalize_lore(registry)
    _normalize_champion(registry)
    _normalize_draconic_fixed_language(registry)
    return registry
