from __future__ import annotations

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, ResourceCounter
from app.domain.rules.abilities import (
    ABILITY_INDEX_TO_NAME,
    ability_modifier,
    effective_ability_score,
    numeric_override,
)
from app.domain.rules.proficiency import proficiency_bonus, total_character_level


def spellcasting_ability(
    source_key: str,
    registry: ContentRegistry,
) -> str | None:
    source = registry.get(source_key)
    spellcasting = source.data.get("spellcasting")
    if not isinstance(spellcasting, dict):
        return None
    reference = spellcasting.get("spellcasting_ability")
    if not isinstance(reference, dict):
        return None
    ability_index = reference.get("index")
    if not isinstance(ability_index, str):
        return None
    return ABILITY_INDEX_TO_NAME.get(ability_index)


def spell_save_dc(
    build: CharacterBuild,
    source_key: str,
    registry: ContentRegistry,
) -> int | None:
    ability = spellcasting_ability(source_key, registry)
    if ability is None:
        return None
    result = (
        8
        + proficiency_bonus(total_character_level(build))
        + ability_modifier(effective_ability_score(build, ability))
    )
    override = numeric_override(build, f"spell_save_dc:{source_key}")
    return int(override) if override is not None else result


def spell_attack_modifier(
    build: CharacterBuild,
    source_key: str,
    registry: ContentRegistry,
) -> int | None:
    ability = spellcasting_ability(source_key, registry)
    if ability is None:
        return None
    return (
        proficiency_bonus(total_character_level(build))
        + ability_modifier(effective_ability_score(build, ability))
    )


def class_level(build: CharacterBuild, class_ref: str) -> int:
    return sum(1 for entry in build.class_progression if entry == class_ref)


def spell_is_on_class_list(spell_key: str, class_ref: str, registry: ContentRegistry) -> bool:
    spell = registry.get_optional(spell_key)
    if spell is None:
        return False
    try:
        parse_stable_key(spell.key, kinds={"spell"})
        parse_stable_key(class_ref, kinds={"class"})
    except ValueError:
        return False

    references = spell.data.get("classes")
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, dict):
                continue
            try:
                reference_key = reference_to_stable_key(reference, kinds={"class"})
            except ValueError:
                continue
            if reference_key == class_ref:
                return True

    # Non-SRD class packs can define their class list authoritatively on the
    # class entry because canonical SRD spell records cannot be mutated to add
    # cross-pack class references. This mirrors the Builder spell-list contract
    # and keeps Character Sheet / runtime validation source-aware.
    class_entry = registry.get_optional(class_ref)
    if class_entry is None:
        return False
    dedicated = class_entry.data.get("spell_list")
    if not isinstance(dedicated, list):
        return False
    for reference in dedicated:
        if not isinstance(reference, dict):
            continue
        try:
            reference_key = reference_to_stable_key(reference, kinds={"spell"})
        except ValueError:
            continue
        if reference_key == spell.key:
            return True
    return False


def max_spell_level_for_class(
    build: CharacterBuild,
    class_ref: str,
    registry: ContentRegistry,
) -> int:
    level = class_level(build, class_ref)
    if level <= 0:
        return 0
    try:
        class_source = parse_stable_key(class_ref, kinds={"class"}).source
    except ValueError:
        return 0

    level_entry = None
    for candidate in registry.list_kind("level", source=class_source):
        if candidate.data.get("level") != level or candidate.data.get("subclass") is not None:
            continue
        class_reference = candidate.data.get("class")
        if not isinstance(class_reference, dict):
            continue
        try:
            candidate_class_ref = reference_to_stable_key(
                class_reference,
                kinds={"class"},
            )
        except ValueError:
            continue
        if candidate_class_ref == class_ref:
            level_entry = candidate
            break

    if level_entry is None:
        return 0
    row = level_entry.data.get("spellcasting")
    if not isinstance(row, dict):
        return 0
    available = [
        spell_level
        for spell_level in range(1, 10)
        if isinstance(row.get(f"spell_slots_level_{spell_level}"), int)
        and int(row[f"spell_slots_level_{spell_level}"]) > 0
    ]
    return max(available, default=0)


def resource_counter_matches_capacity(counter: ResourceCounter, capacity: int) -> bool:
    """Shared invariant for Build-derived resource capacity versus live usage."""

    return counter.used + counter.remaining == capacity


def reconcile_resource_counter(
    counter: ResourceCounter | None,
    capacity: int,
) -> ResourceCounter:
    """Preserve legal usage when a Build change modifies capacity."""

    used = min(counter.used if counter is not None else 0, capacity)
    return ResourceCounter(used=used, remaining=capacity - used)


def pact_resource_key(pool_id: str, spell_level: int) -> str:
    """Stable Current State key for one Pact Magic slot tier."""

    return f"{pool_id}:slot:{spell_level}"


def initial_spell_resource_state(
    build: CharacterBuild,
) -> tuple[dict[int, ResourceCounter], dict[str, ResourceCounter]]:
    """Create full Current State counters from Build capacities.

    Normal multiclass slots use the dedicated state.spell_slots mapping. Pact
    Magic stays in state.resources under source-aware keys so the two pools can
    never be merged accidentally just because their source data uses similar
    slot-shaped field names.
    """

    spell_slots: dict[int, ResourceCounter] = {}
    resources: dict[str, ResourceCounter] = {}
    for pool in build.spell_resource_pools:
        for slot in pool.slots:
            counter = ResourceCounter(used=0, remaining=slot.capacity)
            if pool.pool_type == "normal_multiclass_slots":
                if slot.level in spell_slots:
                    raise ValueError(f"duplicate normal spell slot capacity for level {slot.level}")
                spell_slots[slot.level] = counter
            else:
                key = pact_resource_key(pool.pool_id, slot.level)
                if key in resources:
                    raise ValueError(f"duplicate Pact Magic resource key: {key}")
                resources[key] = counter
    return spell_slots, resources


def reconcile_spell_resource_state(
    build: CharacterBuild,
    current_spell_slots: dict[int, ResourceCounter],
    current_resources: dict[str, ResourceCounter],
) -> tuple[dict[int, ResourceCounter], dict[str, ResourceCounter]]:
    """Reconcile live spell resources after a legal Build capacity change.

    Existing usage is preserved up to the new capacity. Obsolete Pact Magic
    counters are removed, while unrelated generic resource counters remain
    untouched. This helper is intended for future level-up/build-edit workflows
    and keeps `used + remaining == capacity` true after reconciliation.
    """

    next_slots: dict[int, ResourceCounter] = {}
    expected_pact_keys: dict[str, int] = {}
    for pool in build.spell_resource_pools:
        for slot in pool.slots:
            if pool.pool_type == "normal_multiclass_slots":
                next_slots[slot.level] = reconcile_resource_counter(
                    current_spell_slots.get(slot.level),
                    slot.capacity,
                )
            else:
                key = pact_resource_key(pool.pool_id, slot.level)
                expected_pact_keys[key] = slot.capacity

    next_resources = {
        key: counter
        for key, counter in current_resources.items()
        if not (key.startswith("pact_magic:") and ":slot:" in key)
    }
    for key, capacity in expected_pact_keys.items():
        next_resources[key] = reconcile_resource_counter(current_resources.get(key), capacity)

    return next_slots, next_resources
