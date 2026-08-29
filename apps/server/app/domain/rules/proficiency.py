from __future__ import annotations

from app.domain.character.schemas import CharacterBuild


def total_character_level(build: CharacterBuild) -> int:
    return len(build.class_progression)


def class_level(build: CharacterBuild, class_ref: str) -> int:
    return sum(1 for ref in build.class_progression if ref == class_ref)


def proficiency_bonus(character_level: int) -> int:
    if character_level < 1 or character_level > 20:
        raise ValueError("character level must be between 1 and 20")
    return 2 + (character_level - 1) // 4
