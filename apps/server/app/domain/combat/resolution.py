from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Iterable, Literal, Mapping, Sequence


class RollMode(StrEnum):
    NORMAL = "normal"
    ADVANTAGE = "advantage"
    DISADVANTAGE = "disadvantage"


class AttackKind(StrEnum):
    MELEE = "melee"
    RANGED = "ranged"


class TargetKind(StrEnum):
    CHARACTER = "character"
    MONSTER = "monster"


class DamageType(StrEnum):
    """2014 damage types plus an application-only semantic manual-damage sentinel."""

    UNTYPED = "untyped"
    ACID = "acid"
    BLUDGEONING = "bludgeoning"
    COLD = "cold"
    FIRE = "fire"
    FORCE = "force"
    LIGHTNING = "lightning"
    NECROTIC = "necrotic"
    PIERCING = "piercing"
    POISON = "poison"
    PSYCHIC = "psychic"
    RADIANT = "radiant"
    SLASHING = "slashing"
    THUNDER = "thunder"


class SizeCategory(IntEnum):
    TINY = 0
    SMALL = 1
    MEDIUM = 2
    LARGE = 3
    HUGE = 4
    GARGANTUAN = 5


class SpecialAttackKind(StrEnum):
    GRAPPLE = "grapple"
    SHOVE_PRONE = "shove_prone"
    SHOVE_PUSH = "shove_push"


@dataclass(frozen=True)
class ModifierSource:
    source: str
    value: int


@dataclass(frozen=True)
class DamageFormulaPart:
    damage_type: DamageType
    dice_count: int
    die_size: int
    flat_modifier: int = 0

    def __post_init__(self) -> None:
        if self.dice_count < 0:
            raise ValueError("dice_count cannot be negative")
        if self.dice_count and self.die_size < 2:
            raise ValueError("die_size must be >= 2 when dice_count is positive")
        if not self.dice_count and self.die_size not in (0, 1):
            raise ValueError("flat-only damage must use die_size 0 or 1")


@dataclass(frozen=True)
class ResolvedAttack:
    """Normalized P4-C attack shape shared by Character and Monster resolvers."""

    source_ref: str
    name: str
    attack_bonus: int
    attack_kind: AttackKind
    damage_parts: tuple[DamageFormulaPart, ...]
    modifier_sources: tuple[ModifierSource, ...] = ()
    notes: tuple[str, ...] = ()
    content_ref: str | None = None
    presentation_field: str | None = None

    def __post_init__(self) -> None:
        if not self.source_ref.strip():
            raise ValueError("source_ref cannot be blank")
        if not self.name.strip():
            raise ValueError("name cannot be blank")
        if not self.damage_parts:
            raise ValueError("an attack must declare at least one damage part")


@dataclass(frozen=True)
class AttackRollOutcome:
    mode: RollMode
    raw_d20: tuple[int, ...]
    selected_d20: int
    modifier: int
    total: int
    target_ac: int
    hit: bool
    critical: bool
    automatic: Literal["critical_hit", "automatic_miss"] | None = None
    modifier_sources: tuple[ModifierSource, ...] = ()


@dataclass(frozen=True)
class DamageRollPart:
    """One already-rolled damage component.

    ``critical_dice`` contains the additional dice results rolled for a critical
    hit. Flat modifiers are deliberately not duplicated.
    """

    damage_type: DamageType
    dice: tuple[int, ...] = ()
    flat_modifier: int = 0
    critical_dice: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if any(value < 0 for value in (*self.dice, *self.critical_dice)):
            raise ValueError("damage die results cannot be negative")


@dataclass(frozen=True)
class HitPointState:
    current_hp: int
    max_hp: int
    temp_hp: int = 0

    def __post_init__(self) -> None:
        if self.max_hp <= 0:
            raise ValueError("max_hp must be positive")
        if not 0 <= self.current_hp <= self.max_hp:
            raise ValueError("current_hp must be between 0 and max_hp")
        if self.temp_hp < 0:
            raise ValueError("temp_hp cannot be negative")


@dataclass(frozen=True)
class DeathSaveState:
    successes: int = 0
    failures: int = 0
    stable: bool = False
    dead: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.successes <= 2:
            raise ValueError("successes must be between 0 and 2")
        if not 0 <= self.failures <= 2:
            raise ValueError("failures must be between 0 and 2")
        if self.stable and self.dead:
            raise ValueError("death-save state cannot be both stable and dead")


@dataclass(frozen=True)
class DamageOutcome:
    before: HitPointState
    after: HitPointState
    raw_by_type: Mapping[str, int]
    adjusted_by_type: Mapping[str, int]
    raw_total: int
    adjusted_total: int
    temp_hp_absorbed: int
    hp_lost: int
    dropped_to_zero: bool
    instant_death: bool
    apply_unconscious: bool
    apply_prone: bool
    monster_outcome_required: bool
    death_saves: DeathSaveState | None


@dataclass(frozen=True)
class HealingOutcome:
    before: HitPointState
    after: HitPointState
    requested: int
    restored: int
    remove_unconscious: bool
    keep_prone: bool
    death_saves: DeathSaveState | None


@dataclass(frozen=True)
class DeathSaveOutcome:
    d20: int
    hp_after: int
    death_saves: DeathSaveState
    natural_20_recovery: bool = False


@dataclass(frozen=True)
class SpecialAttackOutcome:
    kind: SpecialAttackKind
    status: Literal["success", "failure", "invalid", "dm_adjudication_required"]
    reason: str | None = None
    condition_to_apply: Literal["grappled", "prone"] | None = None
    push_distance_ft: int | None = None


def _validate_d20s(values: Sequence[int]) -> tuple[int, ...]:
    rolls = tuple(values)
    if not rolls:
        raise ValueError("at least one d20 result is required")
    if any(value < 1 or value > 20 for value in rolls):
        raise ValueError("d20 results must be between 1 and 20")
    return rolls


def resolve_attack_roll(
    *,
    d20_rolls: Sequence[int],
    modifier: int,
    target_ac: int,
    mode: RollMode = RollMode.NORMAL,
    modifier_sources: Iterable[ModifierSource] = (),
) -> AttackRollOutcome:
    """Resolve a 2014 attack roll without owning formal Roll persistence."""

    rolls = _validate_d20s(d20_rolls)
    if target_ac < 0:
        raise ValueError("target_ac cannot be negative")
    if mode is RollMode.NORMAL:
        selected = rolls[0]
    elif mode is RollMode.ADVANTAGE:
        if len(rolls) < 2:
            raise ValueError("advantage requires at least two d20 results")
        selected = max(rolls)
    else:
        if len(rolls) < 2:
            raise ValueError("disadvantage requires at least two d20 results")
        selected = min(rolls)

    total = selected + modifier
    if selected == 20:
        return AttackRollOutcome(
            mode=mode,
            raw_d20=rolls,
            selected_d20=selected,
            modifier=modifier,
            total=total,
            target_ac=target_ac,
            hit=True,
            critical=True,
            automatic="critical_hit",
            modifier_sources=tuple(modifier_sources),
        )
    if selected == 1:
        return AttackRollOutcome(
            mode=mode,
            raw_d20=rolls,
            selected_d20=selected,
            modifier=modifier,
            total=total,
            target_ac=target_ac,
            hit=False,
            critical=False,
            automatic="automatic_miss",
            modifier_sources=tuple(modifier_sources),
        )
    return AttackRollOutcome(
        mode=mode,
        raw_d20=rolls,
        selected_d20=selected,
        modifier=modifier,
        total=total,
        target_ac=target_ac,
        hit=total >= target_ac,
        critical=False,
        modifier_sources=tuple(modifier_sources),
    )


def raw_damage_by_type(
    parts: Iterable[DamageRollPart],
    *,
    critical: bool = False,
) -> dict[str, int]:
    """Aggregate one damage instance by type before resistance math."""

    totals: dict[str, int] = {}
    for part in parts:
        amount = sum(part.dice) + part.flat_modifier
        if critical:
            amount += sum(part.critical_dice)
        if amount < 0:
            amount = 0
        key = part.damage_type.value
        totals[key] = totals.get(key, 0) + amount
    return totals


def adjust_damage_by_affinity(
    raw: Mapping[str, int],
    *,
    resistances: Iterable[DamageType] = (),
    immunities: Iterable[DamageType] = (),
    vulnerabilities: Iterable[DamageType] = (),
) -> dict[str, int]:
    resistant = {item.value for item in resistances if item is not DamageType.UNTYPED}
    immune = {item.value for item in immunities if item is not DamageType.UNTYPED}
    vulnerable = {item.value for item in vulnerabilities if item is not DamageType.UNTYPED}
    adjusted: dict[str, int] = {}
    for damage_type, amount in raw.items():
        value = max(0, int(amount))
        if damage_type in immune:
            value = 0
        else:
            if damage_type in resistant:
                value //= 2
            if damage_type in vulnerable:
                value *= 2
        adjusted[damage_type] = value
    return adjusted


def apply_damage(
    state: HitPointState,
    parts: Iterable[DamageRollPart],
    *,
    target_kind: TargetKind,
    critical: bool = False,
    resistances: Iterable[DamageType] = (),
    immunities: Iterable[DamageType] = (),
    vulnerabilities: Iterable[DamageType] = (),
    death_saves: DeathSaveState | None = None,
    zero_hp_failure_count: int = 1,
) -> DamageOutcome:
    """Apply one semantic damage instance in P4-C order.

    Concentration is intentionally not resolved here; P4-D may subscribe to
    this semantic boundary. The returned outcome contains every HP transition
    needed by that later trigger.
    """

    if zero_hp_failure_count not in (1, 2):
        raise ValueError("zero_hp_failure_count must be 1 or 2")

    raw = raw_damage_by_type(parts, critical=critical)
    adjusted = adjust_damage_by_affinity(
        raw,
        resistances=resistances,
        immunities=immunities,
        vulnerabilities=vulnerabilities,
    )
    total = sum(adjusted.values())
    absorbed = min(state.temp_hp, total)
    remaining = total - absorbed
    hp_lost = min(state.current_hp, remaining)
    hp_after = state.current_hp - hp_lost
    temp_after = state.temp_hp - absorbed
    dropped_to_zero = state.current_hp > 0 and hp_after == 0 and remaining > 0
    overflow_after_zero = max(0, remaining - state.current_hp)
    instant_death = (
        target_kind is TargetKind.CHARACTER
        and hp_after == 0
        and overflow_after_zero >= state.max_hp
        and remaining > 0
    )

    next_death_saves = death_saves
    apply_unconscious = False
    apply_prone = False
    monster_outcome_required = False

    if target_kind is TargetKind.CHARACTER and hp_after == 0:
        if death_saves is not None and death_saves.dead:
            next_death_saves = death_saves
        elif instant_death:
            next_death_saves = DeathSaveState(dead=True)
        else:
            apply_unconscious = True
            apply_prone = dropped_to_zero
            if dropped_to_zero:
                next_death_saves = DeathSaveState()
            elif remaining > 0:
                current = death_saves or DeathSaveState()
                failures = current.failures + zero_hp_failure_count
                if failures >= 3:
                    next_death_saves = DeathSaveState(dead=True)
                else:
                    next_death_saves = DeathSaveState(
                        successes=current.successes,
                        failures=failures,
                    )
    elif target_kind is TargetKind.MONSTER and hp_after == 0 and remaining > 0:
        monster_outcome_required = True

    return DamageOutcome(
        before=state,
        after=HitPointState(current_hp=hp_after, max_hp=state.max_hp, temp_hp=temp_after),
        raw_by_type=MappingProxyType(dict(raw)),
        adjusted_by_type=MappingProxyType(dict(adjusted)),
        raw_total=sum(raw.values()),
        adjusted_total=total,
        temp_hp_absorbed=absorbed,
        hp_lost=hp_lost,
        dropped_to_zero=dropped_to_zero,
        instant_death=instant_death,
        apply_unconscious=apply_unconscious,
        apply_prone=apply_prone,
        monster_outcome_required=monster_outcome_required,
        death_saves=next_death_saves,
    )


def apply_healing(
    state: HitPointState,
    amount: int,
    *,
    target_kind: TargetKind,
    death_saves: DeathSaveState | None = None,
) -> HealingOutcome:
    if amount < 0:
        raise ValueError("healing amount cannot be negative")
    if target_kind is TargetKind.CHARACTER and death_saves is not None and death_saves.dead:
        raise ValueError("ordinary healing cannot restore a dead character")
    restored = min(amount, state.max_hp - state.current_hp)
    hp_after = state.current_hp + restored
    recovered_from_zero = state.current_hp == 0 and hp_after > 0
    next_death_saves = death_saves
    if target_kind is TargetKind.CHARACTER and recovered_from_zero:
        next_death_saves = DeathSaveState()
    return HealingOutcome(
        before=state,
        after=HitPointState(current_hp=hp_after, max_hp=state.max_hp, temp_hp=state.temp_hp),
        requested=amount,
        restored=restored,
        remove_unconscious=target_kind is TargetKind.CHARACTER and recovered_from_zero,
        keep_prone=recovered_from_zero,
        death_saves=next_death_saves,
    )


def resolve_death_save(
    *,
    d20: int,
    state: DeathSaveState,
) -> DeathSaveOutcome:
    if d20 < 1 or d20 > 20:
        raise ValueError("death save d20 must be between 1 and 20")
    if state.dead:
        raise ValueError("a dead creature cannot make a death save")
    if state.stable:
        raise ValueError("a stable creature does not make death saves")

    if d20 == 20:
        return DeathSaveOutcome(
            d20=d20,
            hp_after=1,
            death_saves=DeathSaveState(),
            natural_20_recovery=True,
        )

    failures = state.failures + (2 if d20 == 1 else 1 if d20 <= 9 else 0)
    successes = state.successes + (1 if d20 >= 10 else 0)
    if failures >= 3:
        return DeathSaveOutcome(d20=d20, hp_after=0, death_saves=DeathSaveState(dead=True))
    if successes >= 3:
        return DeathSaveOutcome(d20=d20, hp_after=0, death_saves=DeathSaveState(stable=True))
    return DeathSaveOutcome(
        d20=d20,
        hp_after=0,
        death_saves=DeathSaveState(successes=successes, failures=failures),
    )


def resolve_grapple_or_shove(
    *,
    kind: SpecialAttackKind,
    attacker_size: SizeCategory,
    target_size: SizeCategory,
    attacker_check_total: int,
    target_check_total: int,
    attacker_has_free_hand: bool = True,
    reach_confirmed: bool | None = None,
) -> SpecialAttackOutcome:
    """Resolve the non-geometry half of 2014 Grapple/Shove.

    ``reach_confirmed=None`` is intentionally not guessed in Quick Combat. The
    caller must persist a DM adjudication request and resume this same action.
    """

    if target_size > attacker_size + 1:
        return SpecialAttackOutcome(kind=kind, status="invalid", reason="target_too_large")
    if kind is SpecialAttackKind.GRAPPLE and not attacker_has_free_hand:
        return SpecialAttackOutcome(kind=kind, status="invalid", reason="free_hand_required")
    if reach_confirmed is None:
        return SpecialAttackOutcome(
            kind=kind,
            status="dm_adjudication_required",
            reason="reach_required",
        )
    if not reach_confirmed:
        return SpecialAttackOutcome(kind=kind, status="invalid", reason="out_of_reach")

    if attacker_check_total <= target_check_total:
        return SpecialAttackOutcome(kind=kind, status="failure", reason="opposed_check_lost_or_tied")
    if kind is SpecialAttackKind.GRAPPLE:
        return SpecialAttackOutcome(kind=kind, status="success", condition_to_apply="grappled")
    if kind is SpecialAttackKind.SHOVE_PRONE:
        return SpecialAttackOutcome(kind=kind, status="success", condition_to_apply="prone")
    return SpecialAttackOutcome(kind=kind, status="success", push_distance_ft=5)


__all__ = [
    "AttackKind",
    "AttackRollOutcome",
    "DamageFormulaPart",
    "DamageOutcome",
    "DamageRollPart",
    "DamageType",
    "DeathSaveOutcome",
    "DeathSaveState",
    "HealingOutcome",
    "HitPointState",
    "ModifierSource",
    "ResolvedAttack",
    "RollMode",
    "SizeCategory",
    "SpecialAttackKind",
    "SpecialAttackOutcome",
    "TargetKind",
    "adjust_damage_by_affinity",
    "apply_damage",
    "apply_healing",
    "raw_damage_by_type",
    "resolve_attack_roll",
    "resolve_death_save",
    "resolve_grapple_or_shove",
]
