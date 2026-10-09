from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

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
    # P5-D D1: a hidden Monster casting an AoE must not leak its entry id in
    # the public proposal event.
    "caster_entry_id",
    # M07-D D1 (F01): reaction / save / movement payload identity keys.
    "source_entry_id",
    "actor_entry_id",
    "mover_entry_id",
    "monster_instance_id",
    "subject_monster_instance_id",
    "target_monster_instance_id",
}
_ID_LIST_KEYS = {
    "entry_ids",
    "ordered_entry_ids",
    "grouped_entry_ids",
    # P5-D D1: AoE proposal/confirm/candidate identity sets.
    "proposed_target_ids",
    "confirmed_target_ids",
    "candidate_entry_ids",
    # M07-D D1 (F01): initiative groups, save targets, reaction eligibility.
    "combat_entry_ids",
    "target_entry_ids",
    "eligible_entry_ids",
}

# Combat lifecycle events that are *about* one Monster combatant: when that
# combatant is hidden there is no safe redacted form (the kind alone would
# confirm a hidden Monster exists), so Players do not receive them at all.
# The DM view is untouched.
_HIDDEN_SUBJECT_SUPPRESSED_KINDS = frozenset({
    "combat.monster_instance_updated",
    "combat.entry_added",
    "combat.entry_removed",
    "combat.entry_withdrawn",
    "combat.monster_outcome_set",
})


def _is_hidden_id(value: object, hidden_ids: frozenset[str]) -> bool:
    return isinstance(value, (str, UUID)) and str(value) in hidden_ids


def _filter_id_list(values: list, hidden_ids: frozenset[str]) -> tuple[list, bool]:
    """Filter hidden ids out of one id list.

    Nested lists (initiative ``combat_entry_ids`` groups) are filtered
    element-wise; groups left empty are dropped so neither the hidden ids
    nor their count survive. Returns the new list and whether it changed.
    """
    changed = False
    filtered: list = []
    for value in values:
        if isinstance(value, list):
            inner = [item for item in value if not _is_hidden_id(item, hidden_ids)]
            if len(inner) != len(value):
                changed = True
            if inner:
                filtered.append(inner)
            else:
                # A group consisting only of hidden combatants vanishes
                # entirely; keeping an empty group would leak the group count.
                changed = True
        elif _is_hidden_id(value, hidden_ids):
            changed = True
        else:
            filtered.append(value)
    return filtered, changed


def _redact_hidden_entries(data: dict[str, Any], hidden_ids: frozenset[str]) -> bool:
    """Strip hidden Monster entry/instance ids and their names from a Player-facing payload.

    Walks every nested dict/list of the payload (not just ``outcomes`` /
    ``targets``), so newly added identity-carrying structures are covered by
    default. Returns True when anything was redacted.
    """

    redacted = False
    for key in _ID_KEYS:
        if key in data and _is_hidden_id(data[key], hidden_ids):
            data[key] = None
            redacted = True
    for key in _ID_LIST_KEYS:
        values = data.get(key)
        if isinstance(values, list):
            filtered, changed = _filter_id_list(values, hidden_ids)
            if changed:
                redacted = True
                data[key] = filtered
    if redacted:
        # A payload that names its entry (combat.entry_added et al.) must not
        # name a hidden Monster; the id above is already nulled.
        data.pop("display_name", None)
        data.pop("name", None)
    # Recurse into every nested structure, whatever its key.
    for value in data.values():
        if isinstance(value, dict):
            if _redact_hidden_entries(value, hidden_ids):
                redacted = True
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    if _redact_hidden_entries(item, hidden_ids):
                        redacted = True
    return redacted


def _aligned_request_ids(data: dict[str, Any], hidden_ids: frozenset[str]) -> bool:
    """Drop hidden-only initiative units from ``roll_request_ids`` (M07-D D1 F01).

    Initiative ``roll.requested`` aligns ``roll_request_ids[i]`` with the
    ``combat_entry_ids[i]`` unit. Units whose entries are all hidden are
    removed from both lists so the request list and its count cannot be used
    to infer hidden combatants. Returns True when anything was dropped.
    """
    request_ids = data.get("roll_request_ids")
    groups = data.get("combat_entry_ids")
    if not isinstance(request_ids, list) or not isinstance(groups, list):
        return False
    if len(request_ids) != len(groups):
        return False
    kept_requests: list = []
    kept_groups: list = []
    dropped = False
    for request_id, group in zip(request_ids, groups, strict=True):
        entries = group if isinstance(group, list) else [group]
        visible = [entry for entry in entries if not _is_hidden_id(entry, hidden_ids)]
        if not entries or not visible:
            # A unit with no visible entries vanishes entirely.
            dropped = True
            continue
        kept_requests.append(request_id)
        kept_groups.append(visible if isinstance(group, list) else visible[0])
    if dropped:
        data["roll_request_ids"] = kept_requests
        data["combat_entry_ids"] = kept_groups
    return dropped


def _payload_references_hidden(data: dict[str, Any], hidden_ids: frozenset[str]) -> bool:
    """True when any id-carrying key of the payload names a hidden combatant."""
    for key in _ID_KEYS:
        if key in data and _is_hidden_id(data[key], hidden_ids):
            return True
    for key in _ID_LIST_KEYS:
        values = data.get(key)
        if isinstance(values, list):
            for value in values:
                items = value if isinstance(value, list) else [value]
                if any(_is_hidden_id(item, hidden_ids) for item in items):
                    return True
    return False


def _all_entry_ids_hidden(data: dict[str, Any], hidden_ids: frozenset[str]) -> bool:
    """True when ``combat_entry_ids`` names only hidden combatants (M07-D D1 F01).

    Used for initiative roll events: a hidden-only initiative request or
    result carries no Player-actionable content, so the event is withheld
    from Players instead of being sent as a suggestive empty shell.
    """
    groups = data.get("combat_entry_ids")
    if not isinstance(groups, list) or not groups:
        return False
    for group in groups:
        entries = group if isinstance(group, list) else [group]
        if not entries:
            continue
        if any(not _is_hidden_id(entry, hidden_ids) for entry in entries):
            return False
    return True


def project_combat_event_payload(
    kind: str,
    payload: dict[str, Any],
    *,
    audience: CombatantAudience,
    hidden_entry_ids: frozenset[str] = frozenset(),
) -> dict[str, Any] | None:
    """Project combat event payloads and mutation responses for caller visibility.

    DM audience receives the complete payload untouched.
    Player audience has exact enemy HP, AC, saving throw modifiers, and caster DCs
    redacted while preserving damage amounts, hit/crit, outcomes, and injury levels.
    Hidden Monster entry ids/names (P5-A B6) are stripped for Players whenever the
    caller supplies them via hidden_entry_ids.
    Non-combat event kinds are never modified.
    Returns None when a Player must not receive the event at all (M07-D D1 F01):
    bookkeeping / entry-lifecycle events about a hidden Monster, and
    initiative roll events that reference only hidden combatants.
    """
    if audience == "dm":
        return payload
    if not kind.startswith("combat.") and kind not in {"roll.resolved", "roll.requested"}:
        return payload

    data = deepcopy(payload)
    # M07-C: the tactical start idempotency intent (incl. load_map_monsters)
    # is DM bookkeeping; with every loaded monster hidden it would tell
    # Players that hidden monsters exist.
    data.pop("start_intent", None)

    if hidden_entry_ids:
        if kind in _HIDDEN_SUBJECT_SUPPRESSED_KINDS and _payload_references_hidden(data, hidden_entry_ids):
            return None
        if kind == "roll.requested" and isinstance(data.get("combat_entry_ids"), list):
            _aligned_request_ids(data, hidden_entry_ids)
            if _all_entry_ids_hidden(payload, hidden_entry_ids):
                return None
        elif kind == "roll.resolved" and isinstance(data.get("combat_entry_ids"), list):
            if _all_entry_ids_hidden(data, hidden_entry_ids):
                return None
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
