from __future__ import annotations

from app.domain.character.schemas import CharacterBuild

ABILITY_NAMES = (
    "strength",
    "dexterity",
    "constitution",
    "intelligence",
    "wisdom",
    "charisma",
)
ABILITY_INDEX_TO_NAME = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}
ABILITY_NAME_TO_INDEX = {value: key for key, value in ABILITY_INDEX_TO_NAME.items()}


def ability_modifier(score: int) -> int:
    return (score - 10) // 2


def numeric_override(build: CharacterBuild, key: str) -> float | None:
    for override in build.numeric_overrides:
        if override.key == key:
            return override.value
    return None


def normalize_ability_name(ability: str) -> str:
    if ability.startswith("srd5.1:ability:"):
        ability = ability.rsplit(":", 1)[-1]
    ability = ABILITY_INDEX_TO_NAME.get(ability, ability)
    if ability not in ABILITY_NAMES:
        raise ValueError(f"unknown ability: {ability}")
    return ability


def effective_ability_score(build: CharacterBuild, ability: str) -> int:
    name = normalize_ability_name(ability)
    value = numeric_override(build, f"ability:{name}")
    if value is None:
        return getattr(build.ability_scores, name)
    return int(value)


def effective_ability_scores(build: CharacterBuild) -> dict[str, int]:
    return {name: effective_ability_score(build, name) for name in ABILITY_NAMES}
