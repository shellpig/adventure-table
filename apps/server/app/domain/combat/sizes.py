"""Shared combatant size resolution (P5-A).

Extracted from ``app/domain/combat/special_attacks.py`` so Grapple/Shove and
tactical placement share one implementation. Behavior is unchanged: Characters
resolve size from their race content, Monsters from ``rules_snapshot["size"]``.
"""

from __future__ import annotations

from app.content.registry import ContentRegistry
from app.domain.combat.lifecycle import CombatNotFoundError, CombatStateConflictError
from app.domain.combat.resolution import SizeCategory
from app.persistence.characters import CharacterRepository
from app.persistence.combat.lifecycle import StoredCombatEntry
from app.persistence.combat.repository import MonsterRepository


def parse_size(value: object) -> SizeCategory:
    if not isinstance(value, str) or not value.strip():
        raise CombatStateConflictError("Combatant size is required for Grapple/Shove")
    key = value.strip().upper().replace(" ", "_")
    try:
        return SizeCategory[key]
    except KeyError as exc:
        raise CombatStateConflictError(f"Unsupported combatant size: {value}") from exc


def resolve_entry_size(
    entry: StoredCombatEntry,
    *,
    character_repository: CharacterRepository,
    monster_repository: MonsterRepository,
    registry: ContentRegistry,
) -> SizeCategory:
    if entry.subject_kind == "character":
        if entry.character_id is None:
            raise CombatStateConflictError("Character CombatEntry has no Character identity")
        character = character_repository.load_character(entry.character_id)
        race = registry.get_optional(character.build.race_ref)
        if race is None:
            raise CombatStateConflictError("Character race content is unavailable for size resolution")
        return parse_size(race.data.get("size"))
    if entry.subject_kind == "monster":
        if entry.monster_instance_id is None:
            raise CombatStateConflictError("Monster CombatEntry has no Monster identity")
        monster = monster_repository.get_instance(entry.monster_instance_id)
        if monster is None:
            raise CombatNotFoundError("Monster Instance was not found")
        # Quick enemies and legacy instances may not record a size; placement
        # treats them as Medium rather than failing the whole Combat.
        return parse_size(monster.rules_snapshot.get("size") or "medium")
    raise CombatStateConflictError(f"unsupported CombatEntry kind: {entry.subject_kind}")


__all__ = ["parse_size", "resolve_entry_size"]
