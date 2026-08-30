from __future__ import annotations

from collections import Counter

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.registry import ContentNotFoundError, ContentRegistry
from app.domain.character.schemas import CharacterBuild, CharacterState
from app.domain.rules.hit_points import calculate_max_hp
from app.domain.rules.spellcasting import (
    initial_spell_resource_state,
    resource_counter_matches_capacity,
    spell_is_on_class_list,
)


class CharacterValidationError(ValueError):
    pass


def _require_content(registry: ContentRegistry, key: str) -> None:
    try:
        registry.get(key)
    except ContentNotFoundError as exc:
        raise CharacterValidationError(f"unknown content reference: {key}") from exc


def build_content_reference_keys(build: CharacterBuild) -> tuple[str, ...]:
    """Return only persisted fields whose contract is a content reference.

    This deliberately does not walk arbitrary Build strings. Roleplay prose,
    labels, ids and other free text may happen to resemble StableKeys, but they
    are not content provenance. Keeping this list explicit makes
    ``content_sources`` a projection of the Build reference contract.
    """

    refs: list[str] = [build.race_ref, *build.class_progression]
    if build.subrace_ref:
        refs.append(build.subrace_ref)
    if build.background_ref:
        refs.append(build.background_ref)
    if build.alignment_ref:
        refs.append(build.alignment_ref)

    for selection in build.subclasses:
        refs.extend((selection.class_ref, selection.subclass_ref))
    refs.extend(build.proficiencies)
    refs.extend(build.saving_throw_proficiencies)
    refs.extend(build.skill_choices)
    refs.extend(build.language_refs)
    refs.extend(build.feature_refs)
    refs.extend(build.feat_refs)
    for profile in build.spellcasting_profiles:
        refs.extend((profile.source_key, profile.class_ref))
    for entry in build.spell_access_entries:
        refs.extend((entry.spell_key, entry.source_key))
    refs.extend(entry.item_ref for entry in build.starting_equipment)

    # Numeric Override keys are mostly symbolic strings. Only the documented
    # override forms whose suffix is itself a StableKey participate in content
    # provenance; never scan the whole key as free text.
    for override in build.numeric_overrides:
        for prefix in ("skill_modifier:", "spell_save_dc:"):
            if not override.key.startswith(prefix):
                continue
            target = override.key.removeprefix(prefix)
            try:
                parse_stable_key(target)
            except ValueError:
                pass
            else:
                refs.append(target)
            break

    return tuple(dict.fromkeys(refs))


def derive_content_sources(build: CharacterBuild) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                parse_stable_key(reference).source
                for reference in build_content_reference_keys(build)
            }
        )
    )


def _validate_numeric_overrides(build: CharacterBuild, registry: ContentRegistry) -> None:
    abilities = {"strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"}
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
                entry = registry.get(target) if ":" in target else registry.resolve("skill", target)
            except ContentNotFoundError as exc:
                raise CharacterValidationError(f"unknown skill override target: {target}") from exc
            if not entry.key.split(":", 2)[1] == "skill":
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
    for key in build_content_reference_keys(build):
        _require_content(registry, key)

    if build.subrace_ref is not None:
        subrace = registry.get(build.subrace_ref)
        parent = subrace.data.get("race")
        try:
            parent_ref = (
                reference_to_stable_key(parent, kinds={"race"})
                if isinstance(parent, dict)
                else None
            )
        except ValueError:
            parent_ref = None
        if parent_ref != build.race_ref:
            raise CharacterValidationError(
                f"subrace {build.subrace_ref} does not belong to race {build.race_ref}"
            )

    _validate_numeric_overrides(build, registry)


def derive_hit_dice_totals(build: CharacterBuild, registry: ContentRegistry) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for class_ref in build.class_progression:
        entry = registry.get(class_ref)
        hit_die = entry.data.get("hit_die")
        if hit_die not in {6, 8, 10, 12}:
            raise CharacterValidationError(f"{class_ref} has invalid hit die: {hit_die!r}")
        totals[f"d{hit_die}"] += 1
    return dict(totals)


def _validate_prepared_spells(
    state: CharacterState,
    build: CharacterBuild,
    registry: ContentRegistry,
) -> None:
    access_by_id = {entry.entry_id: entry for entry in build.spell_access_entries}

    for entry_id in state.prepared_spell_entry_ids:
        access = access_by_id.get(entry_id)
        if access is None:
            raise CharacterValidationError(f"prepared spell entry does not exist in build: {entry_id}")
        if access.access_type != "spellbook":
            raise CharacterValidationError(f"prepared spell entry is not prepareable in P0: {entry_id}")

    profile_by_id = {profile.profile_id: profile for profile in build.spellcasting_profiles}
    prepared_counts: Counter[str] = Counter()
    for selection in state.prepared_spells:
        _require_content(registry, selection.spell_key)
        profile = profile_by_id.get(selection.source_profile_id)
        if profile is None:
            raise CharacterValidationError(
                f"prepared spell source profile does not exist in build: {selection.source_profile_id}"
            )
        if profile.access_model not in {"prepared", "spellbook"}:
            raise CharacterValidationError(
                f"spellcasting profile does not support a prepared list: {selection.source_profile_id}"
            )
        prepared_counts[profile.profile_id] += 1

        if selection.source_access_entry_id is not None:
            access = access_by_id.get(selection.source_access_entry_id)
            if access is None:
                raise CharacterValidationError(
                    f"prepared spell source access entry does not exist: {selection.source_access_entry_id}"
                )
            if profile.access_model != "spellbook":
                raise CharacterValidationError(
                    f"only spellbook profiles may prepare through a source access entry: {profile.profile_id}"
                )
            if access.access_type != "spellbook" or access.spell_key != selection.spell_key:
                raise CharacterValidationError(
                    f"prepared spell source access entry is not a matching spellbook entry: {selection.source_access_entry_id}"
                )
            if access.source_type != profile.source_type or access.source_key != profile.source_key:
                raise CharacterValidationError(
                    f"prepared spell source access entry belongs to a different profile: {selection.source_access_entry_id}"
                )
            continue

        if profile.access_model == "spellbook":
            raise CharacterValidationError(
                f"spellbook prepared spell must reference its Build access entry: {selection.spell_key}"
            )
        if not spell_is_on_class_list(selection.spell_key, profile.class_ref, registry):
            raise CharacterValidationError(
                f"prepared spell is not on source class list: {selection.spell_key} / {profile.class_ref}"
            )
        spell = registry.get(selection.spell_key)
        level = spell.data.get("level")
        if not isinstance(level, int) or level < 1 or level > profile.max_spell_level:
            raise CharacterValidationError(
                f"prepared spell level is not eligible for source profile: {selection.spell_key}"
            )

    for profile_id, count in prepared_counts.items():
        profile = profile_by_id[profile_id]
        if profile.prepared_limit is not None and count > profile.prepared_limit:
            raise CharacterValidationError(
                f"prepared spell count exceeds profile limit: {profile_id} {count}>{profile.prepared_limit}"
            )


def _validate_spell_resources(state: CharacterState, build: CharacterBuild) -> None:
    if not build.spell_resource_pools:
        return

    expected_slots, expected_resources = initial_spell_resource_state(build)
    if set(state.spell_slots) != set(expected_slots):
        raise CharacterValidationError(
            "live normal spell-slot levels must match Build spell resource capacity"
        )
    for level, expected in expected_slots.items():
        if not resource_counter_matches_capacity(state.spell_slots[level], expected.remaining):
            raise CharacterValidationError(
                f"live spell slot usage does not match Build capacity at level {level}"
            )

    for key, expected in expected_resources.items():
        counter = state.resources.get(key)
        if counter is None:
            raise CharacterValidationError(f"missing live spell resource counter: {key}")
        if not resource_counter_matches_capacity(counter, expected.remaining):
            raise CharacterValidationError(
                f"live spell resource usage does not match Build capacity: {key}"
            )


def validate_state_against_build(
    state: CharacterState,
    build: CharacterBuild,
    registry: ContentRegistry,
) -> None:
    _validate_prepared_spells(state, build, registry)
    _validate_spell_resources(state, build)

    for condition in state.conditions:
        _require_content(registry, condition.condition_ref)
    for item in state.inventory_state:
        _require_content(registry, item.item_ref)

    totals = derive_hit_dice_totals(build, registry)
    for die, available in state.hit_dice_state.items():
        total = totals.get(die, 0)
        if available > total:
            raise CharacterValidationError(f"available hit dice exceed build total for {die}: {available}>{total}")

    max_hp = calculate_max_hp(build)
    if state.current_hp > max_hp:
        raise CharacterValidationError(
            f"current_hp cannot exceed calculated max_hp: {state.current_hp}>{max_hp}"
        )
