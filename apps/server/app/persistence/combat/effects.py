"""P4-D linked-effect bookkeeping shared by spell and concentration writers.

A concentration spell can attach effects to creatures other than the caster.
The caster's ``CharacterState.concentration.effect_ids`` is the only pointer to
those effects, so when concentration ends the effects (and any condition they
applied) must be removed from every combatant of the same Combat inside the
same transaction. Callers already hold the Combat row lock.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select, update

from app.domain.character.schemas import CharacterState, PersistentTemporaryEffect
from app.domain.combat.effect_resolver import Condition, condition_to_state
from app.persistence.characters import character_states
from app.persistence.combat.tables import combat_entries, monster_instances


class LinkedEffectStateConflictError(RuntimeError):
    pass


def condition_ref_for_effect(effect: PersistentTemporaryEffect) -> str | None:
    """Stable condition key when a persisted effect's tag is a 2014 condition."""

    try:
        return condition_to_state(Condition(effect.tag)).condition_ref
    except ValueError:
        return None


def monster_effect_entry(effect: PersistentTemporaryEffect) -> dict[str, Any]:
    """``monster_instances.effects`` item carrying the same durable effect record."""

    return {
        "name": effect.tag,
        "visibility": "public",
        "effect_id": effect.effect_id,
        "effect": effect.model_dump(mode="json"),
    }


def strip_effects_from_state_payload(
    payload: dict[str, Any], effect_ids: set[str]
) -> bool:
    """Drop linked temporary effects and their conditions from a state payload."""

    effects = list(payload.get("temporary_effects", []))
    conditions = list(payload.get("conditions", []))
    kept_effects = [item for item in effects if item.get("effect_id") not in effect_ids]
    kept_conditions = [item for item in conditions if item.get("effect_id") not in effect_ids]
    changed = len(kept_effects) != len(effects) or len(kept_conditions) != len(conditions)
    payload["temporary_effects"] = kept_effects
    payload["conditions"] = kept_conditions
    return changed


def _strip_monster_items(items: list[Any], effect_ids: set[str]) -> tuple[list[Any], bool]:
    kept = [
        item
        for item in items
        if not (isinstance(item, dict) and item.get("effect_id") in effect_ids)
    ]
    return kept, len(kept) != len(items)


def strip_linked_effects(
    connection,
    *,
    combat_id: UUID,
    effect_ids: Iterable[str],
    now: datetime,
    skip_character_ids: Iterable[UUID] = (),
) -> list[dict[str, Any]]:
    """Remove ``effect_ids`` from every other combatant in ``combat_id``.

    Characters whose state the caller is already rewriting in this transaction
    must be listed in ``skip_character_ids`` — they are handled by the caller
    and must not be double-updated under the revision CAS.
    """

    ids = {str(value) for value in effect_ids}
    if not ids:
        return []
    skip = set(skip_character_ids)
    removed: list[dict[str, Any]] = []
    entries = connection.execute(
        select(combat_entries).where(
            combat_entries.c.combat_id == combat_id,
            combat_entries.c.status == "active",
        )
    ).mappings().all()
    for entry in entries:
        if entry["subject_kind"] == "character":
            character_id = entry["character_id"]
            if character_id is None or character_id in skip:
                continue
            row = connection.execute(
                select(character_states.c.state_payload, character_states.c.state_revision)
                .where(character_states.c.character_id == character_id)
                .with_for_update()
            ).mappings().one_or_none()
            if row is None:
                continue
            payload = CharacterState.model_validate(row["state_payload"]).model_dump(mode="json")
            if not strip_effects_from_state_payload(payload, ids):
                continue
            revision = int(row["state_revision"])
            result = connection.execute(
                update(character_states)
                .where(
                    character_states.c.character_id == character_id,
                    character_states.c.state_revision == revision,
                )
                .values(
                    state_payload=CharacterState.model_validate(payload).model_dump(mode="json"),
                    state_revision=revision + 1,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise LinkedEffectStateConflictError(
                    "Character State changed while removing linked spell effects"
                )
            removed.append({"entry_id": str(entry["id"]), "character_id": str(character_id)})
        elif entry["subject_kind"] == "monster":
            monster_id = entry["monster_instance_id"]
            if monster_id is None:
                continue
            monster = connection.execute(
                select(monster_instances.c.conditions, monster_instances.c.effects)
                .where(monster_instances.c.id == monster_id)
                .with_for_update()
            ).mappings().one_or_none()
            if monster is None:
                continue
            conditions, conditions_changed = _strip_monster_items(list(monster["conditions"] or []), ids)
            effects, effects_changed = _strip_monster_items(list(monster["effects"] or []), ids)
            if not (conditions_changed or effects_changed):
                continue
            connection.execute(
                update(monster_instances)
                .where(monster_instances.c.id == monster_id)
                .values(conditions=conditions, effects=effects, updated_at=now)
            )
            removed.append({"entry_id": str(entry["id"]), "monster_instance_id": str(monster_id)})
    return removed


__all__ = [
    "LinkedEffectStateConflictError",
    "condition_ref_for_effect",
    "monster_effect_entry",
    "strip_effects_from_state_payload",
    "strip_linked_effects",
]
