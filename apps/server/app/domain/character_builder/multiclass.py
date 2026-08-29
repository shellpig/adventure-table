from __future__ import annotations

from dataclasses import dataclass

from app.content.schemas import ContentEntry


ABILITY_INDEX_TO_NAME = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}


@dataclass(frozen=True)
class MulticlassPrerequisite:
    ability: str
    minimum_score: int


def multiclass_prerequisites(class_entry: ContentEntry) -> tuple[MulticlassPrerequisite, ...]:
    raw = class_entry.data.get("multi_classing")
    if not isinstance(raw, dict):
        return ()
    prerequisites = raw.get("prerequisites")
    if not isinstance(prerequisites, list):
        return ()

    result: list[MulticlassPrerequisite] = []
    for item in prerequisites:
        if not isinstance(item, dict):
            continue
        ability_score = item.get("ability_score")
        minimum = item.get("minimum_score")
        if not isinstance(ability_score, dict) or not isinstance(minimum, int):
            continue
        ability_index = ability_score.get("index")
        if not isinstance(ability_index, str):
            continue
        ability = ABILITY_INDEX_TO_NAME.get(ability_index)
        if ability is not None:
            result.append(MulticlassPrerequisite(ability=ability, minimum_score=minimum))
    return tuple(result)


def multiclass_failure_reason(
    class_entry: ContentEntry,
    effective_abilities: dict[str, int] | None,
) -> str | None:
    prerequisites = multiclass_prerequisites(class_entry)
    if not prerequisites:
        return None
    if effective_abilities is None:
        return "Complete ability scores before multiclassing."

    failures = [
        prerequisite
        for prerequisite in prerequisites
        if effective_abilities.get(prerequisite.ability, 0) < prerequisite.minimum_score
    ]
    if not failures:
        return None
    detail = ", ".join(
        f"{failure.ability.upper()} {failure.minimum_score}+" for failure in failures
    )
    return f"Requires {detail} to multiclass."


def multiclass_option_failure_reason(
    candidate: ContentEntry,
    acquired_classes: tuple[ContentEntry, ...],
    effective_abilities: dict[str, int] | None,
) -> str | None:
    if not acquired_classes or any(entry.key == candidate.key for entry in acquired_classes):
        return None

    # 2014 rules require meeting the prerequisites for both the class being left
    # and the class being entered. Validate every class already represented in the
    # ordered progression so a stale/edited rail cannot bypass that requirement.
    seen: set[str] = set()
    for entry in (*acquired_classes, candidate):
        if entry.key in seen:
            continue
        seen.add(entry.key)
        reason = multiclass_failure_reason(entry, effective_abilities)
        if reason is not None:
            return f"{entry.name}: {reason}"
    return None


def multiclass_proficiencies(class_entry: ContentEntry) -> tuple[dict[str, object], ...]:
    raw = class_entry.data.get("multi_classing")
    if not isinstance(raw, dict):
        return ()
    proficiencies = raw.get("proficiencies")
    if not isinstance(proficiencies, list):
        return ()
    return tuple(item for item in proficiencies if isinstance(item, dict))


def multiclass_proficiency_choices(class_entry: ContentEntry) -> tuple[dict[str, object], ...]:
    raw = class_entry.data.get("multi_classing")
    if not isinstance(raw, dict):
        return ()
    choices = raw.get("proficiency_choices")
    if not isinstance(choices, list):
        return ()
    return tuple(item for item in choices if isinstance(item, dict))
