"""Shared combatant walk-speed resolution (P5-B).

Characters resolve from their compiled build's ``walking_speed`` (feet);
Monsters from ``rules_snapshot["speed"]["walk"]`` (``"25 ft."``). The existing
condition (``speed_zero``) and exhaustion speed modifiers apply. Legacy data
without a recorded speed falls back to the 2014 standard 30 ft. rather than
failing the whole Combat — the same philosophy as the P5-A size fallback.
"""

from __future__ import annotations

import re
from typing import Iterable

from app.domain.combat.condition_modifiers import conditions_from_refs
from app.domain.combat.effect_resolver import CONDITION_SEMANTICS, exhaustion_semantics
from app.persistence.characters import CharacterRepository
from app.persistence.combat.lifecycle import StoredCombatEntry
from app.persistence.combat.repository import MonsterRepository

DEFAULT_WALK_SPEED_FEET = 30

_SPEED_NUMBER = re.compile(r"(\d+)")


def _parse_speed_feet(value: object) -> int | None:
    if isinstance(value, int):
        return value if value >= 0 else None
    if not isinstance(value, str):
        return None
    match = _SPEED_NUMBER.search(value)
    if match is None:
        return None
    return int(match.group(1))


def resolve_entry_walk_speed(
    entry: StoredCombatEntry,
    *,
    character_repository: CharacterRepository,
    monster_repository: MonsterRepository,
    conditions: Iterable[str],
    exhaustion_level: int,
) -> int:
    """Effective walk speed in feet for one Combat entry this turn."""
    # Imported here: app.domain.combat.lifecycle imports this module for the
    # Dash hook, so a top-level import would be circular.
    from app.domain.combat.lifecycle import CombatNotFoundError, CombatStateConflictError

    if entry.subject_kind == "character":
        if entry.character_id is None:
            raise CombatStateConflictError("Character CombatEntry has no Character identity")
        character = character_repository.load_character(entry.character_id)
        base = character.build.walking_speed
        base_feet = base if base is not None else DEFAULT_WALK_SPEED_FEET
    elif entry.subject_kind == "monster":
        if entry.monster_instance_id is None:
            raise CombatStateConflictError("Monster CombatEntry has no Monster identity")
        monster = monster_repository.get_instance(entry.monster_instance_id)
        if monster is None:
            raise CombatNotFoundError("Monster Instance was not found")
        speed = monster.rules_snapshot.get("speed")
        walk = speed.get("walk") if isinstance(speed, dict) else None
        parsed = _parse_speed_feet(walk)
        base_feet = parsed if parsed is not None else DEFAULT_WALK_SPEED_FEET
    else:
        raise CombatStateConflictError(f"unsupported CombatEntry kind: {entry.subject_kind}")

    for condition in conditions_from_refs(conditions, ignore_unknown=True):
        if CONDITION_SEMANTICS[condition].speed_zero:
            return 0
    exhaustion = exhaustion_semantics(exhaustion_level)
    if exhaustion.speed_zero:
        return 0
    return int(base_feet * exhaustion.speed_multiplier)


__all__ = ["DEFAULT_WALK_SPEED_FEET", "resolve_entry_walk_speed"]
