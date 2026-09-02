from __future__ import annotations

from app.domain.character.schemas import CharacterBuild
from app.domain.rules.abilities import ability_modifier, effective_ability_score, numeric_override
from app.domain.rules.proficiency import total_character_level


def _static_max_hp_bonus(build: CharacterBuild) -> int:
    level = total_character_level(build)
    return sum(
        modifier.value * (level if modifier.per_level else 1)
        for modifier in build.static_derived_modifiers
        if modifier.target == "max_hp"
    )


def calculate_max_hp(build: CharacterBuild) -> int:
    constitution_modifier = ability_modifier(
        effective_ability_score(build, "constitution")
    )
    result = (
        sum(build.hp_progression)
        + constitution_modifier * total_character_level(build)
        + _static_max_hp_bonus(build)
    )
    # Numeric override is intentionally last: base rules -> static derived feat
    # modifiers (for example Tough) -> explicit user override.
    override = numeric_override(build, "max_hp")
    if override is not None:
        return int(override)
    return max(1, result)
