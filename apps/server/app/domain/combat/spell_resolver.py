from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from app.domain.combat.effect_resolver import ActiveEffect, EffectSpec
from app.domain.combat.resolution import (
    DamageRollPart,
    DeathSaveState,
    HitPointState,
    RollMode,
    TargetKind,
    apply_damage,
    apply_healing,
    resolve_attack_roll,
)


class SpellCastMode(StrEnum):
    ATTACK = "attack"
    SAVE = "save"
    HEAL = "heal"
    UTILITY = "utility"


class SaveDamageMode(StrEnum):
    NONE = "none"
    HALF = "half"


@dataclass(frozen=True)
class SpellResolutionSpec:
    spell_ref: str
    cast_mode: SpellCastMode
    minimum_slot_level: int = 0
    attack_modifier: int | None = None
    save_dc: int | None = None
    save_damage_mode: SaveDamageMode = SaveDamageMode.NONE
    concentration: bool = False
    apply_effects: tuple[EffectSpec, ...] = ()

    def __post_init__(self) -> None:
        if not self.spell_ref.strip():
            raise ValueError("spell_ref cannot be blank")
        if not 0 <= self.minimum_slot_level <= 9:
            raise ValueError("minimum_slot_level must be between 0 and 9")
        if self.cast_mode is SpellCastMode.ATTACK and self.attack_modifier is None:
            raise ValueError("attack spells require attack_modifier")
        if self.cast_mode is SpellCastMode.SAVE and self.save_dc is None:
            raise ValueError("save spells require save_dc")


@dataclass(frozen=True)
class SpellTargetState:
    target_ref: str
    target_kind: TargetKind
    hp: HitPointState | None = None
    target_ac: int | None = None
    save_modifier: int | None = None
    death_saves: DeathSaveState | None = None


@dataclass(frozen=True)
class SpellCastRequest:
    caster_ref: str
    slot_level: int = 0
    attack_d20s: tuple[int, ...] = ()
    attack_mode: RollMode = RollMode.NORMAL
    save_d20: int | None = None
    damage_parts: tuple[DamageRollPart, ...] = ()
    healing_amount: int = 0


@dataclass(frozen=True)
class SpellResolution:
    remaining_slots: dict[int, int]
    target_hp: HitPointState | None
    target_death_saves: DeathSaveState | None
    applied_effects: tuple[ActiveEffect, ...]
    concentration_started: bool
    events: tuple[dict[str, object], ...]


def _half_damage(parts: Sequence[DamageRollPart]) -> tuple[DamageRollPart, ...]:
    # Saving-throw half damage applies to the aggregate instance. Re-express it
    # as one already-rolled amount so the P4-C HP pipeline remains authoritative.
    from app.domain.combat.resolution import DamageType

    total = sum(max(0, sum(part.dice) + part.flat_modifier) for part in parts)
    return (DamageRollPart(damage_type=DamageType.UNTYPED, flat_modifier=total // 2),)


def resolve_spell(
    *,
    spec: SpellResolutionSpec,
    request: SpellCastRequest,
    target: SpellTargetState | None,
    spell_slots: dict[int, int],
    effect_id_prefix: str = "spell-effect",
) -> SpellResolution:
    """Resolve one spell atomically from already-authoritative roll inputs.

    Structural, target, and resource validation completes before slot
    expenditure. The input slot map is never mutated, allowing the application
    layer to persist state and emitted semantic events in one transaction.
    """

    if not request.caster_ref.strip():
        raise ValueError("caster_ref cannot be blank")
    if request.slot_level < spec.minimum_slot_level:
        raise ValueError("slot level is below the spell minimum")
    if request.slot_level > 9:
        raise ValueError("slot level must be between 0 and 9")
    if spec.minimum_slot_level > 0 and request.slot_level == 0:
        raise ValueError("this spell requires a spell slot")
    if request.slot_level > 0 and int(spell_slots.get(request.slot_level, 0)) <= 0:
        raise ValueError(f"no level {request.slot_level} spell slot remains")

    if spec.cast_mode in {SpellCastMode.ATTACK, SpellCastMode.SAVE, SpellCastMode.HEAL} and target is None:
        raise ValueError("this spell requires a target")
    if spec.cast_mode is SpellCastMode.ATTACK:
        if target is None or target.target_ac is None or not request.attack_d20s:
            raise ValueError("attack spell requires target AC and attack roll")
    if spec.cast_mode is SpellCastMode.SAVE:
        if target is None or target.save_modifier is None or request.save_d20 is None:
            raise ValueError("save spell requires target save modifier and d20")
        if request.save_d20 < 1 or request.save_d20 > 20:
            raise ValueError("saving throw d20 must be between 1 and 20")
    if (
        spec.cast_mode in {SpellCastMode.ATTACK, SpellCastMode.SAVE}
        and request.damage_parts
        and (target is None or target.hp is None)
    ):
        raise ValueError("damaging spell target requires HP state")
    if spec.cast_mode is SpellCastMode.HEAL:
        if target is None or target.hp is None:
            raise ValueError("healing spell target requires HP state")
        if request.healing_amount < 0:
            raise ValueError("healing amount cannot be negative")

    remaining = dict(spell_slots)
    events: list[dict[str, object]] = []
    if request.slot_level > 0:
        remaining[request.slot_level] -= 1
        events.append(
            {"type": "resource_spent", "resource": "spell_slot", "level": request.slot_level, "amount": 1}
        )

    target_hp = target.hp if target is not None else None
    target_death_saves = target.death_saves if target is not None else None
    should_apply_effects = True

    if spec.cast_mode is SpellCastMode.ATTACK:
        assert target is not None and target.target_ac is not None and spec.attack_modifier is not None
        attack = resolve_attack_roll(
            d20_rolls=request.attack_d20s,
            modifier=spec.attack_modifier,
            target_ac=target.target_ac,
            mode=request.attack_mode,
        )
        events.append(
            {
                "type": "attack_roll",
                "spell_ref": spec.spell_ref,
                "d20": attack.selected_d20,
                "total": attack.total,
                "target_ac": attack.target_ac,
                "hit": attack.hit,
                "critical": attack.critical,
            }
        )
        should_apply_effects = attack.hit
        if attack.hit and request.damage_parts:
            assert target.hp is not None
            damage = apply_damage(
                target.hp,
                request.damage_parts,
                target_kind=target.target_kind,
                critical=attack.critical,
                death_saves=target.death_saves,
            )
            target_hp = damage.after
            target_death_saves = damage.death_saves
            events.append(
                {"type": "damage", "spell_ref": spec.spell_ref, "amount": damage.adjusted_total, "target_ref": target.target_ref}
            )

    elif spec.cast_mode is SpellCastMode.SAVE:
        assert target is not None and target.save_modifier is not None
        assert request.save_d20 is not None and spec.save_dc is not None
        total = request.save_d20 + target.save_modifier
        saved = total >= spec.save_dc
        events.append(
            {
                "type": "saving_throw",
                "spell_ref": spec.spell_ref,
                "d20": request.save_d20,
                "modifier": target.save_modifier,
                "total": total,
                "dc": spec.save_dc,
                "success": saved,
            }
        )
        should_apply_effects = not saved
        damage_parts = request.damage_parts
        if saved and spec.save_damage_mode is SaveDamageMode.NONE:
            damage_parts = ()
        elif saved and spec.save_damage_mode is SaveDamageMode.HALF:
            damage_parts = _half_damage(damage_parts)
        if damage_parts:
            assert target.hp is not None
            damage = apply_damage(
                target.hp,
                damage_parts,
                target_kind=target.target_kind,
                death_saves=target.death_saves,
            )
            target_hp = damage.after
            target_death_saves = damage.death_saves
            events.append(
                {"type": "damage", "spell_ref": spec.spell_ref, "amount": damage.adjusted_total, "target_ref": target.target_ref}
            )

    elif spec.cast_mode is SpellCastMode.HEAL:
        assert target is not None and target.hp is not None
        healing = apply_healing(
            target.hp,
            request.healing_amount,
            target_kind=target.target_kind,
            death_saves=target.death_saves,
        )
        target_hp = healing.after
        target_death_saves = healing.death_saves
        events.append(
            {
                "type": "heal",
                "spell_ref": spec.spell_ref,
                "requested": request.healing_amount,
                "restored": healing.restored,
                "target_ref": target.target_ref,
            }
        )

    effects: list[ActiveEffect] = []
    if should_apply_effects:
        for index, effect_spec in enumerate(spec.apply_effects, start=1):
            effect = ActiveEffect.create(
                f"{effect_id_prefix}:{index}",
                effect_spec,
                concentration_owner_ref=request.caster_ref if spec.concentration else None,
            )
            effects.append(effect)
            events.append(
                {
                    "type": "condition_applied" if effect_spec.effect_type == "condition" else "effect_applied",
                    "effect_id": effect.effect_id,
                    "tag": effect_spec.tag,
                    "source_ref": effect_spec.source_ref,
                }
            )

    if spec.concentration:
        events.append(
            {
                "type": "concentration_started",
                "source_ref": spec.spell_ref,
                "effect_ids": [effect.effect_id for effect in effects],
            }
        )

    return SpellResolution(
        remaining_slots=remaining,
        target_hp=target_hp,
        target_death_saves=target_death_saves,
        applied_effects=tuple(effects),
        concentration_started=spec.concentration,
        events=tuple(events),
    )
