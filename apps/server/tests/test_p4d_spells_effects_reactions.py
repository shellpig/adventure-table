from __future__ import annotations

import pytest

from app.domain.character.character_state import CharacterRuntimeState
from app.domain.combat.effect_resolver import (
    CONDITION_SEMANTICS,
    ActiveEffect,
    Condition,
    Concentration,
    DurationKind,
    DurationSpec,
    EffectSpec,
    concentration_dc,
    expire_effects,
    resolve_concentration_damage,
    start_concentration,
)
from app.domain.combat.reaction_service import (
    ReactionKind,
    create_ready_state,
    expire_ready_at_turn_start,
    expire_reaction_window,
    open_reaction_window,
    resolve_reaction,
)
from app.domain.combat.resolution import DamageRollPart, DamageType, HitPointState, TargetKind
from app.domain.combat.spell_resolver import (
    SaveDamageMode,
    SpellCastMode,
    SpellCastRequest,
    SpellResolutionSpec,
    SpellTargetState,
    resolve_spell,
)


def _fire_damage(*values: int) -> tuple[DamageRollPart, ...]:
    return (DamageRollPart(damage_type=DamageType.FIRE, dice=values),)


def test_p4d_attack_spell_spends_slot_and_applies_damage() -> None:
    spec = SpellResolutionSpec(
        spell_ref="srd:spell:scorching-ray",
        cast_mode=SpellCastMode.ATTACK,
        minimum_slot_level=2,
        attack_modifier=6,
    )
    target = SpellTargetState(
        target_ref="monster:goblin:1",
        target_kind=TargetKind.MONSTER,
        hp=HitPointState(current_hp=20, max_hp=20),
        target_ac=13,
    )
    result = resolve_spell(
        spec=spec,
        request=SpellCastRequest(
            caster_ref="character:1",
            slot_level=2,
            attack_d20s=(12,),
            damage_parts=_fire_damage(4, 5),
        ),
        target=target,
        spell_slots={2: 1},
    )
    assert result.remaining_slots == {2: 0}
    assert result.target_hp == HitPointState(current_hp=11, max_hp=20)
    assert [event["type"] for event in result.events][:3] == [
        "resource_spent",
        "attack_roll",
        "damage",
    ]


def test_p4d_invalid_attack_fails_before_slot_spend() -> None:
    spec = SpellResolutionSpec(
        spell_ref="srd:spell:scorching-ray",
        cast_mode=SpellCastMode.ATTACK,
        minimum_slot_level=2,
        attack_modifier=6,
    )
    slots = {2: 1}
    with pytest.raises(ValueError, match="target AC"):
        resolve_spell(
            spec=spec,
            request=SpellCastRequest(caster_ref="character:1", slot_level=2, attack_d20s=(12,)),
            target=SpellTargetState(target_ref="monster:1", target_kind=TargetKind.MONSTER),
            spell_slots=slots,
        )
    assert slots == {2: 1}


def test_p4d_insufficient_slot_fails_without_mutating_input() -> None:
    spec = SpellResolutionSpec(
        spell_ref="srd:spell:cure-wounds",
        cast_mode=SpellCastMode.HEAL,
        minimum_slot_level=1,
    )
    slots = {1: 0}
    with pytest.raises(ValueError, match="no level 1"):
        resolve_spell(
            spec=spec,
            request=SpellCastRequest(caster_ref="character:1", slot_level=1, healing_amount=5),
            target=SpellTargetState(
                target_ref="character:2",
                target_kind=TargetKind.CHARACTER,
                hp=HitPointState(current_hp=5, max_hp=10),
            ),
            spell_slots=slots,
        )
    assert slots == {1: 0}


def test_p4d_save_spell_and_half_damage() -> None:
    spec = SpellResolutionSpec(
        spell_ref="srd:spell:fireball",
        cast_mode=SpellCastMode.SAVE,
        minimum_slot_level=3,
        save_dc=15,
        save_damage_mode=SaveDamageMode.HALF,
    )
    result = resolve_spell(
        spec=spec,
        request=SpellCastRequest(
            caster_ref="character:1",
            slot_level=3,
            save_d20=14,
            damage_parts=_fire_damage(8, 8),
        ),
        target=SpellTargetState(
            target_ref="monster:1",
            target_kind=TargetKind.MONSTER,
            hp=HitPointState(current_hp=30, max_hp=30),
            save_modifier=2,
        ),
        spell_slots={3: 1},
    )
    assert result.target_hp == HitPointState(current_hp=22, max_hp=30)
    assert any(
        event["type"] == "saving_throw" and event["success"] is True
        for event in result.events
    )


def test_p4d_healing_caps_at_max_hp() -> None:
    spec = SpellResolutionSpec(
        spell_ref="srd:spell:cure-wounds",
        cast_mode=SpellCastMode.HEAL,
        minimum_slot_level=1,
    )
    result = resolve_spell(
        spec=spec,
        request=SpellCastRequest(caster_ref="character:1", slot_level=1, healing_amount=9),
        target=SpellTargetState(
            target_ref="character:2",
            target_kind=TargetKind.CHARACTER,
            hp=HitPointState(current_hp=8, max_hp=12),
        ),
        spell_slots={1: 2},
    )
    assert result.target_hp == HitPointState(current_hp=12, max_hp=12)
    heal_event = next(event for event in result.events if event["type"] == "heal")
    assert heal_event["restored"] == 4


def test_p4d_concentration_is_single_and_linked_effects_cleanup() -> None:
    old_spec = EffectSpec(
        "condition", "restrained", DurationSpec(DurationKind.ROUNDS, 10), "spell:old"
    )
    new_spec = EffectSpec(
        "condition", "frightened", DurationSpec(DurationKind.ROUNDS, 10), "spell:new"
    )
    old = ActiveEffect.create("old:1", old_spec, concentration_owner_ref="character:1")
    new = ActiveEffect.create("new:1", new_spec, concentration_owner_ref="character:1")
    transition = start_concentration(
        owner_ref="character:1",
        source_ref="spell:new",
        effects=(old, new),
        current=Concentration("character:1", "spell:old", ("old:1",)),
    )
    assert transition.removed_effect_ids == ("old:1",)
    assert tuple(effect.effect_id for effect in transition.effects) == ("new:1",)
    assert transition.concentration is not None
    assert transition.concentration.effect_ids == ("new:1",)


def test_p4d_concentration_dc_and_failed_save_end_concentration() -> None:
    assert concentration_dc(1) == 10
    assert concentration_dc(21) == 10
    assert concentration_dc(22) == 11
    spec = EffectSpec(
        "condition", "restrained", DurationSpec(DurationKind.ROUNDS, 10), "spell:web"
    )
    effect = ActiveEffect.create("web:1", spec, concentration_owner_ref="character:1")
    transition = resolve_concentration_damage(
        current=Concentration("character:1", "spell:web", ("web:1",)),
        effects=(effect,),
        damage_taken=24,
        d20=5,
        constitution_save_modifier=3,
    )
    assert transition.concentration is None
    assert transition.effects == ()
    assert [event["type"] for event in transition.events] == [
        "concentration_check",
        "concentration_ended",
    ]


def test_p4d_condition_semantics_cover_minimum_required_conditions() -> None:
    assert CONDITION_SEMANTICS[Condition.RESTRAINED].speed_zero
    assert CONDITION_SEMANTICS[Condition.RESTRAINED].dexterity_saves_disadvantage
    assert CONDITION_SEMANTICS[Condition.FRIGHTENED].cannot_move_closer_to_source
    assert CONDITION_SEMANTICS[Condition.STUNNED].blocks_actions
    assert CONDITION_SEMANTICS[Condition.STUNNED].blocks_reactions
    assert CONDITION_SEMANTICS[Condition.STUNNED].auto_fail_strength_saves
    assert CONDITION_SEMANTICS[Condition.STUNNED].auto_fail_dexterity_saves


def test_p4d_effect_expiry_is_deterministic() -> None:
    spec = EffectSpec(
        "buff", "one-round", DurationSpec(DurationKind.ROUNDS, 2), "feature:test"
    )
    effect = ActiveEffect.create("effect:1", spec)
    first, expired = expire_effects((effect,), boundary="round")
    assert expired == () and first[0].remaining_rounds == 1
    second, expired = expire_effects(first, boundary="round")
    assert second == () and expired == ("effect:1",)


def test_p4d_reaction_window_is_owned_consumed_once_and_timeout_safe() -> None:
    window = open_reaction_window(
        window_id="rw:1",
        entry_id="entry:2",
        kind=ReactionKind.SHIELD,
        reason="incoming attack",
        source_entry_id="entry:1",
    )
    with pytest.raises(PermissionError):
        resolve_reaction(
            window=window,
            actor_entry_id="entry:3",
            reaction_available=True,
            accept=True,
        )
    accepted = resolve_reaction(
        window=window,
        actor_entry_id="entry:2",
        reaction_available=True,
        accept=True,
    )
    assert accepted.reaction_available is False
    with pytest.raises(ValueError, match="not open"):
        resolve_reaction(
            window=accepted.window,
            actor_entry_id="entry:2",
            reaction_available=False,
            accept=True,
        )

    timeout = expire_reaction_window(
        open_reaction_window(
            window_id="rw:2",
            entry_id="entry:2",
            kind=ReactionKind.COUNTERSPELL,
            reason="spell cast",
        )
    )
    assert timeout.window.status == "expired"
    assert timeout.events[0]["type"] == "reaction_expired"


def test_p4d_ready_expires_on_next_owner_turn_without_refund() -> None:
    ready = create_ready_state(
        owner_entry_id="entry:1",
        trigger="enemy_enters_reach",
        response="attack",
        created_turn_key="r1:e1",
        expires_at_owner_turn_key="r2:e1",
        spell_ref="srd:spell:hold-person",
        spell_slot_level=2,
        concentration_started=True,
    )
    same, events = expire_ready_at_turn_start(ready=ready, owner_turn_key="r1:e2")
    assert same == ready and events == ()
    expired, events = expire_ready_at_turn_start(ready=ready, owner_turn_key="r2:e1")
    assert expired is None
    assert events[0]["refund"] is False


def test_p4d_character_state_restores_v1_and_writes_v2() -> None:
    legacy = CharacterRuntimeState.from_json({"current_hp": 7, "max_hp": 10})
    assert legacy.reaction_available is True
    persisted = legacy.to_json()
    assert persisted["schema_version"] == 2
    assert persisted["health"]["current_hp"] == 7
    assert persisted["status"]["conditions"] == []
    assert persisted["combat"]["ready"] is None


def test_p4d_character_state_v2_roundtrip() -> None:
    payload = {
        "schema_version": 2,
        "health": {"current_hp": 6, "max_hp": 12, "temp_hp": 3},
        "status": {
            "conditions": ["restrained"],
            "concentration": {
                "source_ref": "spell:web",
                "effect_ids": ["web:1"],
                "started_round": 2,
            },
            "temporary_effects": [],
        },
        "combat": {"reaction_available": False, "ready": {"trigger": "door_opens"}},
        "resources": {"spell_slots": {"1": 2, "2": 1}},
    }
    state = CharacterRuntimeState.from_json(payload)
    assert state.to_json() == payload
