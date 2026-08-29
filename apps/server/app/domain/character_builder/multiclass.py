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
ABILITY_NAME_TO_LABEL = {value: key.upper() for key, value in ABILITY_INDEX_TO_NAME.items()}


@dataclass(frozen=True)
class MulticlassPrerequisite:
    ability: str
    minimum_score: int


@dataclass(frozen=True)
class MulticlassPrerequisiteGroup:
    choose: int
    options: tuple[MulticlassPrerequisite, ...]


def _parse_prerequisite(item: object) -> MulticlassPrerequisite | None:
    if not isinstance(item, dict):
        return None
    ability_score = item.get("ability_score")
    minimum = item.get("minimum_score")
    if not isinstance(ability_score, dict) or not isinstance(minimum, int):
        return None
    ability_index = ability_score.get("index")
    if not isinstance(ability_index, str):
        return None
    ability = ABILITY_INDEX_TO_NAME.get(ability_index)
    if ability is None:
        return None
    return MulticlassPrerequisite(ability=ability, minimum_score=minimum)


def multiclass_prerequisites(class_entry: ContentEntry) -> tuple[MulticlassPrerequisite, ...]:
    raw = class_entry.data.get("multi_classing")
    if not isinstance(raw, dict):
        return ()
    prerequisites = raw.get("prerequisites")
    if not isinstance(prerequisites, list):
        return ()
    return tuple(
        prerequisite
        for item in prerequisites
        for prerequisite in [_parse_prerequisite(item)]
        if prerequisite is not None
    )


def multiclass_prerequisite_groups(
    class_entry: ContentEntry,
) -> tuple[MulticlassPrerequisiteGroup, ...]:
    raw = class_entry.data.get("multi_classing")
    if not isinstance(raw, dict):
        return ()
    raw_group = raw.get("prerequisite_options")
    if not isinstance(raw_group, dict):
        return ()

    choose = raw_group.get("choose")
    choose_count = choose if isinstance(choose, int) and choose > 0 else 1
    source = raw_group.get("from")
    if not isinstance(source, dict):
        return ()
    raw_options = source.get("options")
    if not isinstance(raw_options, list):
        return ()

    parsed: list[MulticlassPrerequisite] = []
    for option in raw_options:
        if not isinstance(option, dict):
            continue
        # 5e SRD represents Fighter's STR-or-DEX rule as score_prerequisite
        # options. Accept both the nested option object and a direct prerequisite
        # shape so imported/custom content can use either without class hardcodes.
        prerequisite = _parse_prerequisite(option)
        if prerequisite is None and option.get("option_type") == "score_prerequisite":
            prerequisite = _parse_prerequisite(option)
        if prerequisite is not None:
            parsed.append(prerequisite)
    if not parsed:
        return ()
    return (MulticlassPrerequisiteGroup(choose=choose_count, options=tuple(parsed)),)


def _label(prerequisite: MulticlassPrerequisite) -> str:
    return f"{ABILITY_NAME_TO_LABEL.get(prerequisite.ability, prerequisite.ability.upper())} {prerequisite.minimum_score}+"


def multiclass_failure_reason(
    class_entry: ContentEntry,
    effective_abilities: dict[str, int] | None,
) -> str | None:
    prerequisites = multiclass_prerequisites(class_entry)
    groups = multiclass_prerequisite_groups(class_entry)
    if not prerequisites and not groups:
        return None
    if effective_abilities is None:
        return "Complete ability scores before multiclassing."

    failures = [
        prerequisite
        for prerequisite in prerequisites
        if effective_abilities.get(prerequisite.ability, 0) < prerequisite.minimum_score
    ]
    failed_groups: list[MulticlassPrerequisiteGroup] = []
    for group in groups:
        satisfied = sum(
            effective_abilities.get(option.ability, 0) >= option.minimum_score
            for option in group.options
        )
        if satisfied < group.choose:
            failed_groups.append(group)

    if not failures and not failed_groups:
        return None

    details = [_label(failure) for failure in failures]
    for group in failed_groups:
        labels = [_label(option) for option in group.options]
        if group.choose == 1:
            details.append(" or ".join(labels))
        else:
            details.append(f"choose {group.choose}: " + ", ".join(labels))
    return f"Requires {'; '.join(details)} to multiclass."


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
