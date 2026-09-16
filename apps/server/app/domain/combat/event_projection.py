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


def project_combat_event_payload(
    kind: str,
    payload: dict[str, Any],
    *,
    audience: CombatantAudience,
) -> dict[str, Any]:
    """Project combat event payloads and mutation responses for caller visibility.

    DM audience receives the complete payload untouched.
    Player audience has exact enemy HP, AC, saving throw modifiers, and caster DCs
    redacted while preserving damage amounts, hit/crit, outcomes, and injury levels.
    Non-combat event kinds are never modified.
    """
    if audience == "dm":
        return payload
    if not kind.startswith("combat.") and kind not in {"roll.resolved", "roll.requested"}:
        return payload

    data = deepcopy(payload)

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
