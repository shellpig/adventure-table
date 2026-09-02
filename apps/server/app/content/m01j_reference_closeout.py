from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from app.content import m01j_reference_fixes as _fixes
from app.content.identity import reference_to_stable_key
from app.content.m01j_reference_content import M01JReferenceRegistry
from app.content.registry import ContentRegistry, ContentValidationError


ARCANA_REF = "scag:subclass:arcana"
ILLUSION_REF = "phb2014:subclass:illusion"
CLOCKWORK_REF = "tce:subclass:clockwork-soul"
ABERRANT_REF = "tce:subclass:aberrant-mind"


def _spell_on_class_list(registry: ContentRegistry, spell: object, class_ref: str) -> bool:
    data = getattr(spell, "data", None)
    if not isinstance(data, dict):
        return False
    raw_classes = data.get("classes")
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
                if reference_to_stable_key(reference, kinds={"spell"}) == getattr(spell, "key", None):
                    return True
            except ValueError:
                continue
    return False


def _spell_refs_for_class_level(
    registry: ContentRegistry,
    class_ref: str,
    spell_level: int,
) -> tuple[str, ...]:
    refs = tuple(
        spell.key
        for spell in registry.list_kind("spell")
        if spell.data.get("level") == spell_level
        and _spell_on_class_list(registry, spell, class_ref)
    )
    return tuple(sorted(dict.fromkeys(refs)))


def _append_grant_choices(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    choices: Iterable[dict[str, Any]],
) -> None:
    subclass = registry.get(subclass_ref)
    current = [
        deepcopy(choice)
        for choice in subclass.data.get("grant_choices", [])
        if isinstance(choice, dict)
    ]
    by_key = {
        choice.get("choice_key"): index
        for index, choice in enumerate(current)
        if isinstance(choice.get("choice_key"), str)
    }
    for choice in choices:
        key = choice.get("choice_key")
        if not isinstance(key, str) or not key:
            raise ContentValidationError(f"{subclass_ref}: invalid closeout grant choice key")
        normalized = deepcopy(choice)
        if key in by_key:
            current[by_key[key]] = normalized
        else:
            by_key[key] = len(current)
            current.append(normalized)
    _fixes._update_subclass_data(registry, subclass_ref, grant_choices=current)


def _normalize_arcana_mastery(registry: M01JReferenceRegistry) -> None:
    if registry.get_optional(ARCANA_REF) is None:
        raise ContentValidationError("M01-J Arcana Domain is missing")
    choices: list[dict[str, Any]] = []
    for spell_level in (6, 7, 8, 9):
        refs = _spell_refs_for_class_level(
            registry,
            "srd5.1:class:wizard",
            spell_level,
        )
        if not refs:
            raise ContentValidationError(
                f"M01-J Arcane Mastery has no Wizard spell options at spell level {spell_level}"
            )
        choices.append(
            {
                "choice_key": f"arcane-mastery-{spell_level}",
                "label": f"Arcane Mastery — level {spell_level} spell",
                "minimum_class_level": 17,
                "choose_total": 1,
                "grant_target": "spell",
                "option_refs": refs,
                "access_type": "always_prepared",
            }
        )
    _append_grant_choices(registry, ARCANA_REF, choices)


def _remove_unconditional_illusion_cantrip(registry: M01JReferenceRegistry) -> None:
    subclass = registry.get(ILLUSION_REF)
    rows = subclass.data.get("spells", [])
    if not isinstance(rows, list):
        return
    filtered: list[dict[str, Any]] = []
    removed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_spell = row.get("spell")
        spell_ref = None
        if isinstance(raw_spell, dict):
            try:
                spell_ref = reference_to_stable_key(raw_spell, kinds={"spell"})
            except ValueError:
                spell_ref = None
        if spell_ref == "srd5.1:spell:minor-illusion":
            removed += 1
            continue
        filtered.append(row)
    if removed == 0:
        raise ContentValidationError(
            "M01-J Illusion closeout expected the temporary unconditional Minor Illusion grant"
        )
    _fixes._update_subclass_data(registry, ILLUSION_REF, spells=filtered)


def _attach_spell_replacement_metadata(
    registry: M01JReferenceRegistry,
    subclass_ref: str,
    *,
    school_indices: tuple[str, ...],
) -> None:
    subclass = registry.get(subclass_ref)
    rows = subclass.data.get("spells")
    if not isinstance(rows, list) or not rows:
        raise ContentValidationError(
            f"{subclass_ref}: replaceable subclass spell feature has no generated spell rows"
        )
    original_refs: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("access_type") != "granted":
            raise ContentValidationError(
                f"{subclass_ref}: replaceable subclass spell rows must use granted access"
            )
        raw_spell = row.get("spell")
        if not isinstance(raw_spell, dict):
            raise ContentValidationError(
                f"{subclass_ref}: replaceable subclass spell row is missing a spell reference"
            )
        try:
            spell_ref = reference_to_stable_key(raw_spell, kinds={"spell"})
        except ValueError as exc:
            raise ContentValidationError(
                f"{subclass_ref}: invalid replaceable subclass spell reference"
            ) from exc
        if spell_ref is None or registry.get_optional(spell_ref) is None:
            raise ContentValidationError(
                f"{subclass_ref}: missing replaceable subclass spell {spell_ref}"
            )
        original_refs.append(spell_ref)
    if len(original_refs) != len(set(original_refs)):
        raise ContentValidationError(
            f"{subclass_ref}: replaceable subclass spell table contains duplicate spell identities"
        )
    _fixes._update_subclass_data(
        registry,
        subclass_ref,
        subclass_spell_replacement={
            "eligible_class_refs": (
                "srd5.1:class:sorcerer",
                "srd5.1:class:warlock",
                "srd5.1:class:wizard",
            ),
            "school_indices": school_indices,
            "one_replacement_per_class_level": True,
        },
    )


def apply_m01j_reference_closeout(registry: ContentRegistry) -> ContentRegistry:
    """Finish M01-J spell-choice semantics that require cross-feature context."""

    if not isinstance(registry, M01JReferenceRegistry):
        raise ContentValidationError("M01-J reference closeout requires M01JReferenceRegistry")
    _normalize_arcana_mastery(registry)
    _remove_unconditional_illusion_cantrip(registry)
    _attach_spell_replacement_metadata(
        registry,
        CLOCKWORK_REF,
        school_indices=("abjuration", "transmutation"),
    )
    _attach_spell_replacement_metadata(
        registry,
        ABERRANT_REF,
        school_indices=("divination", "enchantment"),
    )
    return registry
