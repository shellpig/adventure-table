from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.domain.combat.effect_resolver import CONDITION_SEMANTICS, Condition, exhaustion_semantics
from app.domain.combat.resolution import AttackKind, RollMode
from app.domain.rooms.rolls import RollModifierMode

_ABILITY_ALIASES = {
    "str": "strength", "dex": "dexterity", "con": "constitution",
    "int": "intelligence", "wis": "wisdom", "cha": "charisma",
}


def _normalize_ability(ability_ref: str) -> str:
    slug = ability_ref.rsplit(":", 1)[-1].strip().lower()
    return _ABILITY_ALIASES.get(slug, slug)


def conditions_from_refs(
    refs: Iterable[str],
    *,
    ignore_unknown: bool = False,
) -> frozenset[Condition]:
    """Parse 2014 condition references or bare slugs into Condition enum values."""
    result: set[Condition] = set()
    for ref in refs:
        try:
            result.add(Condition(ref.rsplit(":", 1)[-1]))
        except ValueError as exc:
            if ignore_unknown:
                continue
            raise ValueError(f"unsupported 2014 combat condition: {ref}") from exc
    return frozenset(result)


def _combine(advantage_sources: list[str], disadvantage_sources: list[str]) -> RollMode:
    """5e 2014: any advantage and any disadvantage cancel to normal, whatever the counts."""
    if advantage_sources and disadvantage_sources:
        return RollMode.NORMAL
    if advantage_sources:
        return RollMode.ADVANTAGE
    return RollMode.DISADVANTAGE if disadvantage_sources else RollMode.NORMAL


@dataclass(frozen=True)
class AttackModifierDecision:
    mode: RollMode
    critical_on_hit: bool
    advantage_sources: tuple[str, ...]
    disadvantage_sources: tuple[str, ...]
    unresolved: tuple[str, ...]
    chosen: RollMode = RollMode.NORMAL


@dataclass(frozen=True)
class SaveModifierDecision:
    mode: RollModifierMode
    auto_fail: bool
    advantage_sources: tuple[str, ...]
    disadvantage_sources: tuple[str, ...]
    auto_fail_sources: tuple[str, ...]
    chosen: RollModifierMode = RollModifierMode.NORMAL


def attack_decision_payload(decision: AttackModifierDecision) -> dict[str, Any]:
    return {
        "chosen": decision.chosen.value,
        "mode": decision.mode.value,
        "critical_on_hit": decision.critical_on_hit,
        "advantage_sources": list(decision.advantage_sources),
        "disadvantage_sources": list(decision.disadvantage_sources),
        "unresolved": list(decision.unresolved),
    }


def save_decision_payload(decision: SaveModifierDecision) -> dict[str, Any]:
    return {
        "chosen": decision.chosen.value,
        "mode": decision.mode.value,
        "auto_fail": decision.auto_fail,
        "advantage_sources": list(decision.advantage_sources),
        "disadvantage_sources": list(decision.disadvantage_sources),
        "auto_fail_sources": list(decision.auto_fail_sources),
    }


def attack_modifiers(
    *,
    chosen: RollMode,
    attack_kind: AttackKind,
    attacker_conditions: Iterable[str],
    target_conditions: Iterable[str],
    attacker_exhaustion: int = 0,
) -> AttackModifierDecision:
    """Evaluate conditions and exhaustion for an attack roll."""
    parsed_attacker = sorted(
        conditions_from_refs(attacker_conditions, ignore_unknown=True),
        key=lambda c: c.value,
    )
    parsed_target = sorted(
        conditions_from_refs(target_conditions, ignore_unknown=True),
        key=lambda c: c.value,
    )
    exhaustion = exhaustion_semantics(attacker_exhaustion)

    adv_sources: list[str] = ["chosen:advantage"] if chosen is RollMode.ADVANTAGE else []
    dis_sources: list[str] = ["chosen:disadvantage"] if chosen is RollMode.DISADVANTAGE else []
    unresolved: list[str] = []
    critical_on_hit = False

    for cond in parsed_attacker:
        sem = CONDITION_SEMANTICS[cond]
        if sem.attacks_advantage:
            adv_sources.append(f"attacker:{cond.value}")
        if sem.attacks_disadvantage:
            dis_sources.append(f"attacker:{cond.value}")
        if sem.attacks_disadvantage_while_source_visible:
            unresolved.append(f"attacker:{cond.value}:source_visibility")

    if exhaustion.attacks_disadvantage:
        dis_sources.append(f"attacker:exhaustion:{attacker_exhaustion}")

    for cond in parsed_target:
        sem = CONDITION_SEMANTICS[cond]
        if sem.attacks_against_advantage or (
            sem.attacks_against_advantage_within_5ft and attack_kind is AttackKind.MELEE
        ):
            adv_sources.append(f"target:{cond.value}")
        if sem.attacks_against_disadvantage or (
            sem.attacks_against_disadvantage_beyond_5ft and attack_kind is AttackKind.RANGED
        ):
            dis_sources.append(f"target:{cond.value}")
        if sem.adjacent_hit_is_critical and attack_kind is AttackKind.MELEE:
            critical_on_hit = True

    return AttackModifierDecision(
        mode=_combine(adv_sources, dis_sources),
        critical_on_hit=critical_on_hit,
        advantage_sources=tuple(adv_sources),
        disadvantage_sources=tuple(dis_sources),
        unresolved=tuple(unresolved),
        chosen=chosen,
    )


def save_modifiers(
    *,
    chosen: RollModifierMode,
    ability_ref: str,
    target_conditions: Iterable[str],
    target_exhaustion: int = 0,
) -> SaveModifierDecision:
    """Evaluate conditions and exhaustion for a saving throw."""
    ability = _normalize_ability(ability_ref)
    parsed_target = sorted(
        conditions_from_refs(target_conditions, ignore_unknown=True),
        key=lambda c: c.value,
    )
    exhaustion = exhaustion_semantics(target_exhaustion)

    auto_fail_sources: list[str] = []
    adv_sources: list[str] = ["chosen:advantage"] if chosen is RollModifierMode.ADVANTAGE else []
    dis_sources: list[str] = ["chosen:disadvantage"] if chosen is RollModifierMode.DISADVANTAGE else []

    for cond in parsed_target:
        sem = CONDITION_SEMANTICS[cond]
        if (ability == "strength" and sem.auto_fail_strength_saves) or (
            ability == "dexterity" and sem.auto_fail_dexterity_saves
        ):
            auto_fail_sources.append(f"target:{cond.value}")
        if sem.saves_disadvantage or (ability == "dexterity" and sem.dexterity_saves_disadvantage):
            dis_sources.append(f"target:{cond.value}")

    if exhaustion.saves_disadvantage:
        dis_sources.append(f"target:exhaustion:{target_exhaustion}")

    return SaveModifierDecision(
        mode=RollModifierMode(_combine(adv_sources, dis_sources).value),
        auto_fail=bool(auto_fail_sources),
        advantage_sources=tuple(adv_sources),
        disadvantage_sources=tuple(dis_sources),
        auto_fail_sources=tuple(auto_fail_sources),
        chosen=chosen,
    )


__all__ = [
    "AttackModifierDecision",
    "SaveModifierDecision",
    "attack_decision_payload",
    "attack_modifiers",
    "conditions_from_refs",
    "save_decision_payload",
    "save_modifiers",
]

