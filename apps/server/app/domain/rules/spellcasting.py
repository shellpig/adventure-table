from __future__ import annotations

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
    if spell is None or not spell.key.startswith("srd5.1:spell:"):
        return False
    class_index = class_ref.split(":", 2)[2]
    references = spell.data.get("classes")
    if not isinstance(references, list):
        return False
    return any(
        isinstance(reference, dict) and reference.get("index") == class_index
        for reference in references
    )


def max_spell_level_for_class(
    build: CharacterBuild,
    class_ref: str,
    registry: ContentRegistry,
) -> int:
    level = class_level(build, class_ref)
    if level <= 0:
        return 0
    class_index = class_ref.split(":", 2)[2]
    level_entry = registry.get_optional(f"srd5.1:level:{class_index}-{level}")
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
