from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal


class Condition(StrEnum):
    BLINDED = "blinded"
    CHARMED = "charmed"
    DEAFENED = "deafened"
    FRIGHTENED = "frightened"
    GRAPPLED = "grappled"
    INCAPACITATED = "incapacitated"
    INVISIBLE = "invisible"
    PARALYZED = "paralyzed"
    PETRIFIED = "petrified"
    POISONED = "poisoned"
    PRONE = "prone"
    RESTRAINED = "restrained"
    STUNNED = "stunned"
    UNCONSCIOUS = "unconscious"


@dataclass(frozen=True)
class ConditionSemantics:
    """Typed 2014 mechanical contributions used by the combat rules layer.

    Context-dependent clauses (source visibility, 5-foot adjacency, hearing,
    grappler reach, etc.) are represented explicitly instead of guessed by
    Quick Combat, which has no geometry.
    """

    blocks_actions: bool = False
    blocks_reactions: bool = False
    speed_zero: bool = False
    attacks_disadvantage: bool = False
    attacks_disadvantage_while_source_visible: bool = False
    attacks_advantage: bool = False
    attacks_against_advantage: bool = False
    attacks_against_disadvantage: bool = False
    attacks_against_advantage_within_5ft: bool = False
    attacks_against_disadvantage_beyond_5ft: bool = False
    ability_checks_disadvantage: bool = False
    saves_disadvantage: bool = False
    dexterity_saves_disadvantage: bool = False
    auto_fail_strength_saves: bool = False
    auto_fail_dexterity_saves: bool = False
    auto_fail_sight_checks: bool = False
    auto_fail_hearing_checks: bool = False
    cannot_see: bool = False
    cannot_hear: bool = False
    cannot_speak: bool = False
    cannot_move: bool = False
    cannot_move_closer_to_source: bool = False
    cannot_attack_source: bool = False
    source_social_checks_advantage: bool = False
    unaware_of_surroundings: bool = False
    drops_held_items: bool = False
    falls_prone: bool = False
    adjacent_hit_is_critical: bool = False
    crawl_or_stand_only: bool = False
    damage_resistance_all: bool = False
    poison_disease_immune_or_suspended: bool = False
    transformed_to_inanimate_substance: bool = False
    invisible_to_unaided_sight: bool = False
    ends_if_grappler_incapacitated_or_out_of_reach: bool = False


CONDITION_SEMANTICS: dict[Condition, ConditionSemantics] = {
    Condition.BLINDED: ConditionSemantics(
        cannot_see=True,
        auto_fail_sight_checks=True,
        attacks_disadvantage=True,
        attacks_against_advantage=True,
    ),
    Condition.CHARMED: ConditionSemantics(
        cannot_attack_source=True,
        source_social_checks_advantage=True,
    ),
    Condition.DEAFENED: ConditionSemantics(
        cannot_hear=True,
        auto_fail_hearing_checks=True,
    ),
    Condition.FRIGHTENED: ConditionSemantics(
        attacks_disadvantage_while_source_visible=True,
        ability_checks_disadvantage=True,
        cannot_move_closer_to_source=True,
    ),
    Condition.GRAPPLED: ConditionSemantics(
        speed_zero=True,
        ends_if_grappler_incapacitated_or_out_of_reach=True,
    ),
    Condition.INCAPACITATED: ConditionSemantics(
        blocks_actions=True,
        blocks_reactions=True,
    ),
    Condition.INVISIBLE: ConditionSemantics(
        invisible_to_unaided_sight=True,
        attacks_advantage=True,
        attacks_against_disadvantage=True,
    ),
    Condition.PARALYZED: ConditionSemantics(
        blocks_actions=True,
        blocks_reactions=True,
        cannot_move=True,
        cannot_speak=True,
        attacks_against_advantage=True,
        auto_fail_strength_saves=True,
        auto_fail_dexterity_saves=True,
        adjacent_hit_is_critical=True,
    ),
    Condition.PETRIFIED: ConditionSemantics(
        blocks_actions=True,
        blocks_reactions=True,
        cannot_move=True,
        cannot_speak=True,
        unaware_of_surroundings=True,
        attacks_against_advantage=True,
        auto_fail_strength_saves=True,
        auto_fail_dexterity_saves=True,
        damage_resistance_all=True,
        poison_disease_immune_or_suspended=True,
        transformed_to_inanimate_substance=True,
    ),
    Condition.POISONED: ConditionSemantics(
        attacks_disadvantage=True,
        ability_checks_disadvantage=True,
    ),
    Condition.PRONE: ConditionSemantics(
        attacks_disadvantage=True,
        attacks_against_advantage_within_5ft=True,
        attacks_against_disadvantage_beyond_5ft=True,
        crawl_or_stand_only=True,
    ),
    Condition.RESTRAINED: ConditionSemantics(
        speed_zero=True,
        attacks_disadvantage=True,
        attacks_against_advantage=True,
        dexterity_saves_disadvantage=True,
    ),
    Condition.STUNNED: ConditionSemantics(
        blocks_actions=True,
        blocks_reactions=True,
        cannot_move=True,
        attacks_against_advantage=True,
        auto_fail_strength_saves=True,
        auto_fail_dexterity_saves=True,
    ),
    Condition.UNCONSCIOUS: ConditionSemantics(
        blocks_actions=True,
        blocks_reactions=True,
        cannot_move=True,
        cannot_speak=True,
        unaware_of_surroundings=True,
        drops_held_items=True,
        falls_prone=True,
        attacks_against_advantage=True,
        auto_fail_strength_saves=True,
        auto_fail_dexterity_saves=True,
        adjacent_hit_is_critical=True,
    ),
}


@dataclass(frozen=True)
class ExhaustionSemantics:
    level: int
    ability_checks_disadvantage: bool = False
    speed_multiplier: float = 1.0
    attacks_disadvantage: bool = False
    saves_disadvantage: bool = False
    max_hp_multiplier: float = 1.0
    speed_zero: bool = False
    dead: bool = False


def exhaustion_semantics(level: int) -> ExhaustionSemantics:
    """Return cumulative 2014 exhaustion mechanics for levels 0..6."""

    if level < 0 or level > 6:
        raise ValueError("exhaustion level must be between 0 and 6")
    return ExhaustionSemantics(
        level=level,
        ability_checks_disadvantage=level >= 1,
        speed_multiplier=0.5 if level >= 2 else 1.0,
        attacks_disadvantage=level >= 3,
        saves_disadvantage=level >= 3,
        max_hp_multiplier=0.5 if level >= 4 else 1.0,
        speed_zero=level >= 5,
        dead=level >= 6,
    )


def change_exhaustion(level: int, delta: int) -> int:
    """Apply exhaustion gain/recovery without allowing an invalid state."""

    if level < 0 or level > 6:
        raise ValueError("exhaustion level must be between 0 and 6")
    return min(6, max(0, level + delta))


class ModifierScope(StrEnum):
    AC = "ac"
    SPEED = "speed"
    ATTACK = "attack"
    SAVE = "save"
    CHECK = "check"
    DAMAGE = "damage"


class ModifierMode(StrEnum):
    BONUS = "bonus"
    ADVANTAGE = "advantage"
    DISADVANTAGE = "disadvantage"


@dataclass(frozen=True)
class TypedModifier:
    scope: ModifierScope
    mode: ModifierMode
    value: int = 0
    target: str | None = None

    def __post_init__(self) -> None:
        if self.mode is not ModifierMode.BONUS and self.value != 0:
            raise ValueError("advantage/disadvantage modifier cannot carry a numeric value")
        if self.target is not None and not self.target.strip():
            raise ValueError("modifier target cannot be blank")


class DurationKind(StrEnum):
    ROUNDS = "rounds"
    UNTIL_TURN_START = "until_turn_start"
    UNTIL_TURN_END = "until_turn_end"
    UNTIL_SHORT_REST = "until_short_rest"
    UNTIL_LONG_REST = "until_long_rest"
    UNTIL_CONCENTRATION_ENDS = "until_concentration_ends"
    MANUAL = "manual"
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
    modifiers: tuple[TypedModifier, ...] = ()
    note: str | None = None

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
        if not effect_id.strip():
            raise ValueError("effect_id cannot be blank")
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
        removed_set = set(removed)
        remaining = tuple(effect for effect in effects if effect.effect_id not in removed_set)
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


def apply_condition(
    conditions: tuple[Condition, ...], condition: Condition
) -> tuple[Condition, ...]:
    if condition in conditions:
        return conditions
    return (*conditions, condition)


def remove_condition(
    conditions: tuple[Condition, ...], condition: Condition
) -> tuple[Condition, ...]:
    return tuple(value for value in conditions if value is not condition)


def expire_effects(
    effects: tuple[ActiveEffect, ...],
    *,
    boundary: Literal["round", "turn_start", "turn_end", "short_rest", "long_rest"],
) -> tuple[tuple[ActiveEffect, ...], tuple[str, ...]]:
    kept: list[ActiveEffect] = []
    expired: list[str] = []
    for effect in effects:
        duration = effect.spec.duration
        should_expire = (
            (boundary == "turn_start" and duration.kind is DurationKind.UNTIL_TURN_START)
            or (boundary == "turn_end" and duration.kind is DurationKind.UNTIL_TURN_END)
            or (boundary == "short_rest" and duration.kind is DurationKind.UNTIL_SHORT_REST)
            or (
                boundary == "long_rest"
                and duration.kind in {DurationKind.UNTIL_SHORT_REST, DurationKind.UNTIL_LONG_REST}
            )
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
