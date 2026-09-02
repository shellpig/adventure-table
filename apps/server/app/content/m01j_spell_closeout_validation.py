from __future__ import annotations

from typing import Any

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.registry import ContentRegistry, ContentValidationError


ARCANA_REF = "scag:subclass:arcana"
ILLUSION_REF = "phb2014:subclass:illusion"
CLOCKWORK_REF = "tce:subclass:clockwork-soul"
ABERRANT_REF = "tce:subclass:aberrant-mind"


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


def _spell_school_index(spell: Any) -> str | None:
    raw = spell.data.get("school")
    if not isinstance(raw, dict):
        return None
    try:
        ref = reference_to_stable_key(raw, kinds={"magic-school"})
    except ValueError:
        ref = None
    if ref is not None:
        return parse_stable_key(ref).index
    index = raw.get("index")
    return index if isinstance(index, str) else None


def _validate_arcana_mastery(registry: ContentRegistry) -> None:
    subclass = registry.get_optional(ARCANA_REF)
    if subclass is None:
        raise ContentValidationError("M01-J Arcana Domain closeout subclass is missing")
    raw_choices = subclass.data.get("grant_choices")
    if not isinstance(raw_choices, list):
        raise ContentValidationError("M01-J Arcana Domain grant choices are missing")
    by_key = {
        raw.get("choice_key"): raw
        for raw in raw_choices
        if isinstance(raw, dict) and isinstance(raw.get("choice_key"), str)
    }
    for spell_level in (6, 7, 8, 9):
        key = f"arcane-mastery-{spell_level}"
        raw = by_key.get(key)
        if not isinstance(raw, dict):
            raise ContentValidationError(f"{ARCANA_REF}: missing {key}")
        if raw.get("minimum_class_level") != 17 or raw.get("choose_total") != 1:
            raise ContentValidationError(f"{ARCANA_REF}/{key}: invalid Arcane Mastery choice shape")
        if raw.get("grant_target") != "spell" or raw.get("access_type") != "always_prepared":
            raise ContentValidationError(f"{ARCANA_REF}/{key}: invalid Arcane Mastery spell access")
        refs = raw.get("option_refs")
        if not isinstance(refs, (list, tuple)) or not refs:
            raise ContentValidationError(f"{ARCANA_REF}/{key}: no Wizard spell options")
        for ref in refs:
            spell = registry.get_optional(ref) if isinstance(ref, str) else None
            if (
                spell is None
                or parse_stable_key(spell.key).kind != "spell"
                or spell.data.get("level") != spell_level
                or not _spell_on_class_list(registry, spell, "srd5.1:class:wizard")
            ):
                raise ContentValidationError(
                    f"{ARCANA_REF}/{key}: illegal Arcane Mastery option {ref}"
                )


def _validate_illusion_closeout(registry: ContentRegistry) -> None:
    subclass = registry.get_optional(ILLUSION_REF)
    if subclass is None:
        raise ContentValidationError("M01-J Illusion closeout subclass is missing")
    rows = subclass.data.get("spells", [])
    if not isinstance(rows, list):
        raise ContentValidationError(f"{ILLUSION_REF}: spells must be a list")
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_spell = row.get("spell")
        if not isinstance(raw_spell, dict):
            continue
        try:
            ref = reference_to_stable_key(raw_spell, kinds={"spell"})
        except ValueError:
            ref = None
        if ref == "srd5.1:spell:minor-illusion":
            raise ContentValidationError(
                f"{ILLUSION_REF}: Minor Illusion must be conditional, not an unconditional subclass spell row"
            )


def _validate_spell_replacement(
    registry: ContentRegistry,
    subclass_ref: str,
    expected_schools: set[str],
) -> None:
    subclass = registry.get_optional(subclass_ref)
    if subclass is None:
        raise ContentValidationError(f"M01-J spell-replacement subclass is missing: {subclass_ref}")
    spec = subclass.data.get("subclass_spell_replacement")
    if not isinstance(spec, dict):
        raise ContentValidationError(f"{subclass_ref}: subclass_spell_replacement is missing")
    classes = spec.get("eligible_class_refs")
    expected_classes = {
        "srd5.1:class:sorcerer",
        "srd5.1:class:warlock",
        "srd5.1:class:wizard",
    }
    if not isinstance(classes, (list, tuple)) or set(classes) != expected_classes:
        raise ContentValidationError(f"{subclass_ref}: invalid replacement source class set")
    for class_ref in classes:
        parent = registry.get_optional(class_ref) if isinstance(class_ref, str) else None
        if parent is None or parse_stable_key(parent.key).kind != "class":
            raise ContentValidationError(f"{subclass_ref}: invalid replacement source class {class_ref}")
    schools = spec.get("school_indices")
    if not isinstance(schools, (list, tuple)) or set(schools) != expected_schools:
        raise ContentValidationError(f"{subclass_ref}: invalid replacement school set")
    if spec.get("one_replacement_per_class_level") is not True:
        raise ContentValidationError(
            f"{subclass_ref}: subclass spell replacement must be limited to one per gained class level"
        )

    rows = subclass.data.get("spells")
    if not isinstance(rows, list) or not rows:
        raise ContentValidationError(f"{subclass_ref}: replaceable subclass spell rows are missing")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("access_type") != "granted":
            raise ContentValidationError(f"{subclass_ref}: invalid replaceable subclass spell row")
        raw_spell = row.get("spell")
        if not isinstance(raw_spell, dict):
            raise ContentValidationError(f"{subclass_ref}: replaceable spell row has no spell reference")
        try:
            ref = reference_to_stable_key(raw_spell, kinds={"spell"})
        except ValueError as exc:
            raise ContentValidationError(
                f"{subclass_ref}: invalid replaceable spell reference"
            ) from exc
        spell = registry.get_optional(ref) if ref is not None else None
        if spell is None:
            raise ContentValidationError(f"{subclass_ref}: missing replaceable spell {ref}")
        if ref in seen:
            raise ContentValidationError(f"{subclass_ref}: duplicate replaceable spell {ref}")
        seen.add(ref)

    # The replacement universe must have at least one legal option at every
    # spell level represented by the feature. The original spell is always a
    # legal keep-current option; this gate protects the actual replacement path.
    spell_levels = {
        int(registry.get(ref).data["level"])
        for ref in seen
        if isinstance(registry.get(ref).data.get("level"), int)
    }
    for spell_level in spell_levels:
        candidates = [
            spell
            for spell in registry.list_kind("spell")
            if spell.data.get("level") == spell_level
            and _spell_school_index(spell) in expected_schools
            and any(_spell_on_class_list(registry, spell, class_ref) for class_ref in expected_classes)
        ]
        if not candidates:
            raise ContentValidationError(
                f"{subclass_ref}: no legal replacement candidates at spell level {spell_level}"
            )


def validate_m01j_spell_closeout(registry: ContentRegistry) -> ContentRegistry:
    _validate_arcana_mastery(registry)
    _validate_illusion_closeout(registry)
    _validate_spell_replacement(
        registry,
        CLOCKWORK_REF,
        {"abjuration", "transmutation"},
    )
    _validate_spell_replacement(
        registry,
        ABERRANT_REF,
        {"divination", "enchantment"},
    )
    return registry
