from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from app.content import m01j_reference_fixes as _fixes
from app.content.identity import parse_stable_key, stable_key
from app.content.m01j_reference_content import M01JReferenceRegistry
from app.content.registry import ContentRegistry, ContentValidationError


# Final source-id correction and small permanent-grant additions found during
# the second static rules pass. Keeping these edits in one layer makes the
# generic parser remain source-layout agnostic while the normalized runtime is
# explicit and machine-verifiable.


def _merge_fixed_grant(subclass_ref: str, field: str, *refs: str) -> None:
    current = deepcopy(_fixes.FIXED_GRANTS.get(subclass_ref, {}))
    values = list(current.get(field, ()))
    values.extend(refs)
    current[field] = tuple(dict.fromkeys(values))
    _fixes.FIXED_GRANTS[subclass_ref] = current


def _append_grant_choice(subclass_ref: str, choice: dict[str, Any]) -> None:
    current = list(_fixes.GRANT_CHOICES.get(subclass_ref, ()))
    key = choice.get("choice_key")
    if not any(isinstance(item, dict) and item.get("choice_key") == key for item in current):
        current.append(choice)
    _fixes.GRANT_CHOICES[subclass_ref] = tuple(current)


def _append_fixed_spell(
    subclass_ref: str,
    *,
    minimum_class_level: int,
    spell_ref: str,
    access_type: str = "granted",
) -> None:
    current = list(_fixes.FIXED_SPELLS.get(subclass_ref, ()))
    identity = (minimum_class_level, spell_ref, access_type)
    known = {
        (
            int(item.get("minimum_class_level", 0)),
            str(item.get("spell_ref", "")),
            str(item.get("access_type", "")),
        )
        for item in current
        if isinstance(item, dict)
    }
    if identity not in known:
        current.append(
            {
                "minimum_class_level": minimum_class_level,
                "spell_ref": spell_ref,
                "access_type": access_type,
            }
        )
    _fixes.FIXED_SPELLS[subclass_ref] = tuple(current)


def _prepare_completion_constants() -> None:
    # Circle of Spores is in TCE for this M01 baseline. The initial static pass
    # used its pre-TCE publication lineage accidentally; normalize to the
    # canonical M01 source identity before applying any metadata.
    stale_spores = _fixes.FIXED_SPELLS.pop("xge:subclass:spores", ())
    if stale_spores:
        current = list(_fixes.FIXED_SPELLS.get("tce:subclass:spores", ()))
        current.extend(stale_spores)
        _fixes.FIXED_SPELLS["tce:subclass:spores"] = tuple(current)

    _merge_fixed_grant("scag:subclass:arcana", "skills", "srd5.1:skill:arcana")

    _append_grant_choice(
        "tce:subclass:fey-wanderer",
        {
            "choice_key": "fey-wanderer-skill",
            "label": "Otherworldly Glamour — skill",
            "minimum_class_level": 3,
            "choose_total": 1,
            "grant_target": "skill",
            "option_refs": (
                "srd5.1:skill:deception",
                "srd5.1:skill:performance",
                "srd5.1:skill:persuasion",
            ),
        },
    )

    _append_fixed_spell(
        "tce:subclass:swarmkeeper",
        minimum_class_level=3,
        spell_ref="srd5.1:spell:mage-hand",
    )
    _append_fixed_spell(
        "phb2014:subclass:illusion",
        minimum_class_level=2,
        spell_ref="srd5.1:spell:minor-illusion",
    )


def _subclass_level_features(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    level: int,
) -> tuple[str, ...]:
    refs: list[str] = []
    for feature in registry.list_kind("feature"):
        parent = feature.data.get("subclass")
        if (
            isinstance(parent, dict)
            and parent.get("key") == subclass_ref
            and feature.data.get("level") == level
        ):
            refs.append(feature.key)
    return tuple(refs)


def _remove_automatic_features(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    level: int,
    refs: Iterable[str],
) -> None:
    remove = set(refs)
    if not remove:
        return
    parsed = parse_stable_key(subclass_ref, kinds={"subclass"})
    level_ref = stable_key(parsed.source, "level", f"{parsed.index}-{level}")
    level_entry = registry.get_optional(level_ref)
    if level_entry is None:
        raise ContentValidationError(f"{subclass_ref}: missing subclass level row {level}")
    raw_features = level_entry.data.get("features")
    if not isinstance(raw_features, list):
        raise ContentValidationError(f"{level_ref}: features must be a list")
    next_features = [
        reference
        for reference in raw_features
        if not (isinstance(reference, dict) and reference.get("key") in remove)
    ]
    data = dict(level_entry.data)
    data["features"] = next_features
    _fixes._replace_entry(registry, level_entry.model_copy(update={"data": data}))

    subclass = registry.get(subclass_ref)
    declared = subclass.data.get("progression_feature_refs", [])
    if isinstance(declared, list):
        _fixes._update_subclass_data(
            registry,
            subclass_ref,
            progression_feature_refs=[ref for ref in declared if ref not in remove],
        )


def _normalize_totem_warrior(registry: M01JReferenceRegistry) -> None:
    subclass_ref = "phb2014:subclass:totem-warrior"
    subclass = registry.get(subclass_ref)
    choices = [
        choice
        for choice in subclass.data.get("persistent_choices", [])
        if isinstance(choice, dict)
    ]
    known_keys = {choice.get("choice_key") for choice in choices}
    for level, key, label in (
        (6, "aspect-of-the-beast", "Aspect of the Beast"),
        (14, "totemic-attunement", "Totemic Attunement"),
    ):
        option_refs = tuple(
            ref
            for ref in _subclass_level_features(registry, subclass_ref, level)
            if registry.get(ref).name in {"Bear", "Eagle", "Elk", "Tiger", "Wolf"}
        )
        if len(option_refs) < 5:
            raise ContentValidationError(
                f"{subclass_ref}: expected five {label} options at class level {level}"
            )
        _remove_automatic_features(registry, subclass_ref, level, option_refs)
        if key not in known_keys:
            choices.append(
                {
                    "choice_key": key,
                    "minimum_class_level": level,
                    "choose_total": 1,
                    "progression": (),
                    "option_refs": option_refs,
                    "option_minimum_levels": {},
                    "label": label,
                }
            )
    _fixes._update_subclass_data(registry, subclass_ref, persistent_choices=choices)


def _normalize_storm_herald_branches(registry: M01JReferenceRegistry) -> None:
    subclass_ref = "xge:subclass:storm-herald"
    subclass = registry.get(subclass_ref)
    raw_choices = subclass.data.get("persistent_choices", [])
    environment_choice = next(
        (
            choice
            for choice in raw_choices
            if isinstance(choice, dict) and choice.get("choice_key") == "storm-aura-environment"
        ),
        None,
    )
    if not isinstance(environment_choice, dict):
        return
    option_refs = [ref for ref in environment_choice.get("option_refs", ()) if isinstance(ref, str)]
    by_name = {registry.get(ref).name: ref for ref in option_refs}
    branch_names = set(by_name)
    if not branch_names:
        return
    progression_by_name: dict[str, dict[int, str]] = {name: {} for name in branch_names}
    for level in (6, 10, 14):
        branch_refs = tuple(
            ref
            for ref in _subclass_level_features(registry, subclass_ref, level)
            if registry.get(ref).name in branch_names
        )
        for ref in branch_refs:
            progression_by_name[registry.get(ref).name][level] = ref
        _remove_automatic_features(registry, subclass_ref, level, branch_refs)

    for name, option_ref in by_name.items():
        option = registry.get(option_ref)
        data = dict(option.data)
        data["branch_progression_refs"] = {
            str(level): ref for level, ref in sorted(progression_by_name[name].items())
        }
        _fixes._replace_entry(registry, option.model_copy(update={"data": data}))


def _normalize_zealot_damage_type(registry: M01JReferenceRegistry) -> None:
    subclass_ref = "xge:subclass:zealot"
    feature_ref = _fixes._feature_ref_by_name(registry, subclass_ref, "Divine Fury")
    option_refs = (
        _fixes._new_option_feature(
            registry,
            subclass_ref,
            suffix="divine-fury-necrotic",
            name="Necrotic Divine Fury",
            zh_name="黯蝕神性狂怒",
            source_feature_ref=feature_ref,
        ),
        _fixes._new_option_feature(
            registry,
            subclass_ref,
            suffix="divine-fury-radiant",
            name="Radiant Divine Fury",
            zh_name="光耀神性狂怒",
            source_feature_ref=feature_ref,
        ),
    )
    subclass = registry.get(subclass_ref)
    choices = [
        choice
        for choice in subclass.data.get("persistent_choices", [])
        if isinstance(choice, dict) and choice.get("choice_key") != "divine-fury-damage-type"
    ]
    choices.append(
        _fixes._make_choice(
            key="divine-fury-damage-type",
            feature_ref=feature_ref,
            label="Divine Fury Damage Type",
            level=3,
            count=1,
            option_refs=option_refs,
        )
    )
    _fixes._update_subclass_data(registry, subclass_ref, persistent_choices=choices)


def _remove_false_persistent_choices(registry: M01JReferenceRegistry) -> None:
    # These H5 groups are choices made when a feature is activated, not immutable
    # character-build choices. Kensei's real permanent weapon/tool choices are
    # represented separately by grant_choices.
    for subclass_ref in (
        "xge:subclass:kensei",
        "xge:subclass:shepherd",
        "tce:subclass:stars",
    ):
        if registry.get_optional(subclass_ref) is not None:
            _fixes._update_subclass_data(registry, subclass_ref, persistent_choices=[])


def _normalize_post_generation(registry: ContentRegistry) -> ContentRegistry:
    if not isinstance(registry, M01JReferenceRegistry):
        raise ContentValidationError("M01-J completion requires M01JReferenceRegistry")
    _normalize_totem_warrior(registry)
    _normalize_storm_herald_branches(registry)
    _normalize_zealot_damage_type(registry)
    _remove_false_persistent_choices(registry)
    return registry


def apply_m01j_reference_completion(registry: ContentRegistry) -> ContentRegistry:
    _prepare_completion_constants()
    registry = _fixes.apply_m01j_reference_fixes(registry)
    return _normalize_post_generation(registry)
