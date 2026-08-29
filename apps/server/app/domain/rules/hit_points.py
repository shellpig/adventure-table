from __future__ import annotations

from app.domain.character.schemas import CharacterBuild
from app.domain.rules.abilities import ability_modifier, effective_ability_score, numeric_override
from app.domain.rules.proficiency import total_character_level


def calculate_max_hp(build: CharacterBuild) -> int:
    constitution_modifier = ability_modifier(
        effective_ability_score(build, "constitution")
    )
    result = sum(build.hp_progression) + constitution_modifier * total_character_level(build)
    override = numeric_override(build, "max_hp")
    if override is not None:
        return int(override)
    return max(1, result)
