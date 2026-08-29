from __future__ import annotations

from collections import Counter

from app.content.registry import ContentNotFoundError, ContentRegistry
from app.domain.character.schemas import CharacterBuild, CharacterState
from app.domain.rules.hit_points import calculate_max_hp


class CharacterValidationError(ValueError):
    pass


def _require_content(registry: ContentRegistry, key: str) -> None:
    try:
        registry.get(key)
    except ContentNotFoundError as exc:
        raise CharacterValidationError(f"unknown content reference: {key}") from exc


def _validate_numeric_overrides(build: CharacterBuild, registry: ContentRegistry) -> None:
    abilities = {
        "strength",
        "dexterity",
        "constitution",
        "intelligence",
        "wisdom",
        "charisma",
    }
    for override in build.numeric_overrides:
        key = override.key
        value = override.value
        if not float(value).is_integer():
            raise CharacterValidationError(f"numeric override must be an integer: {key}")
        if key.startswith("ability:"):
            ability = key.removeprefix("ability:")
            if ability not in abilities or value < 1 or value > 30:
                raise CharacterValidationError(f"invalid ability numeric override: {key}")
            continue
        if key == "ac":
            if value < 1:
                raise CharacterValidationError("ac override must be positive")
            continue
        if key == "max_hp":
            if value < 1:
                raise CharacterValidationError("max_hp override must be positive")
            continue
        if key.startswith("skill_modifier:"):
            target = key.removeprefix("skill_modifier:")
            try:
                if target.startswith("srd5.1:"):
                    entry = registry.get(target)
                else:
                    entry = registry.resolve("skill", target)
            except ContentNotFoundError as exc:
                raise CharacterValidationError(
                    f"unknown skill override target: {target}"
                ) from exc
            if not entry.key.startswith("srd5.1:skill:"):
                raise CharacterValidationError(f"invalid skill override target: {target}")
            continue
        if key.startswith("spell_save_dc:"):
            target = key.removeprefix("spell_save_dc:")
            _require_content(registry, target)
            if value < 1:
                raise CharacterValidationError("spell save DC override must be positive")
            continue
        raise CharacterValidationError(f"unsupported numeric override key: {key}")


def validate_build_references(build: CharacterBuild, registry: ContentRegistry) -> None:
    refs: list[str] = [build.race_ref, *build.class_progression]
    if build.background_ref:
        refs.append(build.background_ref)
    if build.alignment_ref:
        refs.append(build.alignment_ref)

    refs.extend(selection.subclass_ref for selection in build.subclasses)
    refs.extend(build.proficiencies)
    refs.extend(build.saving_throw_proficiencies)
    refs.extend(build.skill_choices)
    refs.extend(build.feature_refs)
    refs.extend(build.feat_refs)
    refs.extend(entry.spell_key for entry in build.spell_access_entries)
    refs.extend(entry.source_key for entry in build.spell_access_entries)
    refs.extend(entry.item_ref for entry in build.starting_equipment)

    for key in refs:
        _require_content(registry, key)
    _validate_numeric_overrides(build, registry)


def derive_hit_dice_totals(
    build: CharacterBuild, registry: ContentRegistry
) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for class_ref in build.class_progression:
        entry = registry.get(class_ref)
        hit_die = entry.data.get("hit_die")
        if hit_die not in {6, 8, 10, 12}:
            raise CharacterValidationError(f"{class_ref} has invalid hit die: {hit_die!r}")
        totals[f"d{hit_die}"] += 1
    return dict(totals)


def validate_state_against_build(
    state: CharacterState,
    build: CharacterBuild,
    registry: ContentRegistry,
) -> None:
    access_by_id = {entry.entry_id: entry for entry in build.spell_access_entries}
    for entry_id in state.prepared_spell_entry_ids:
        access = access_by_id.get(entry_id)
        if access is None:
            raise CharacterValidationError(
                f"prepared spell entry does not exist in build: {entry_id}"
            )
        if access.access_type != "spellbook":
            raise CharacterValidationError(
                f"prepared spell entry is not prepareable in P0: {entry_id}"
            )

    for condition in state.conditions:
        _require_content(registry, condition.condition_ref)
    for item in state.inventory_state:
        _require_content(registry, item.item_ref)

    totals = derive_hit_dice_totals(build, registry)
    for die, available in state.hit_dice_state.items():
        total = totals.get(die, 0)
        if available > total:
            raise CharacterValidationError(
                f"available hit dice exceed build total for {die}: {available}>{total}"
            )

    max_hp = calculate_max_hp(build)
    if state.current_hp > max_hp:
        raise CharacterValidationError(
            f"current_hp cannot exceed calculated max_hp: {state.current_hp}>{max_hp}"
        )
