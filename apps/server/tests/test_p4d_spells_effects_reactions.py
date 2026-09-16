from __future__ import annotations

import pytest

from app.domain.character.schemas import (
    AbilityScores,
    CharacterBuild,
    CharacterConcentrationState,
    CharacterState,
    PersistentTemporaryEffect,
    PreparedSpellSelection,
    ResourceCounter,
    SpellAccessEntry,
    SpellResourcePool,
    SpellSlotCapacity,
    SpellcastingProfile,
    TemporaryEffectModifier,
)
from app.domain.combat.aoe_adjudication import (
    AoeTargetState,
    confirm_aoe,
    propose_aoe,
    resolve_aoe_save_spell,
)
from app.domain.combat.effect_resolver import (
    CONDITION_SEMANTICS,
    ActiveEffect,
    Condition,
    Concentration,
    DurationKind,
    DurationSpec,
    EffectSpec,
    ModifierMode,
    ModifierScope,
    TypedModifier,
    change_exhaustion,
    concentration_dc,
    exhaustion_semantics,
    expire_effects,
    resolve_concentration_damage,
    start_concentration,
)
from app.domain.combat.reaction_service import (
    ReactionKind,
    ReactionWindow,
    ReadyState,
    create_ready_state,
    expire_ready_at_turn_start,
    expire_reaction_window,
    open_opportunity_attack_window,
    open_reaction_window,
    resolve_reaction,
    spend_legendary_action,
)
from app.domain.combat.resolution import DamageRollPart, DamageType, HitPointState, TargetKind
from app.domain.combat.spell_resolver import (
    SaveDamageMode,
    SpellCastMode,
    SpellCastRequest,
    SpellResolutionSpec,
    SpellTargetState,
    half_damage_parts,
    resolve_spell,
)
from app.domain.combat.spell_resources import (
    SpellResourceKind,
    authorize_character_spell,
    resolve_monster_spell_source,
    spend_character_spell,
)
from app.domain.rules.spellcasting import pact_resource_key


def _damage(damage_type: DamageType, *values: int) -> DamageRollPart:
    return DamageRollPart(damage_type=damage_type, dice=values)


def _caster_build_and_state() -> tuple[CharacterBuild, CharacterState]:
    wizard = "srd5.1:class:wizard"
    warlock = "srd5.1:class:warlock"
    magic_missile = "srd5.1:spell:magic-missile"
    hex_spell = "srd5.1:spell:hex"
    build = CharacterBuild(
        race_ref="srd5.1:race:human",
        character_level=2,
        class_progression=(wizard, warlock),
        ability_scores=AbilityScores(
            strength=8,
            dexterity=14,
            constitution=14,
            intelligence=16,
            wisdom=10,
            charisma=16,
        ),
        hp_progression=(8, 7),
        spellcasting_profiles=(
            SpellcastingProfile(
                profile_id="wizard",
                source_type="class",
                source_key=wizard,
                class_ref=wizard,
                ability="intelligence",
                access_model="prepared",
                resource_pool_type="normal_multiclass_slots",
                max_spell_level=1,
                prepared_limit=2,
            ),
            SpellcastingProfile(
                profile_id="warlock",
                source_type="class",
                source_key=warlock,
                class_ref=warlock,
                ability="charisma",
                access_model="known",
                resource_pool_type="pact_magic",
                max_spell_level=1,
            ),
        ),
        spell_access_entries=(
            SpellAccessEntry(
                entry_id="wizard:mm",
                spell_key=magic_missile,
                source_type="class",
                source_key=wizard,
                access_type="known",
                casting_ability="intelligence",
            ),
            SpellAccessEntry(
                entry_id="warlock:hex",
                spell_key=hex_spell,
                source_type="class",
                source_key=warlock,
                access_type="known",
                casting_ability="charisma",
            ),
        ),
        spell_resource_pools=(
            SpellResourcePool(
                pool_id="normal_multiclass",
                pool_type="normal_multiclass_slots",
                slots=(SpellSlotCapacity(level=1, capacity=2), SpellSlotCapacity(level=2, capacity=1)),
            ),
            SpellResourcePool(
                pool_id="pact_magic:warlock",
                pool_type="pact_magic",
                source_profile_id="warlock",
                slots=(SpellSlotCapacity(level=1, capacity=1),),
            ),
        ),
    )
    pact_key = pact_resource_key("pact_magic:warlock", 1)
    state = CharacterState(
        current_hp=15,
        prepared_spells=[
            PreparedSpellSelection(spell_key=magic_missile, source_profile_id="wizard", source_access_entry_id="wizard:mm")
        ],
        spell_slots={
            1: ResourceCounter(used=0, remaining=2),
            2: ResourceCounter(used=0, remaining=1),
        },
        resources={pact_key: ResourceCounter(used=0, remaining=1)},
    )
    return build, state


def _fireball_caster_build_and_state() -> tuple[CharacterBuild, CharacterState]:
    build, state = _caster_build_and_state()
    fireball = "srd5.1:spell:fireball"
    wizard = build.spellcasting_profiles[0].model_copy(update={"max_spell_level": 3})
    normal_pool = build.spell_resource_pools[0].model_copy(
        update={
            "slots": (
                *build.spell_resource_pools[0].slots,
                SpellSlotCapacity(level=3, capacity=1),
            )
        }
    )
    fireball_access = SpellAccessEntry(
        entry_id="wizard:fireball",
        spell_key=fireball,
        source_type="class",
        source_key=wizard.source_key,
        access_type="known",
        casting_ability="intelligence",
    )
    next_build = build.model_copy(
        update={
            "spellcasting_profiles": (wizard, *build.spellcasting_profiles[1:]),
            "spell_access_entries": (*build.spell_access_entries, fireball_access),
            "spell_resource_pools": (normal_pool, *build.spell_resource_pools[1:]),
        },
        deep=True,
    )
    next_state = state.model_copy(
        update={
            "prepared_spells": [
                *state.prepared_spells,
                PreparedSpellSelection(
                    spell_key=fireball,
                    source_profile_id="wizard",
                    source_access_entry_id="wizard:fireball",
                ),
            ],
            "spell_slots": {
                **state.spell_slots,
                3: ResourceCounter(used=0, remaining=1),
            },
        },
        deep=True,
    )
    return next_build, next_state


# D.0 — canonical Character Current State / backwards compatibility.
def test_p4d_d0_character_state_additive_defaults_and_roundtrip() -> None:
    legacy = CharacterState.model_validate({"current_hp": 7})
    assert legacy.concentration is None
    assert legacy.exhaustion_level == 0
    assert legacy.death_saves.successes == 0
    assert legacy.temporary_effects == []
    assert "schema_version" not in legacy.model_dump()

    state = legacy.model_copy(
        update={
            "concentration": CharacterConcentrationState(
                source_ref="srd5.1:spell:web", effect_ids=("web:1",)
            ),
            "exhaustion_level": 2,
            "temporary_effects": [
                PersistentTemporaryEffect(
                    effect_id="bless:1",
                    source_ref="srd5.1:spell:bless",
                    tag="bless",
                    modifiers=(TemporaryEffectModifier(scope="save", mode="bonus", value=1),),
                )
            ],
        }
    )
    restored = CharacterState.model_validate(state.model_dump(mode="json"))
    assert restored == state


def test_p4d_d0_shared_state_rejects_duplicate_effect_ids() -> None:
    effect = PersistentTemporaryEffect(effect_id="same", tag="test")
    with pytest.raises(ValueError, match="temporary effect ids"):
        CharacterState(current_hp=1, temporary_effects=[effect, effect])


# D.1 — source-aware spell eligibility / resource pools.
def test_p4d_d1_prepared_normal_slot_spend_and_upcast() -> None:
    build, state = _caster_build_and_state()
    authorization = authorize_character_spell(
        build=build,
        state=state,
        profile_id="wizard",
        spell_ref="srd5.1:spell:magic-missile",
        spell_level=1,
        slot_level=2,
    )
    assert authorization.resource_kind is SpellResourceKind.NORMAL_SLOT
    spent = spend_character_spell(state=state, authorization=authorization)
    assert state.spell_slots[2].remaining == 1
    assert spent.state.spell_slots[2] == ResourceCounter(used=1, remaining=0)


def test_p4d_d1_known_pact_magic_stays_separate_from_normal_slots() -> None:
    build, state = _caster_build_and_state()
    authorization = authorize_character_spell(
        build=build,
        state=state,
        profile_id="warlock",
        spell_ref="srd5.1:spell:hex",
        spell_level=1,
        slot_level=1,
    )
    assert authorization.resource_kind is SpellResourceKind.PACT_SLOT
    spent = spend_character_spell(state=state, authorization=authorization)
    key = pact_resource_key("pact_magic:warlock", 1)
    assert spent.state.resources[key] == ResourceCounter(used=1, remaining=0)
    assert spent.state.spell_slots[1] == state.spell_slots[1]
    with pytest.raises(ValueError, match="Pact Magic slot remains"):
        spend_character_spell(state=spent.state, authorization=authorization)


def test_p4d_d1_unprepared_spell_fails_before_resource_spend() -> None:
    build, state = _caster_build_and_state()
    unprepared = state.model_copy(update={"prepared_spells": []}, deep=True)
    with pytest.raises(ValueError, match="not prepared"):
        authorize_character_spell(
            build=build,
            state=unprepared,
            profile_id="wizard",
            spell_ref="srd5.1:spell:magic-missile",
            spell_level=1,
            slot_level=1,
        )
    assert unprepared.spell_slots[1] == ResourceCounter(used=0, remaining=2)


def test_p4d_d1_monster_spell_source_uses_p4a_snapshot_and_live_resource() -> None:
    source = resolve_monster_spell_source(
        rules_snapshot={
            "traits": [
                {
                    "spellcasting": {
                        "modifier": 7,
                        "dc": 15,
                        "slots": {"3": 3},
                        "spells": [
                            {
                                "name": "Fireball",
                                "url": "/api/2014/spells/fireball",
                            }
                        ],
                    }
                }
            ]
        },
        resources={"spell_slot:3": 1},
        spell_ref="srd5.1:spell:fireball",
        spell_level=3,
        slot_level=3,
    )
    assert source.attack_bonus == 7
    assert source.save_dc == 15
    assert source.resource_key == "spell_slot:3"


def test_p4d_d1_save_half_retains_damage_types() -> None:
    parts = (_damage(DamageType.FIRE, 5, 4), _damage(DamageType.COLD, 3, 2))
    halved = half_damage_parts(parts)
    assert [(part.damage_type, part.flat_modifier) for part in halved] == [
        (DamageType.FIRE, 4),
        (DamageType.COLD, 2),
    ]


# Existing unified single-target spell resolver remains the semantic core.
def test_p4d_single_target_attack_and_heal_resolution() -> None:
    attack = resolve_spell(
        spec=SpellResolutionSpec(
            spell_ref="srd5.1:spell:scorching-ray",
            cast_mode=SpellCastMode.ATTACK,
            minimum_slot_level=2,
            attack_modifier=6,
        ),
        request=SpellCastRequest(
            caster_ref="character:1",
            slot_level=2,
            attack_d20s=(12,),
            damage_parts=(_damage(DamageType.FIRE, 4, 5),),
        ),
        target=SpellTargetState(
            target_ref="monster:1",
            target_kind=TargetKind.MONSTER,
            hp=HitPointState(current_hp=20, max_hp=20),
            target_ac=13,
        ),
        spell_slots={2: 1},
    )
    assert attack.target_hp == HitPointState(current_hp=11, max_hp=20)
    assert attack.remaining_slots == {2: 0}

    healed = resolve_spell(
        spec=SpellResolutionSpec(
            spell_ref="srd5.1:spell:cure-wounds",
            cast_mode=SpellCastMode.HEAL,
            minimum_slot_level=1,
        ),
        request=SpellCastRequest(caster_ref="character:1", slot_level=1, healing_amount=9),
        target=SpellTargetState(
            target_ref="character:2",
            target_kind=TargetKind.CHARACTER,
            hp=HitPointState(current_hp=8, max_hp=12),
        ),
        spell_slots={1: 1},
    )
    assert healed.target_hp == HitPointState(current_hp=12, max_hp=12)


# D.2 — identity-only AoE + DM-confirmed affected set + one canonical resource spend.
def test_p4d_d2_aoe_requires_confirmation_and_resolves_each_confirmed_target_once() -> None:
    build, state = _fireball_caster_build_and_state()
    authorization = authorize_character_spell(
        build=build,
        state=state,
        profile_id="wizard",
        spell_ref="srd5.1:spell:fireball",
        spell_level=3,
        slot_level=3,
    )
    proposed = propose_aoe(command_id="cast:1", acting_entry_id="caster", target_ids=("a", "b", "c"))
    assert "radius" not in proposed.to_payload()
    confirmed = confirm_aoe(proposed, confirmed_target_ids=("a", "c"))
    spec = SpellResolutionSpec(
        spell_ref="srd5.1:spell:fireball",
        cast_mode=SpellCastMode.SAVE,
        minimum_slot_level=3,
        save_dc=15,
        save_damage_mode=SaveDamageMode.HALF,
    )
    result = resolve_aoe_save_spell(
        adjudication=confirmed,
        spec=spec,
        state=state,
        authorization=authorization,
        targets={
            "a": AoeTargetState("a", TargetKind.MONSTER, HitPointState(30, 30), 2),
            "c": AoeTargetState("c", TargetKind.MONSTER, HitPointState(30, 30), 5),
        },
        save_d20s={"a": 5, "c": 12},
        damage_parts=(_damage(DamageType.FIRE, 8, 8),),
    )
    assert result.character_state is not None
    assert state.spell_slots[3] == ResourceCounter(used=0, remaining=1)
    assert result.character_state.spell_slots[3] == ResourceCounter(used=1, remaining=0)
    assert result.adjudication.status == "resolved"
    assert [(row.entry_id, row.saved, row.damage_taken) for row in result.outcomes] == [
        ("a", False, 16),
        ("c", True, 8),
    ]


# D.3/D.4 — full 2014 conditions, effects, exhaustion, concentration.
def test_p4d_d3_all_2014_conditions_have_semantics() -> None:
    assert len(Condition) == 14
    assert set(CONDITION_SEMANTICS) == set(Condition)
    assert CONDITION_SEMANTICS[Condition.BLINDED].cannot_see
    assert CONDITION_SEMANTICS[Condition.CHARMED].cannot_attack_source
    assert CONDITION_SEMANTICS[Condition.FRIGHTENED].attacks_disadvantage_while_source_visible
    assert CONDITION_SEMANTICS[Condition.GRAPPLED].speed_zero
    assert CONDITION_SEMANTICS[Condition.INCAPACITATED].blocks_reactions
    assert CONDITION_SEMANTICS[Condition.INVISIBLE].attacks_advantage
    assert CONDITION_SEMANTICS[Condition.PARALYZED].adjacent_hit_is_critical
    assert CONDITION_SEMANTICS[Condition.PETRIFIED].damage_resistance_all
    assert CONDITION_SEMANTICS[Condition.POISONED].ability_checks_disadvantage
    assert CONDITION_SEMANTICS[Condition.PRONE].crawl_or_stand_only
    assert CONDITION_SEMANTICS[Condition.RESTRAINED].dexterity_saves_disadvantage
    assert CONDITION_SEMANTICS[Condition.STUNNED].auto_fail_dexterity_saves
    assert CONDITION_SEMANTICS[Condition.UNCONSCIOUS].drops_held_items


def test_p4d_d3_exhaustion_is_cumulative_and_recovers() -> None:
    level4 = exhaustion_semantics(4)
    assert level4.ability_checks_disadvantage
    assert level4.speed_multiplier == 0.5
    assert level4.attacks_disadvantage and level4.saves_disadvantage
    assert level4.max_hp_multiplier == 0.5
    assert exhaustion_semantics(5).speed_zero
    assert exhaustion_semantics(6).dead
    assert change_exhaustion(4, -1) == 3
    assert change_exhaustion(5, 3) == 6


def test_p4d_d3_typed_effect_modifier_and_expiry() -> None:
    spec = EffectSpec(
        "buff",
        "bless",
        DurationSpec(DurationKind.ROUNDS, 2),
        "srd5.1:spell:bless",
        modifiers=(TypedModifier(ModifierScope.SAVE, ModifierMode.BONUS, value=1),),
    )
    effect = ActiveEffect.create("effect:1", spec)
    first, expired = expire_effects((effect,), boundary="round")
    assert expired == () and first[0].remaining_rounds == 1
    second, expired = expire_effects(first, boundary="round")
    assert second == () and expired == ("effect:1",)


def test_p4d_d4_concentration_replacement_and_damage_failure_cleanup() -> None:
    old = ActiveEffect.create(
        "old:1",
        EffectSpec("condition", "restrained", DurationSpec(DurationKind.ROUNDS, 10), "srd5.1:spell:web"),
        concentration_owner_ref="character:1",
    )
    new = ActiveEffect.create(
        "new:1",
        EffectSpec("condition", "frightened", DurationSpec(DurationKind.ROUNDS, 10), "srd5.1:spell:fear"),
        concentration_owner_ref="character:1",
    )
    replaced = start_concentration(
        owner_ref="character:1",
        source_ref="srd5.1:spell:fear",
        effects=(old, new),
        current=Concentration("character:1", "srd5.1:spell:web", ("old:1",)),
    )
    assert replaced.removed_effect_ids == ("old:1",)
    assert replaced.concentration is not None and replaced.concentration.effect_ids == ("new:1",)
    assert concentration_dc(21) == 10 and concentration_dc(22) == 11
    failed = resolve_concentration_damage(
        current=replaced.concentration,
        effects=replaced.effects,
        damage_taken=24,
        d20=5,
        constitution_save_modifier=3,
    )
    assert failed.concentration is None
    assert failed.effects == ()


def test_p4d_d4_zero_damage_does_not_trigger_concentration_check() -> None:
    current = Concentration("character:1", "srd5.1:spell:web", ())
    result = resolve_concentration_damage(
        current=current,
        effects=(),
        damage_taken=0,
        d20=1,
        constitution_save_modifier=-5,
    )
    assert result.concentration == current
    assert result.events == ()


# D.5 — durable reaction/Ready/OA/legendary substrate.
def test_p4d_d5_reaction_payload_roundtrip_and_single_resolution() -> None:
    window = open_reaction_window(
        window_id="rw:1",
        entry_id="entry:2",
        kind=ReactionKind.SHIELD,
        reason="incoming attack",
        source_entry_id="entry:1",
        eligible_entry_ids=("entry:2",),
        target_entry_id="entry:2",
        safe_payload={"spell": "shield"},
        secret_payload={"dc": 17},
        session_ref="session:1",
    )
    restored = ReactionWindow.from_payload(window.to_payload())
    assert restored == window
    accepted = resolve_reaction(
        window=restored,
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
    expired = expire_reaction_window(accepted.window)
    assert expired.events == ()


def test_p4d_d5_opportunity_attack_is_dm_adjudicated_only() -> None:
    with pytest.raises(PermissionError, match="DM adjudication"):
        open_opportunity_attack_window(
            window_id="oa:1",
            entry_id="entry:defender",
            source_entry_id="entry:defender",
            target_entry_id="entry:mover",
            dm_adjudicated=False,
        )
    window = open_opportunity_attack_window(
        window_id="oa:2",
        entry_id="entry:defender",
        source_entry_id="entry:defender",
        target_entry_id="entry:mover",
        dm_adjudicated=True,
    )
    assert window.kind is ReactionKind.OPPORTUNITY_ATTACK


def test_p4d_d5_ready_roundtrip_and_owner_turn_expiry_no_refund() -> None:
    ready = create_ready_state(
        owner_entry_id="entry:1",
        trigger="enemy_enters_reach",
        response="attack",
        created_turn_key="r1:e1",
        expires_at_owner_turn_key="r2:e1",
        spell_ref="srd5.1:spell:hold-person",
        spell_slot_level=2,
        concentration_started=True,
    )
    assert ReadyState.from_payload(ready.to_payload()) == ready
    same, events = expire_ready_at_turn_start(ready=ready, owner_turn_key="r1:e2")
    assert same == ready and events == ()
    expired, events = expire_ready_at_turn_start(ready=ready, owner_turn_key="r2:e1")
    assert expired is None
    assert events[0]["refund"] is False


def test_p4d_d5_legendary_action_requires_other_creature_turn_end_and_resource() -> None:
    with pytest.raises(ValueError, match="another creature"):
        spend_legendary_action(owner_entry_id="dragon", ended_turn_entry_id="dragon", available_points=3, cost=1)
    remaining, event = spend_legendary_action(
        owner_entry_id="dragon", ended_turn_entry_id="fighter", available_points=3, cost=2
    )
    assert remaining == 1
    assert event["remaining"] == 1
