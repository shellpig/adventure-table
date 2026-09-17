from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterState, PersistedCharacter
from app.domain.combat import CombatantState
from app.domain.rules.armor_class import calculate_armor_class
from app.domain.rules.hit_points import calculate_max_hp
from app.domain.rules.m01m_ancestry import effective_movement
from app.persistence.combat.lifecycle import StoredCombatEntry
from app.persistence.combat.repository import StoredMonsterInstance


@dataclass(frozen=True)
class MonsterRevealState:
    armor_class: bool = False
    description: bool = False
    position_note: bool = False

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> MonsterRevealState:
        if not mapping:
            return cls()
        kwargs: dict[str, bool] = {}
        for key in ("armor_class", "description", "position_note"):
            if key in mapping:
                val = mapping[key]
                if isinstance(val, bool):
                    kwargs[key] = val
        return cls(**kwargs)

    def to_mapping(self) -> dict[str, bool]:
        return {
            "armor_class": self.armor_class,
            "description": self.description,
            "position_note": self.position_note,
        }


def _partition_visible_names(
    items: list[dict[str, Any] | str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    public: list[str] = []
    hidden: list[str] = []
    for item in items:
        if isinstance(item, str):
            public.append(item)
            continue
        name = str(item.get("name") or item.get("condition_ref") or item.get("tag") or "").strip()
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
    entry: StoredCombatEntry | None = None,
) -> CombatantState:
    rules = instance.rules_snapshot
    public_conditions, hidden_conditions = _partition_visible_names(instance.conditions)
    public_effects, hidden_effects = _partition_visible_names(instance.effects)
    reveal_state = (
        reveals
        if reveals is not None
        else MonsterRevealState.from_mapping(instance.reveal_state)
    )
    # P4-B moved initiative and reaction economy onto combat_entries; the
    # instance columns only remain for pre-combat / template-level state.
    initiative = entry.initiative_total if entry is not None else instance.initiative
    reaction_available = entry.reaction_available if entry is not None else instance.reaction_available

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
        initiative=initiative,
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
        reaction_available=reaction_available,
        position_note=instance.position_note,
        armor_class_revealed=reveal_state.armor_class,
        description_revealed=reveal_state.description,
        position_note_revealed=reveal_state.position_note,
        concentration=deepcopy(instance.concentration) if instance.concentration is not None else None,
    )


def character_to_combatant(
    character: PersistedCharacter,
    *,
    entry: StoredCombatEntry,
    registry: ContentRegistry,
) -> CombatantState:
    """Project a Character CombatEntry onto the same shape as a Monster combatant.

    Character conditions and effects are never hidden, so they all land in the
    public tuples; conditions are exposed by ``condition_ref`` (設計 §8.5).
    """

    state: CharacterState = character.state
    movement = effective_movement(character.build, state, registry)
    speed: dict[str, Any] = {"walk": movement.walk}
    for mode in ("swim", "climb", "fly"):
        value = getattr(movement, mode)
        if value is not None:
            speed[mode] = value
    return CombatantState(
        id=character.id,
        kind="character",
        name=entry.display_name,
        current_hp=state.current_hp,
        max_hp=calculate_max_hp(character.build),
        temp_hp=state.temporary_hp,
        armor_class=calculate_armor_class(character.build, state, registry),
        speed=speed,
        initiative=entry.initiative_total,
        combat_status="down" if state.current_hp <= 0 else "active",
        visibility="public",
        public_conditions=tuple(str(item.condition_ref) for item in state.conditions),
        public_effects=tuple(item.tag for item in state.temporary_effects),
        reaction_available=entry.reaction_available,
        concentration=(
            state.concentration.model_dump(mode="json") if state.concentration is not None else None
        ),
        death_saves=state.death_saves.model_dump(mode="json"),
        exhaustion_level=state.exhaustion_level,
    )


__all__ = ["MonsterRevealState", "character_to_combatant", "monster_instance_to_combatant"]
