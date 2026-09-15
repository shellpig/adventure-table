from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal


class Condition(StrEnum):
    RESTRAINED = "restrained"
    FRIGHTENED = "frightened"
    STUNNED = "stunned"


@dataclass(frozen=True)
class ConditionSemantics:
    blocks_actions: bool = False
    blocks_reactions: bool = False
    speed_zero: bool = False
    attacks_disadvantage: bool = False
    attacks_against_advantage: bool = False
    auto_fail_strength_saves: bool = False
    auto_fail_dexterity_saves: bool = False
    dexterity_saves_disadvantage: bool = False
    cannot_move_closer_to_source: bool = False


CONDITION_SEMANTICS = {
    Condition.RESTRAINED: ConditionSemantics(
        speed_zero=True,
        attacks_disadvantage=True,
        attacks_against_advantage=True,
        dexterity_saves_disadvantage=True,
    ),
    Condition.FRIGHTENED: ConditionSemantics(
        attacks_disadvantage=True,
        cannot_move_closer_to_source=True,
    ),
    Condition.STUNNED: ConditionSemantics(
        blocks_actions=True,
        blocks_reactions=True,
        speed_zero=True,
        attacks_against_advantage=True,
        auto_fail_strength_saves=True,
        auto_fail_dexterity_saves=True,
    ),
}


class DurationKind(StrEnum):
    ROUNDS = "rounds"
    UNTIL_TURN_START = "until_turn_start"
    UNTIL_TURN_END = "until_turn_end"
    INSTANT = "instant"


@dataclass(frozen=True)
class DurationSpec:
    kind: DurationKind
    rounds: int | None = None

    def __post_init__(self) -> None:
        if self.kind is DurationKind.ROUNDS:
            if self.rounds is None or self.rounds <= 0:
                raise ValueError("round duration requires a positive rounds value")
        elif self.rounds is not None:
            raise ValueError("rounds may only be set for round duration")


@dataclass(frozen=True)
class EffectSpec:
    effect_type: Literal["condition", "buff", "debuff", "movement_lock", "reaction_modifier"]
    tag: str
    duration: DurationSpec
    source_ref: str

    def __post_init__(self) -> None:
        if not self.tag.strip() or not self.source_ref.strip():
            raise ValueError("effect tag and source_ref cannot be blank")


@dataclass(frozen=True)
class ActiveEffect:
    effect_id: str
    spec: EffectSpec
    concentration_owner_ref: str | None = None
    remaining_rounds: int | None = None

    @classmethod
    def create(
        cls, effect_id: str, spec: EffectSpec, *, concentration_owner_ref: str | None = None
    ) -> "ActiveEffect":
        return cls(
            effect_id=effect_id,
            spec=spec,
            concentration_owner_ref=concentration_owner_ref,
            remaining_rounds=spec.duration.rounds,
        )


@dataclass(frozen=True)
class Concentration:
    owner_ref: str
    source_ref: str
    effect_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConcentrationTransition:
    concentration: Concentration | None
    effects: tuple[ActiveEffect, ...]
    removed_effect_ids: tuple[str, ...]
    events: tuple[dict[str, object], ...]


def start_concentration(
    *,
    owner_ref: str,
    source_ref: str,
    effects: tuple[ActiveEffect, ...],
    current: Concentration | None = None,
) -> ConcentrationTransition:
    removed: tuple[str, ...] = ()
    remaining = effects
    events: list[dict[str, object]] = []
    if current is not None:
        removed = current.effect_ids
        remaining = tuple(effect for effect in effects if effect.effect_id not in set(removed))
        events.append(
            {"type": "concentration_ended", "source_ref": current.source_ref, "reason": "replaced"}
        )
    linked = tuple(
        effect.effect_id
        for effect in remaining
        if effect.concentration_owner_ref == owner_ref and effect.spec.source_ref == source_ref
    )
    concentration = Concentration(owner_ref=owner_ref, source_ref=source_ref, effect_ids=linked)
    events.append(
        {"type": "concentration_started", "source_ref": source_ref, "effect_ids": list(linked)}
    )
    return ConcentrationTransition(concentration, remaining, removed, tuple(events))


def end_concentration(
    *, current: Concentration, effects: tuple[ActiveEffect, ...], reason: str
) -> ConcentrationTransition:
    removed_set = set(current.effect_ids)
    remaining = tuple(effect for effect in effects if effect.effect_id not in removed_set)
    return ConcentrationTransition(
        None,
        remaining,
        current.effect_ids,
        ({"type": "concentration_ended", "source_ref": current.source_ref, "reason": reason},),
    )


def concentration_dc(damage_taken: int) -> int:
    if damage_taken < 0:
        raise ValueError("damage_taken cannot be negative")
    return max(10, damage_taken // 2)


def resolve_concentration_damage(
    *,
    current: Concentration | None,
    effects: tuple[ActiveEffect, ...],
    damage_taken: int,
    d20: int,
    constitution_save_modifier: int,
) -> ConcentrationTransition:
    if current is None or damage_taken <= 0:
        return ConcentrationTransition(current, effects, (), ())
    if d20 < 1 or d20 > 20:
        raise ValueError("concentration d20 must be between 1 and 20")
    dc = concentration_dc(damage_taken)
    total = d20 + constitution_save_modifier
    check = {
        "type": "concentration_check",
        "dc": dc,
        "d20": d20,
        "modifier": constitution_save_modifier,
        "total": total,
        "success": total >= dc,
    }
    if total >= dc:
        return ConcentrationTransition(current, effects, (), (check,))
    ended = end_concentration(current=current, effects=effects, reason="failed_save")
    return ConcentrationTransition(
        None, ended.effects, ended.removed_effect_ids, (check, *ended.events)
    )


def expire_effects(
    effects: tuple[ActiveEffect, ...], *, boundary: Literal["round", "turn_start", "turn_end"]
) -> tuple[tuple[ActiveEffect, ...], tuple[str, ...]]:
    kept: list[ActiveEffect] = []
    expired: list[str] = []
    for effect in effects:
        duration = effect.spec.duration
        should_expire = (
            (boundary == "turn_start" and duration.kind is DurationKind.UNTIL_TURN_START)
            or (boundary == "turn_end" and duration.kind is DurationKind.UNTIL_TURN_END)
        )
        if boundary == "round" and duration.kind is DurationKind.ROUNDS:
            remaining = int(effect.remaining_rounds or 0) - 1
            if remaining <= 0:
                should_expire = True
            else:
                effect = replace(effect, remaining_rounds=remaining)
        if duration.kind is DurationKind.INSTANT:
            should_expire = True
        if should_expire:
            expired.append(effect.effect_id)
        else:
            kept.append(effect)
    return tuple(kept), tuple(expired)
