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


def resolve_skill_ref(registry: ContentRegistry, ref: str) -> str:
    """Normalise a skill reference to its stable content key.

    The engine stores skills as stable keys (e.g. ``srd5.1:skill:investigation``)
    so proficiency and expertise can match ``build.skill_choices``. Callers,
    including AI DMs, may pass a plain index like ``investigation`` or
    ``Investigation``; resolve it here rather than forcing the long key.
    """

    candidate = ref.strip()
    if not candidate:
        raise ValueError("skill reference is empty")
    if registry.get_optional(candidate) is not None:
        return candidate
    index = candidate.lower().replace(" ", "-").replace("_", "-")
    matches = [
        entry.key
        for entry in registry.list_kind("skill")
        if entry.index == index
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"unknown skill: {ref}")
    raise ValueError(f"ambiguous skill across content packs: {ref}")


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


def all_skill_proficiencies(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> tuple[str, ...]:
    return tuple(
        entry.index
        for entry in registry.list_kind("skill")
        if entry.key in build.skill_choices
    )


def _static_passive_bonus(build: CharacterBuild, target: str) -> int:
    level = total_character_level(build)
    return sum(
        modifier.value * (level if modifier.per_level else 1)
        for modifier in build.static_derived_modifiers
        if modifier.target == target
    )


def _passive_score(
    build: CharacterBuild,
    registry: ContentRegistry,
    *,
    skill_ref: str,
    target: str,
) -> int:
    result = 10 + skill_modifier(build, skill_ref, registry) + _static_passive_bonus(build, target)
    override = numeric_override(build, target)
    if override is not None:
        return int(override)
    return result


def passive_perception(build: CharacterBuild, registry: ContentRegistry) -> int:
    return _passive_score(
        build,
        registry,
        skill_ref="srd5.1:skill:perception",
        target="passive_perception",
    )


def passive_investigation(build: CharacterBuild, registry: ContentRegistry) -> int:
    return _passive_score(
        build,
        registry,
        skill_ref="srd5.1:skill:investigation",
        target="passive_investigation",
    )
