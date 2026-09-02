from __future__ import annotations

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild
from app.domain.rules.abilities import (
    ABILITY_INDEX_TO_NAME,
    ABILITY_NAME_TO_INDEX,
    ABILITY_NAMES,
    ability_modifier,
    effective_ability_score,
    numeric_override,
)
from app.domain.rules.proficiency import proficiency_bonus, total_character_level


def saving_throw_modifier(build: CharacterBuild, ability: str) -> int:
    name = ABILITY_INDEX_TO_NAME.get(ability, ability)
    index = ABILITY_NAME_TO_INDEX.get(name)
    if name not in ABILITY_NAMES or index is None:
        raise ValueError(f"unknown ability: {ability}")
    result = ability_modifier(effective_ability_score(build, name))
    if f"srd5.1:ability:{index}" in build.saving_throw_proficiencies:
        result += proficiency_bonus(total_character_level(build))
    return result


def saving_throw_modifiers(build: CharacterBuild) -> dict[str, int]:
    return {name: saving_throw_modifier(build, name) for name in ABILITY_NAMES}


def skill_modifier(
    build: CharacterBuild,
    skill_ref: str,
    registry: ContentRegistry,
) -> int:
    skill = registry.get(skill_ref)
    ability_index = skill.data["ability_score"]["index"]
    ability_name = ABILITY_INDEX_TO_NAME[ability_index]
    result = ability_modifier(effective_ability_score(build, ability_name))
    if skill_ref in build.skill_choices:
        bonus = proficiency_bonus(total_character_level(build))
        result += bonus
        if skill_ref in build.skill_expertise_refs:
            result += bonus

    for override_key in (
        f"skill_modifier:{skill_ref}",
        f"skill_modifier:{skill.index}",
    ):
        override = numeric_override(build, override_key)
        if override is not None:
            return int(override)
    return result


def all_skill_modifiers(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> dict[str, int]:
    return {
        entry.index: skill_modifier(build, entry.key, registry)
        for entry in registry.list_kind("skill")
    }


def passive_perception(build: CharacterBuild, registry: ContentRegistry) -> int:
    return 10 + skill_modifier(build, "srd5.1:skill:perception", registry)
