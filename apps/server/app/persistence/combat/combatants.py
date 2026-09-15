from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.domain.combat import CombatantState
from app.persistence.combat.repository import StoredMonsterInstance


@dataclass(frozen=True)
class MonsterRevealState:
    armor_class: bool = False
    description: bool = False
    position_note: bool = False


def _partition_visible_names(
    items: list[dict[str, Any] | str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    public: list[str] = []
    hidden: list[str] = []
    for item in items:
        if isinstance(item, str):
            public.append(item)
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        if item.get("visibility") == "public":
            public.append(name)
        else:
            hidden.append(name)
    return tuple(public), tuple(hidden)


def monster_instance_to_combatant(
    instance: StoredMonsterInstance,
    *,
    reveals: MonsterRevealState | None = None,
) -> CombatantState:
    rules = instance.rules_snapshot
    public_conditions, hidden_conditions = _partition_visible_names(instance.conditions)
    public_effects, hidden_effects = _partition_visible_names(instance.effects)
    reveal_state = reveals or MonsterRevealState()

    return CombatantState(
        id=instance.id,
        kind="monster",
        name=instance.name,
        description=rules.get("description") or rules.get("desc"),
        armor_class=rules.get("armor_class"),
        max_hp=rules["max_hp"],
        current_hp=instance.current_hp,
        temp_hp=instance.temp_hp,
        speed=deepcopy(rules.get("speed", {})),
        initiative=instance.initiative,
        combat_status=instance.combat_status,
        visibility=instance.visibility,
        public_conditions=public_conditions,
        hidden_conditions=hidden_conditions,
        public_effects=public_effects,
        hidden_effects=hidden_effects,
        traits=tuple(deepcopy(rules.get("traits", rules.get("special_abilities", [])))),
        actions=tuple(deepcopy(rules.get("actions", []))),
        bonus_actions=tuple(deepcopy(rules.get("bonus_actions", []))),
        reactions=tuple(deepcopy(rules.get("reactions", []))),
        legendary_actions=tuple(deepcopy(rules.get("legendary_actions", []))),
        resources=deepcopy(instance.resources),
        reaction_available=instance.reaction_available,
        position_note=instance.position_note,
        armor_class_revealed=reveal_state.armor_class,
        description_revealed=reveal_state.description,
        position_note_revealed=reveal_state.position_note,
    )


__all__ = ["MonsterRevealState", "monster_instance_to_combatant"]
