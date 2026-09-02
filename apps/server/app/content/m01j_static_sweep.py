from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.content import m01j_reference_fixes as _fixes
from app.content.identity import reference_to_stable_key
from app.content.m01j_reference_content import M01JReferenceRegistry
from app.content.registry import ContentRegistry, ContentValidationError


LAND_REF = "srd5.1:subclass:land"
SHEPHERD_REF = "xge:subclass:shepherd"
STARS_REF = "tce:subclass:stars"
ARCANA_REF = "scag:subclass:arcana"
SYLVAN_REF = "srd5.1:language:sylvan"
GUIDING_BOLT_REF = "srd5.1:spell:guiding-bolt"
ARCANA_SKILL_REF = "srd5.1:skill:arcana"
DRUID_REF = "srd5.1:class:druid"


def _require(registry: ContentRegistry, ref: str) -> Any:
    entry = registry.get_optional(ref)
    if entry is None:
        raise ContentValidationError(f"M01-J final static sweep is missing {ref}")
    return entry


def _spell_on_class_list(registry: ContentRegistry, spell: Any, class_ref: str) -> bool:
    raw_classes = spell.data.get("classes")
    if isinstance(raw_classes, list):
        for reference in raw_classes:
            if not isinstance(reference, dict):
                continue
            try:
                if reference_to_stable_key(reference, kinds={"class"}) == class_ref:
                    return True
            except ValueError:
                continue

    class_entry = registry.get_optional(class_ref)
    dedicated = class_entry.data.get("spell_list") if class_entry is not None else None
    if isinstance(dedicated, list):
        for reference in dedicated:
            if not isinstance(reference, dict):
                continue
            try:
                if reference_to_stable_key(reference, kinds={"spell"}) == spell.key:
                    return True
            except ValueError:
                continue
    return False


def _merge_grant_choice(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    choice: dict[str, Any],
) -> None:
    subclass = _require(registry, subclass_ref)
    current = [
        deepcopy(raw)
        for raw in subclass.data.get("grant_choices", [])
        if isinstance(raw, dict)
    ]
    key = choice.get("choice_key")
    if not isinstance(key, str) or not key:
        raise ContentValidationError(f"{subclass_ref}: invalid final-sweep choice key")
    replaced = False
    for index, raw in enumerate(current):
        if raw.get("choice_key") == key:
            current[index] = deepcopy(choice)
            replaced = True
            break
    if not replaced:
        current.append(deepcopy(choice))
    _fixes._update_subclass_data(registry, subclass_ref, grant_choices=current)


def _merge_fixed_grant(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    field: str,
    *refs: str,
) -> None:
    for ref in refs:
        _require(registry, ref)
    subclass = _require(registry, subclass_ref)
    fixed = deepcopy(subclass.data.get("fixed_grants", {}))
    if not isinstance(fixed, dict):
        fixed = {}
    values = [ref for ref in fixed.get(field, ()) if isinstance(ref, str)]
    values.extend(refs)
    fixed[field] = tuple(dict.fromkeys(values))
    _fixes._update_subclass_data(registry, subclass_ref, fixed_grants=fixed)


def _merge_spell_record(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    *,
    spell_ref: str,
    minimum_class_level: int,
    access_type: str,
) -> None:
    _require(registry, spell_ref)
    subclass = _require(registry, subclass_ref)
    current = [
        deepcopy(raw)
        for raw in subclass.data.get("spells", [])
        if isinstance(raw, dict)
    ]
    replacement = _fixes._spell_record(
        registry,
        spell_ref,
        minimum_class_level=minimum_class_level,
        access_type=access_type,
    )
    for index, raw in enumerate(current):
        raw_spell = raw.get("spell")
        raw_key = raw_spell.get("key") if isinstance(raw_spell, dict) else None
        if raw_key == spell_ref and raw.get("access_type") == access_type:
            current[index] = replacement
            break
    else:
        current.append(replacement)
    _fixes._update_subclass_data(registry, subclass_ref, spells=current)


def _normalize_land_bonus_cantrip(registry: M01JReferenceRegistry) -> None:
    eligible = tuple(
        spell.key
        for spell in registry.list_kind("spell")
        if spell.data.get("level") == 0 and _spell_on_class_list(registry, spell, DRUID_REF)
    )
    if not eligible:
        raise ContentValidationError("M01-J Circle of the Land has no eligible Druid cantrips")
    _merge_grant_choice(
        registry,
        LAND_REF,
        {
            "choice_key": "land-bonus-cantrip",
            "label": "Circle of the Land — Bonus Cantrip",
            "minimum_class_level": 2,
            "choose_total": 1,
            "grant_target": "spell",
            "option_pool": "druid_cantrips",
            "access_type": "granted",
        },
    )


def _normalize_shepherd_language(registry: M01JReferenceRegistry) -> None:
    _merge_fixed_grant(registry, SHEPHERD_REF, "languages", SYLVAN_REF)


def _normalize_stars_star_map(registry: M01JReferenceRegistry) -> None:
    _merge_spell_record(
        registry,
        STARS_REF,
        spell_ref=GUIDING_BOLT_REF,
        minimum_class_level=2,
        access_type="always_prepared",
    )
    feature_ref = _fixes._feature_ref_by_name(registry, STARS_REF, "Star Map")
    feature = _require(registry, feature_ref)
    data = dict(feature.data)
    data["resource"] = {
        "capacity": {"type": "proficiency_bonus"},
        "recharge": ["long_rest"],
    }
    _fixes._replace_entry(registry, feature.model_copy(update={"data": data}))


def _validate_arcana_proficiency(registry: M01JReferenceRegistry) -> None:
    subclass = _require(registry, ARCANA_REF)
    fixed = subclass.data.get("fixed_grants")
    skills = fixed.get("skills") if isinstance(fixed, dict) else None
    if not isinstance(skills, (list, tuple)) or ARCANA_SKILL_REF not in skills:
        raise ContentValidationError(
            "M01-J Arcana Domain must preserve Arcana skill proficiency from Arcane Initiate"
        )


def apply_m01j_static_sweep(registry: ContentRegistry) -> ContentRegistry:
    """Close permanent rules found by the final M01-J static source sweep."""

    if not isinstance(registry, M01JReferenceRegistry):
        raise ContentValidationError("M01-J static sweep requires M01JReferenceRegistry")
    _normalize_land_bonus_cantrip(registry)
    _normalize_shepherd_language(registry)
    _normalize_stars_star_map(registry)
    _validate_arcana_proficiency(registry)
    return registry
