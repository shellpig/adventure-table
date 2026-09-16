from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

CombatantKind = Literal["character", "monster"]
CombatantAudience = Literal["dm", "player"]


@dataclass(frozen=True)
class CombatantState:
    id: UUID
    kind: CombatantKind
    name: str
    current_hp: int
    max_hp: int
    temp_hp: int = 0
    armor_class: int | None = None
    speed: dict[str, Any] = field(default_factory=dict)
    initiative: int | None = None
    combat_status: str = "active"
    visibility: Literal["public", "hidden"] = "public"
    description: str | None = None
    public_conditions: tuple[str, ...] = ()
    hidden_conditions: tuple[str, ...] = ()
    public_effects: tuple[str, ...] = ()
    hidden_effects: tuple[str, ...] = ()
    traits: tuple[dict[str, Any], ...] = ()
    actions: tuple[dict[str, Any], ...] = ()
    bonus_actions: tuple[dict[str, Any], ...] = ()
    reactions: tuple[dict[str, Any], ...] = ()
    legendary_actions: tuple[dict[str, Any], ...] = ()
    resources: dict[str, Any] = field(default_factory=dict)
    reaction_available: bool | None = None
    position_note: str | None = None
    dm_notes: str | None = None
    armor_class_revealed: bool = False
    description_revealed: bool = False
    position_note_revealed: bool = False
    concentration: dict[str, Any] | None = None
    death_saves: dict[str, Any] | None = None
    exhaustion_level: int = 0

    def __post_init__(self) -> None:
        if self.current_hp < 0 or self.max_hp < 0 or self.temp_hp < 0:
            raise ValueError("combatant HP values must not be negative")
        if self.armor_class is not None and self.armor_class < 0:
            raise ValueError("combatant armor_class must not be negative")
        if self.exhaustion_level < 0:
            raise ValueError("combatant exhaustion_level must not be negative")


def calculate_injury_level(
    current_hp: int,
    max_hp: int,
    combat_status: str = "active",
) -> Literal["down", "critical", "wounded", "healthy"]:
    if current_hp <= 0 or combat_status in {"down", "dead"}:
        return "down"
    if max_hp <= 0:
        return "critical"
    ratio = current_hp / max_hp
    if ratio <= 0.25:
        return "critical"
    if ratio <= 0.5:
        return "wounded"
    return "healthy"


def injury_level(state: CombatantState) -> Literal["down", "critical", "wounded", "healthy"]:
    return calculate_injury_level(state.current_hp, state.max_hp, state.combat_status)



def _full_projection(state: CombatantState) -> dict[str, Any]:
    return {
        "id": str(state.id),
        "kind": state.kind,
        "name": state.name,
        "description": state.description,
        "armor_class": state.armor_class,
        "max_hp": state.max_hp,
        "current_hp": state.current_hp,
        "temp_hp": state.temp_hp,
        "speed": deepcopy(state.speed),
        "initiative": state.initiative,
        "combat_status": state.combat_status,
        "visibility": state.visibility,
        "conditions": list(state.public_conditions + state.hidden_conditions),
        "effects": list(state.public_effects + state.hidden_effects),
        "traits": deepcopy(list(state.traits)),
        "actions": deepcopy(list(state.actions)),
        "bonus_actions": deepcopy(list(state.bonus_actions)),
        "reactions": deepcopy(list(state.reactions)),
        "legendary_actions": deepcopy(list(state.legendary_actions)),
        "resources": deepcopy(state.resources),
        "reaction_available": state.reaction_available,
        "position_note": state.position_note,
        "dm_notes": state.dm_notes,
        "concentration": deepcopy(state.concentration) if state.concentration is not None else None,
        "death_saves": deepcopy(state.death_saves) if state.death_saves is not None else None,
        "exhaustion_level": state.exhaustion_level,
    }


def project_combatant(
    state: CombatantState,
    *,
    audience: CombatantAudience,
    enemy: bool,
) -> dict[str, Any] | None:
    """Project canonical combat state without relying on caller-side redaction.

    DM receives the complete combatant state. Player projections for friendly
    combatants keep exact mechanical state but still omit DM-only notes. Enemy
    projections use a fixed allowlist so newly-added private fields cannot leak
    unless this function explicitly opts them in.
    """

    if audience == "dm":
        return _full_projection(state)
    if audience != "player":
        raise ValueError(f"unsupported combatant audience: {audience}")

    if not enemy:
        projected = _full_projection(state)
        projected.pop("dm_notes", None)
        return projected

    if state.visibility == "hidden":
        return None

    projected: dict[str, Any] = {
        "id": str(state.id),
        "kind": state.kind,
        "name": state.name,
        "combat_status": state.combat_status,
        "injury_level": injury_level(state),
        "conditions": list(state.public_conditions),
        "effects": list(state.public_effects),
    }
    if state.initiative is not None:
        projected["initiative"] = state.initiative
    if state.armor_class_revealed and state.armor_class is not None:
        projected["armor_class"] = state.armor_class
    if state.description_revealed and state.description:
        projected["description"] = state.description
    if state.position_note_revealed and state.position_note:
        projected["position_note"] = state.position_note
    return projected


__all__ = [
    "CombatantAudience",
    "CombatantKind",
    "CombatantState",
    "calculate_injury_level",
    "injury_level",
    "project_combatant",
]
