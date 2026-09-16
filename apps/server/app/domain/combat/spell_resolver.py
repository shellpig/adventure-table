from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Sequence

from app.domain.character.schemas import (
    CharacterConcentrationState,
    CharacterState,
    PersistentTemporaryEffect,
    TemporaryEffectModifier,
)
from app.domain.combat.effect_resolver import DurationKind, EffectSpec
from app.domain.combat.resolution import (
    DamageOutcome,
    DamageRollPart,
    DamageType,
    DeathSaveState,
    HitPointState,
    RollMode,
    TargetKind,
    apply_damage,
    apply_healing,
    raw_damage_by_type,
    resolve_attack_roll,
)
from app.domain.combat.spell_resources import (
    CharacterSpellAuthorization,
    MonsterSpellSource,
    spend_character_spell,
    spend_monster_spell,
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
    resistances: tuple[DamageType, ...] = ()
    immunities: tuple[DamageType, ...] = ()
    vulnerabilities: tuple[DamageType, ...] = ()


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
    character_state: CharacterState
    target_hp: HitPointState | None
    target_death_saves: DeathSaveState | None
    applied_effects: tuple[PersistentTemporaryEffect, ...]
    concentration_started: bool
    events: tuple[dict[str, object], ...]
    damage: DamageOutcome | None = None
    replaced_concentration_effect_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MonsterSpellResolution:
    resources: dict[str, object]
    target_hp: HitPointState | None
    target_death_saves: DeathSaveState | None
    applied_effects: tuple[PersistentTemporaryEffect, ...]
    events: tuple[dict[str, object], ...]
    damage: DamageOutcome | None = None


def half_damage_parts(parts: Sequence[DamageRollPart]) -> tuple[DamageRollPart, ...]:
    """Apply save-for-half before affinity while retaining each damage type."""

    raw = raw_damage_by_type(parts)
    return tuple(
        DamageRollPart(damage_type=DamageType(damage_type), flat_modifier=amount // 2)
        for damage_type, amount in raw.items()
        if amount > 0
    )


def _persistent_effect(effect_id: str, spec: EffectSpec, *, concentration: bool) -> PersistentTemporaryEffect:
    if spec.duration.kind is DurationKind.UNTIL_SHORT_REST:
        duration = "short_rest"
    elif spec.duration.kind is DurationKind.UNTIL_LONG_REST:
        duration = "long_rest"
    elif spec.duration.kind is DurationKind.UNTIL_CONCENTRATION_ENDS or concentration:
        duration = "concentration"
    elif spec.duration.kind is DurationKind.MANUAL:
        duration = "manual"
    else:
        # Round/turn lifetime is combat-local timing state and must not be
        # silently persisted as a different duration in CharacterState.
        raise ValueError("round/turn spell effects require durable combat timing persistence")
    return PersistentTemporaryEffect(
        effect_id=effect_id,
        source_ref=spec.source_ref,
        tag=spec.tag,
        duration=duration,
        modifiers=tuple(
            TemporaryEffectModifier(
                scope=modifier.scope.value,
                mode=modifier.mode.value,
                value=modifier.value,
                target=modifier.target,
            )
            for modifier in spec.modifiers
        ),
        note=spec.note,
    )


def _validate_resolution_inputs(
    *, spec: SpellResolutionSpec, request: SpellCastRequest, target: SpellTargetState | None
) -> None:
    if not request.caster_ref.strip():
        raise ValueError("caster_ref cannot be blank")
    if request.slot_level < spec.minimum_slot_level:
        raise ValueError("slot level is below the spell minimum")
    if request.slot_level > 9:
        raise ValueError("slot level must be between 0 and 9")
    if spec.minimum_slot_level > 0 and request.slot_level == 0:
        raise ValueError("this spell requires a spell slot")
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


def _resolve_semantics(
    *,
    spec: SpellResolutionSpec,
    request: SpellCastRequest,
    target: SpellTargetState | None,
    effect_id_prefix: str,
    resource_event: dict[str, object] | None,
) -> tuple[
    HitPointState | None,
    DeathSaveState | None,
    tuple[PersistentTemporaryEffect, ...],
    tuple[dict[str, object], ...],
    DamageOutcome | None,
]:
    events: list[dict[str, object]] = []
    if resource_event is not None:
        events.append(resource_event)
    target_hp = target.hp if target is not None else None
    target_death_saves = target.death_saves if target is not None else None
    should_apply_effects = True
    damage: DamageOutcome | None = None
    affinities = (
        {
            "resistances": target.resistances,
            "immunities": target.immunities,
            "vulnerabilities": target.vulnerabilities,
        }
        if target is not None
        else {}
    )

    if spec.cast_mode is SpellCastMode.ATTACK:
        assert target is not None and target.target_ac is not None and spec.attack_modifier is not None
        attack = resolve_attack_roll(
            d20_rolls=request.attack_d20s,
            modifier=spec.attack_modifier,
            target_ac=target.target_ac,
            mode=request.attack_mode,
        )
        events.append({
            "type": "attack_roll", "spell_ref": spec.spell_ref,
            "d20": attack.selected_d20, "total": attack.total,
            "target_ac": attack.target_ac, "hit": attack.hit, "critical": attack.critical,
        })
        should_apply_effects = attack.hit
        if attack.hit and request.damage_parts:
            assert target.hp is not None
            damage = apply_damage(
                target.hp, request.damage_parts, target_kind=target.target_kind,
                critical=attack.critical, death_saves=target.death_saves, **affinities,
            )
            target_hp, target_death_saves = damage.after, damage.death_saves
            events.append({"type": "damage", "spell_ref": spec.spell_ref, "amount": damage.adjusted_total, "target_ref": target.target_ref})
    elif spec.cast_mode is SpellCastMode.SAVE:
        assert target is not None and target.save_modifier is not None
        assert request.save_d20 is not None and spec.save_dc is not None
        total = request.save_d20 + target.save_modifier
        saved = total >= spec.save_dc
        events.append({
            "type": "saving_throw", "spell_ref": spec.spell_ref,
            "d20": request.save_d20, "modifier": target.save_modifier,
            "total": total, "dc": spec.save_dc, "success": saved,
        })
        should_apply_effects = not saved
        damage_parts = request.damage_parts
        if saved and spec.save_damage_mode is SaveDamageMode.NONE:
            damage_parts = ()
        elif saved and spec.save_damage_mode is SaveDamageMode.HALF:
            damage_parts = half_damage_parts(damage_parts)
        if damage_parts:
            assert target.hp is not None
            damage = apply_damage(
                target.hp, damage_parts, target_kind=target.target_kind,
                death_saves=target.death_saves, **affinities,
            )
            target_hp, target_death_saves = damage.after, damage.death_saves
            events.append({"type": "damage", "spell_ref": spec.spell_ref, "amount": damage.adjusted_total, "target_ref": target.target_ref})
    elif spec.cast_mode is SpellCastMode.HEAL:
        assert target is not None and target.hp is not None
        healing = apply_healing(target.hp, request.healing_amount, target_kind=target.target_kind, death_saves=target.death_saves)
        target_hp, target_death_saves = healing.after, healing.death_saves
        events.append({
            "type": "heal", "spell_ref": spec.spell_ref,
            "requested": request.healing_amount, "restored": healing.restored,
            "target_ref": target.target_ref,
        })

    effects: list[PersistentTemporaryEffect] = []
    if should_apply_effects:
        for index, effect_spec in enumerate(spec.apply_effects, start=1):
            effect = _persistent_effect(f"{effect_id_prefix}:{index}", effect_spec, concentration=spec.concentration)
            effects.append(effect)
            events.append({
                "type": "condition_applied" if effect_spec.effect_type == "condition" else "effect_applied",
                "effect_id": effect.effect_id, "tag": effect.tag, "source_ref": effect.source_ref,
            })
    return target_hp, target_death_saves, tuple(effects), tuple(events), damage


def resolve_spell(
    *,
    spec: SpellResolutionSpec,
    request: SpellCastRequest,
    target: SpellTargetState | None,
    state: CharacterState,
    authorization: CharacterSpellAuthorization,
    effect_id_prefix: str = "spell-effect",
    effects_target: Literal["caster", "target"] = "caster",
) -> SpellResolution:
    """Resolve one character spell through the canonical CharacterState resource layer.

    ``effects_target="target"`` keeps ``applied_effects`` out of the caster's
    ``temporary_effects`` so the persistence layer can attach them to the
    creature that was actually targeted; the caster still owns the
    concentration pointer to those effect ids.
    """

    _validate_resolution_inputs(spec=spec, request=request, target=target)
    if authorization.spell_ref != spec.spell_ref or authorization.slot_level != request.slot_level:
        raise ValueError("spell authorization does not match cast request")
    if effects_target == "target" and target is None:
        raise ValueError("effects_target='target' requires a target")

    spend = spend_character_spell(state=state, authorization=authorization)
    target_hp, target_death_saves, effects, events, damage = _resolve_semantics(
        spec=spec, request=request, target=target, effect_id_prefix=effect_id_prefix,
        resource_event=spend.event,
    )
    next_state = spend.state
    caster_effects = effects if effects_target == "caster" else ()
    removed_ids: set[str] = set()
    if spec.concentration:
        previous = next_state.concentration
        removed_ids = set(previous.effect_ids) if previous is not None else set()
        kept = [effect for effect in next_state.temporary_effects if effect.effect_id not in removed_ids]
        kept.extend(caster_effects)
        next_state = next_state.model_copy(update={
            "temporary_effects": kept,
            "concentration": CharacterConcentrationState(
                source_ref=spec.spell_ref,
                effect_ids=tuple(effect.effect_id for effect in effects),
            ),
        }, deep=True)
        concentration_events: list[dict[str, object]] = []
        if previous is not None:
            concentration_events.append({
                "type": "concentration_ended", "source_ref": previous.source_ref,
                "reason": "replaced", "removed_effect_ids": sorted(removed_ids),
            })
        concentration_events.append({
            "type": "concentration_started", "source_ref": spec.spell_ref,
            "effect_ids": [effect.effect_id for effect in effects],
        })
        events = (*events, *concentration_events)
    elif caster_effects:
        next_state = next_state.model_copy(
            update={"temporary_effects": [*next_state.temporary_effects, *caster_effects]}, deep=True
        )

    return SpellResolution(
        character_state=next_state,
        target_hp=target_hp,
        target_death_saves=target_death_saves,
        applied_effects=effects,
        concentration_started=spec.concentration,
        events=events,
        damage=damage,
        replaced_concentration_effect_ids=tuple(sorted(removed_ids)),
    )


def resolve_monster_spell(
    *,
    spec: SpellResolutionSpec,
    request: SpellCastRequest,
    target: SpellTargetState | None,
    resources: dict[str, object],
    source: MonsterSpellSource,
    effect_id_prefix: str = "spell-effect",
) -> MonsterSpellResolution:
    """Resolve one monster spell through the canonical monster resource layer."""

    _validate_resolution_inputs(spec=spec, request=request, target=target)
    if source.spell_ref != spec.spell_ref:
        raise ValueError("monster spell source does not match cast request")
    spend = spend_monster_spell(resources=resources, source=source)
    target_hp, target_death_saves, effects, events, damage = _resolve_semantics(
        spec=spec, request=request, target=target, effect_id_prefix=effect_id_prefix,
        resource_event=spend.event,
    )
    return MonsterSpellResolution(
        resources=dict(spend.resources),
        target_hp=target_hp,
        target_death_saves=target_death_saves,
        applied_effects=effects,
        events=events,
        damage=damage,
    )
