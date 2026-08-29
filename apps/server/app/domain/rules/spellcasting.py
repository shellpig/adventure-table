from __future__ import annotations

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild
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
