from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.domain.combat.projection import CombatantAudience

HOSTILE_TARGET_EXACT_KEYS = {
    "before_hp",
    "after_hp",
    "before_temp_hp",
    "after_temp_hp",
    "current_hp",
    "temp_hp",
    "max_hp",
    "target_current_hp",
    "target_temp_hp",
    "target_ac",
    "resources",
    "hidden_conditions",
    "dm_notes",
    "save_modifier",
    # Damage bookkeeping that lets a Player back out resistances / temp HP.
    "affinities",
    "adjusted_by_type",
    "hp_lost",
    "temp_hp_absorbed",
}

HOSTILE_CASTER_KEYS = {
    "save_dc",
    "attack_modifier",
    "resource_cost",
    "slot_level",
    "spell_slot",
    "resources",
    "slots_remaining",
}


def _redact_attack_structure(res: dict[str, Any]) -> None:
    attack = res.get("attack")
    if isinstance(attack, dict):
        attack.pop("target_ac", None)
    damage = res.get("damage")
    if isinstance(damage, dict):
        damage.pop("before", None)
        damage.pop("after", None)
        damage.pop("before_hp", None)
        damage.pop("after_hp", None)


# Payload keys that carry Combat entry ids (or Monster instance ids), singly or as lists.
_ID_KEYS = {
    "entry_id",
    "target_entry_id",
    "target_combat_entry_id",
    "current_turn_entry_id",
    "acting_entry_id",
    "monster_instance_id",
    "subject_monster_instance_id",
    "target_monster_instance_id",
}
_ID_LIST_KEYS = {
    "entry_ids",
    "ordered_entry_ids",
    "grouped_entry_ids",
}


def _redact_hidden_entries(data: dict[str, Any], hidden_ids: frozenset[str]) -> None:
    """Strip hidden Monster entry/instance ids and their names from a Player-facing payload."""

    def is_hidden(value: object) -> bool:
        return isinstance(value, str) and value in hidden_ids

    redacted = False
    for key in _ID_KEYS:
        if is_hidden(data.get(key)):
            data[key] = None
            redacted = True
    for key in _ID_LIST_KEYS:
        values = data.get(key)
        if isinstance(values, list):
            filtered = [value for value in values if not is_hidden(value)]
            if len(filtered) != len(values):
                redacted = True
            data[key] = filtered
    if redacted:
        # A payload that names its entry (combat.entry_added et al.) must not
        # name a hidden Monster; the id above is already nulled.
        data.pop("display_name", None)
        data.pop("name", None)
    # Per-target lists: element-wise projection
    for list_key in ("outcomes", "targets"):
        items = data.get(list_key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    _redact_hidden_entries(item, hidden_ids)


def project_combat_event_payload(
    kind: str,
    payload: dict[str, Any],
    *,
    audience: CombatantAudience,
    hidden_entry_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Project combat event payloads and mutation responses for caller visibility.

    DM audience receives the complete payload untouched.
    Player audience has exact enemy HP, AC, saving throw modifiers, and caster DCs
    redacted while preserving damage amounts, hit/crit, outcomes, and injury levels.
    Hidden Monster entry ids/names (P5-A B6) are stripped for Players whenever the
    caller supplies them via hidden_entry_ids.
    Non-combat event kinds are never modified.
    """
    if audience == "dm":
        return payload
    if not kind.startswith("combat.") and kind not in {"roll.resolved", "roll.requested"}:
        return payload

    data = deepcopy(payload)

    if hidden_entry_ids:
        _redact_hidden_entries(data, hidden_entry_ids)

    if kind == "combat.door_state_changed" and data.pop("hidden_door", False):
        # Hidden-origin doors never expose their id to Players (their board
        # view projects door_id=None); the state change itself stays visible.
        data.pop("door_id", None)
    if kind == "combat.movement_interrupted":
        # An interrupted movement tells Players only that the path was
        # obstructed. The step index and blocker identity stay DM-only; the
        # blocker id is deliberately outside _ID_KEYS, so the allowlist below
        # is the only thing that keeps it out of Player payloads.
        return {
            "combat_id": data.get("combat_id"),
            "entry_id": data.get("entry_id"),
            "reason": data.get("reason"),
        }
    if kind == "combat.position_corrected":
        # The DM's correction reason is audit-only; Players see the new position.
        data.pop("reason", None)
    target_is_hostile = bool(data.get("target_is_hostile", False))
    caster_is_hostile = bool(data.get("caster_is_hostile", False))

    if target_is_hostile:
        for key in HOSTILE_TARGET_EXACT_KEYS:
            data.pop(key, None)

        if isinstance(data.get("before"), dict):
            data.pop("before", None)
        if isinstance(data.get("after"), dict):
            data.pop("after", None)

        # In saving throws or concentration checks, formula and modifiers leak monster stats
        data.pop("modifier", None)
        data.pop("formula", None)

        if isinstance(data.get("attack_resolution"), dict):
            _redact_attack_structure(data["attack_resolution"])
        if isinstance(data.get("resolution_result"), dict):
            _redact_attack_structure(data["resolution_result"])

    # If the payload itself is an attack resolution / result dict
    if "attack" in data or "damage" in data:
        if target_is_hostile or data.get("target_is_hostile") is None:
            _redact_attack_structure(data)

    if caster_is_hostile:
        for key in HOSTILE_CASTER_KEYS:
            data.pop(key, None)
        roll = data.get("roll")
        if isinstance(roll, dict):
            for k in ("save_dc", "attack_modifier", "modifier", "formula", "base_modifier"):
                roll.pop(k, None)
        spell = data.get("spell")
        if isinstance(spell, dict):
            for k in ("slot_level", "resource_cost", "resources"):
                spell.pop(k, None)

    # Per-target lists: element-wise projection
    outcomes = data.get("outcomes")
    if isinstance(outcomes, list):
        for item in outcomes:
            if isinstance(item, dict) and item.get("target_is_hostile") is True:
                for k in ("current_hp", "temp_hp", "before_hp", "after_hp", "max_hp"):
                    item.pop(k, None)

    rolls = data.get("rolls")
    if isinstance(rolls, list):
        for item in rolls:
            if isinstance(item, dict) and item.get("target_is_hostile") is True:
                item.pop("modifier", None)

    checks = data.get("concentration_checks")
    if isinstance(checks, list):
        for item in checks:
            if isinstance(item, dict) and item.get("target_is_hostile") is True:
                item.pop("dc", None)

    return data


__all__ = [
    "HOSTILE_CASTER_KEYS",
    "HOSTILE_TARGET_EXACT_KEYS",
    "project_combat_event_payload",
]
