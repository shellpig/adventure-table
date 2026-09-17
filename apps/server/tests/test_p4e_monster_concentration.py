from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, update

from app.content import load_default_content_registry
from app.domain.combat.effect_resolver import DurationKind, DurationSpec, EffectSpec
from app.domain.combat.resolution import DamageRollPart, DamageType
from app.domain.combat.spell_resolver import SpellCastMode
from app.persistence.characters import CharacterRepository
from app.persistence.combat.concentration import (
    CombatConcentrationRepository,
    CombatConcentrationStateConflictError,
)
from app.persistence.combat.resolution import CombatResolutionRepository
from app.persistence.combat.spells import CombatSpellRepository
from app.persistence.combat.tables import combat_entries, monster_instances
from app.persistence.rooms.p3c_runtime import roll_requests
from tests.test_p4d_persistence import _enable_fireball_profile, _running_aoe_table
from tests.test_p4e_monster_cast import _running_mage_combat


def test_mage_casts_concentration_spell_stores_concentration_pointer_with_effect_ids() -> None:
    table, running, caster_id, mage, _target_id = _running_mage_combat()
    try:
        repository = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        stored, event = repository.cast_monster_spell(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:fly",
            spell_level=3,
            slot_level=3,
            cast_mode=SpellCastMode.UTILITY,
            target_entry_id=caster_id,
            concentration=True,
            apply_effects=(
                EffectSpec(
                    effect_type="condition",
                    tag="flying",
                    duration=DurationSpec(kind=DurationKind.UNTIL_CONCENTRATION_ENDS),
                    source_ref="srd5.1:spell:fly",
                ),
            ),
            roll_source="physical",
            idempotency_key="p4e-test-fly-1",
        )

        assert stored.status == "resolved"
        assert stored.resolution_result is not None
        assert stored.resolution_result["concentration_started"] is True
        applied_ids = stored.resolution_result["applied_effect_ids"]
        assert len(applied_ids) == 1
        fly_effect_id = applied_ids[0]

        reloaded = table.monsters.get_instance(mage.id)
        assert reloaded is not None
        assert reloaded.concentration == {
            "source_ref": "srd5.1:spell:fly",
            "effect_ids": [fly_effect_id],
        }
        assert any(eff["effect_id"] == fly_effect_id for eff in reloaded.effects)
        assert any(
            ev.get("type") == "concentration_started"
            for ev in stored.resolution_result.get("domain_events", [])
        )
    finally:
        table.engine.dispose()


def test_mage_casts_second_concentration_spell_replaces_pointer_and_strips_linked_effects() -> None:
    table, running, caster_id, mage, target_id = _running_mage_combat()
    try:
        repository = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        # 1) First cast: Mage casts Suggestion on the PC target
        first_cast, _ = repository.cast_monster_spell(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:suggestion",
            spell_level=2,
            slot_level=2,
            cast_mode=SpellCastMode.SAVE,
            target_entry_id=target_id,
            save_ability_ref="srd5.1:ability:wis",
            save_dc=14,
            save_modifier=0,
            save_d20=2,  # Fails save
            concentration=True,
            apply_effects=(
                EffectSpec(
                    effect_type="condition",
                    tag="charmed",
                    duration=DurationSpec(kind=DurationKind.UNTIL_CONCENTRATION_ENDS),
                    source_ref="srd5.1:spell:suggestion",
                ),
            ),
            roll_source="physical",
            idempotency_key="p4e-test-sugg-1",
        )
        assert first_cast.resolution_result is not None
        first_effect_id = first_cast.resolution_result["applied_effect_ids"][0]

        # Verify PC target has the charmed effect
        registry = load_default_content_registry()
        pc = CharacterRepository(table.engine, registry).load_character(table.character_id)
        assert any(e.effect_id == first_effect_id for e in pc.state.temporary_effects)

        # Reset mage action economy for next turn
        with table.engine.begin() as conn:
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == caster_id)
                .values(action_available=True)
            )

        # 2) Second cast: Mage casts Greater Invisibility on self
        second_cast, _ = repository.cast_monster_spell(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:greater-invisibility",
            spell_level=4,
            slot_level=4,
            cast_mode=SpellCastMode.UTILITY,
            target_entry_id=caster_id,
            concentration=True,
            apply_effects=(
                EffectSpec(
                    effect_type="condition",
                    tag="invisible",
                    duration=DurationSpec(kind=DurationKind.UNTIL_CONCENTRATION_ENDS),
                    source_ref="srd5.1:spell:greater-invisibility",
                ),
            ),
            roll_source="physical",
            idempotency_key="p4e-test-invis-1",
        )
        assert second_cast.resolution_result is not None
        assert second_cast.resolution_result["concentration_started"] is True
        assert second_cast.resolution_result["replaced_concentration_effect_ids"] == [first_effect_id]
        removed_from = second_cast.resolution_result["replaced_effects_removed_from"]
        assert any(r["entry_id"] == str(target_id) for r in removed_from)

        # PC no longer has first_effect_id
        pc_after = CharacterRepository(table.engine, registry).load_character(table.character_id)
        assert not any(e.effect_id == first_effect_id for e in pc_after.state.temporary_effects)

        # Mage now concentrates on Greater Invisibility
        second_effect_id = second_cast.resolution_result["applied_effect_ids"][0]
        reloaded = table.monsters.get_instance(mage.id)
        assert reloaded is not None
        assert reloaded.concentration == {
            "source_ref": "srd5.1:spell:greater-invisibility",
            "effect_ids": [second_effect_id],
        }
    finally:
        table.engine.dispose()


def test_apply_damage_on_concentrating_monster_creates_concentration_request() -> None:
    table, running, caster_id, mage, target_id = _running_mage_combat()
    try:
        spell_repo = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        # Mage casts Fly on self to establish concentration
        spell_repo.cast_monster_spell(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:fly",
            spell_level=3,
            slot_level=3,
            cast_mode=SpellCastMode.UTILITY,
            target_entry_id=caster_id,
            concentration=True,
            apply_effects=(
                EffectSpec(
                    effect_type="condition",
                    tag="flying",
                    duration=DurationSpec(kind=DurationKind.UNTIL_CONCENTRATION_ENDS),
                    source_ref="srd5.1:spell:fly",
                ),
            ),
            roll_source="physical",
            idempotency_key="p4e-conc-fly",
        )

        res_repo = CombatResolutionRepository(table.engine, table.events.repository)
        # Apply 24 damage: DC should be max(10, 24 // 2) = 12
        damage_res = res_repo.apply_damage(
            binding=dm_binding,
            combat_id=running.id,
            target_entry_id=caster_id,
            damage_parts=(DamageRollPart(damage_type=DamageType.FORCE, dice=(12, 12)),),
            critical=False,
            source_entry_id=target_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            idempotency_key="p4e-damage-24",
        )

        check = damage_res.payload.get("concentration_check")
        assert check is not None
        assert check["dc"] == 12
        assert check["source_ref"] == "srd5.1:spell:fly"
        req_id = UUID(check["roll_request_id"])

        with table.engine.connect() as conn:
            req = conn.execute(
                select(roll_requests).where(roll_requests.c.id == req_id)
            ).mappings().one()
        assert req["target_combat_entry_id"] == caster_id
        assert req["target_character_id"] is None
        assert req["ability_ref"] == "srd5.1:ability:constitution"
        assert req["dc"] == 12
        assert req["status"] == "pending"

        # Contrast 1: 0 damage produces no concentration request
        zero_res = res_repo.apply_damage(
            binding=dm_binding,
            combat_id=running.id,
            target_entry_id=caster_id,
            damage_parts=(DamageRollPart(damage_type=DamageType.FORCE, dice=(), flat_modifier=0),),
            critical=False,
            source_entry_id=target_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            idempotency_key="p4e-zero-damage",
        )
        assert zero_res.payload.get("concentration_check") is None

        # Contrast 2: Non-concentrating monster produces no concentration request
        non_conc = table.monsters.create_quick_enemy(
            campaign_id=table.campaign_id,
            name="Goblin Non-Conc",
            max_hp=10,
            armor_class=12,
            speed={"walk": "30 ft."},
        )
        table.combat.add_monster(
            table.dm_actor,
            support_lifecycle_add(non_conc.id, "p4e-add-goblin"),
        )
        with table.engine.connect() as conn:
            goblin_entry = conn.execute(
                select(combat_entries.c.id).where(
                    combat_entries.c.combat_id == running.id,
                    combat_entries.c.monster_instance_id == non_conc.id,
                )
            ).scalar_one()

        goblin_res = res_repo.apply_damage(
            binding=dm_binding,
            combat_id=running.id,
            target_entry_id=goblin_entry,
            damage_parts=(DamageRollPart(damage_type=DamageType.SLASHING, dice=(6,)),),
            critical=False,
            source_entry_id=target_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            idempotency_key="p4e-goblin-damage",
        )
        assert goblin_res.payload.get("concentration_check") is None
    finally:
        table.engine.dispose()


def support_lifecycle_add(monster_instance_id: UUID, idempotency_key: str):
    from app.domain.combat.lifecycle import AddMonsterInput
    return AddMonsterInput(
        monster_instance_id=monster_instance_id,
        idempotency_key=idempotency_key,
    )


def test_complete_check_monster_failure_clears_pointer_and_strips_effects() -> None:
    table, running, caster_id, mage, target_id = _running_mage_combat()
    try:
        spell_repo = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        # Mage casts Fly
        cast, _ = spell_repo.cast_monster_spell(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:fly",
            spell_level=3,
            slot_level=3,
            cast_mode=SpellCastMode.UTILITY,
            target_entry_id=caster_id,
            concentration=True,
            apply_effects=(
                EffectSpec(
                    effect_type="condition",
                    tag="flying",
                    duration=DurationSpec(kind=DurationKind.UNTIL_CONCENTRATION_ENDS),
                    source_ref="srd5.1:spell:fly",
                ),
            ),
            roll_source="physical",
            idempotency_key="p4e-conc-fly-fail",
        )
        assert cast.resolution_result is not None
        fly_effect_id = cast.resolution_result["applied_effect_ids"][0]

        res_repo = CombatResolutionRepository(table.engine, table.events.repository)
        damage_res = res_repo.apply_damage(
            binding=dm_binding,
            combat_id=running.id,
            target_entry_id=caster_id,
            damage_parts=(DamageRollPart(damage_type=DamageType.FORCE, dice=(20,)),),
            critical=False,
            source_entry_id=target_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            idempotency_key="p4e-damage-fail-setup",
        )
        check = damage_res.payload["concentration_check"]
        request_id = UUID(check["roll_request_id"])

        conc_repo = CombatConcentrationRepository(table.engine, table.events.repository)
        resolved, event = conc_repo.complete_check(
            binding=dm_binding,
            request_id=request_id,
            acting_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            d20=1,
            constitution_save_modifier=0,  # 1 < 10 (DC) -> Fail
            roll_source="physical",
            idempotency_key="p4e-complete-fail",
        )

        assert resolved.succeeded is False
        assert resolved.total == 1
        assert event.kind == "combat.concentration_resolved"
        assert event.payload["linked_effect_ids"] == [fly_effect_id]

        reloaded = table.monsters.get_instance(mage.id)
        assert reloaded is not None
        assert reloaded.concentration is None
        assert not any(eff["effect_id"] == fly_effect_id for eff in reloaded.effects)
        assert not any(cond["effect_id"] == fly_effect_id for cond in reloaded.conditions)
    finally:
        table.engine.dispose()


def test_complete_check_monster_success_retains_pointer() -> None:
    table, running, caster_id, mage, target_id = _running_mage_combat()
    try:
        spell_repo = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        # Mage casts Fly
        cast, _ = spell_repo.cast_monster_spell(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:fly",
            spell_level=3,
            slot_level=3,
            cast_mode=SpellCastMode.UTILITY,
            target_entry_id=caster_id,
            concentration=True,
            apply_effects=(
                EffectSpec(
                    effect_type="condition",
                    tag="flying",
                    duration=DurationSpec(kind=DurationKind.UNTIL_CONCENTRATION_ENDS),
                    source_ref="srd5.1:spell:fly",
                ),
            ),
            roll_source="physical",
            idempotency_key="p4e-conc-fly-succ",
        )
        assert cast.resolution_result is not None
        fly_effect_id = cast.resolution_result["applied_effect_ids"][0]

        res_repo = CombatResolutionRepository(table.engine, table.events.repository)
        damage_res = res_repo.apply_damage(
            binding=dm_binding,
            combat_id=running.id,
            target_entry_id=caster_id,
            damage_parts=(DamageRollPart(damage_type=DamageType.FORCE, dice=(20,)),),
            critical=False,
            source_entry_id=target_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            idempotency_key="p4e-damage-succ-setup",
        )
        check = damage_res.payload["concentration_check"]
        request_id = UUID(check["roll_request_id"])

        conc_repo = CombatConcentrationRepository(table.engine, table.events.repository)
        resolved, event = conc_repo.complete_check(
            binding=dm_binding,
            request_id=request_id,
            acting_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            d20=15,
            constitution_save_modifier=2,  # 17 >= 10 (DC) -> Success
            roll_source="physical",
            idempotency_key="p4e-complete-succ",
        )

        assert resolved.succeeded is True
        assert resolved.total == 17
        assert event.kind == "combat.concentration_resolved"

        reloaded = table.monsters.get_instance(mage.id)
        assert reloaded is not None
        assert reloaded.concentration == {
            "source_ref": "srd5.1:spell:fly",
            "effect_ids": [fly_effect_id],
        }
        assert any(eff["effect_id"] == fly_effect_id for eff in reloaded.effects)
    finally:
        table.engine.dispose()


def test_duplicate_complete_check_on_monster_raises_conflict_without_side_effects() -> None:
    table, running, caster_id, mage, target_id = _running_mage_combat()
    try:
        spell_repo = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        # Mage casts Fly
        cast, _ = spell_repo.cast_monster_spell(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:fly",
            spell_level=3,
            slot_level=3,
            cast_mode=SpellCastMode.UTILITY,
            target_entry_id=caster_id,
            concentration=True,
            apply_effects=(
                EffectSpec(
                    effect_type="condition",
                    tag="flying",
                    duration=DurationSpec(kind=DurationKind.UNTIL_CONCENTRATION_ENDS),
                    source_ref="srd5.1:spell:fly",
                ),
            ),
            roll_source="physical",
            idempotency_key="p4e-conc-fly-dup",
        )

        res_repo = CombatResolutionRepository(table.engine, table.events.repository)
        damage_res = res_repo.apply_damage(
            binding=dm_binding,
            combat_id=running.id,
            target_entry_id=caster_id,
            damage_parts=(DamageRollPart(damage_type=DamageType.FORCE, dice=(20,)),),
            critical=False,
            source_entry_id=target_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            idempotency_key="p4e-damage-dup-setup",
        )
        check = damage_res.payload["concentration_check"]
        request_id = UUID(check["roll_request_id"])

        conc_repo = CombatConcentrationRepository(table.engine, table.events.repository)
        resolved, event = conc_repo.complete_check(
            binding=dm_binding,
            request_id=request_id,
            acting_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            d20=15,
            constitution_save_modifier=2,
            roll_source="physical",
            idempotency_key="p4e-first-complete",
        )

        # Replay with same idempotency key succeeds identically
        replay, replay_event = conc_repo.complete_check(
            binding=dm_binding,
            request_id=request_id,
            acting_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            d20=1,
            constitution_save_modifier=0,
            roll_source="physical",
            idempotency_key="p4e-first-complete",
        )
        assert replay == resolved
        assert replay_event.id == event.id

        # Re-resolve with different idempotency key raises CombatConcentrationStateConflictError
        with pytest.raises(
            CombatConcentrationStateConflictError,
            match="Concentration RollRequest is already resolved",
        ):
            conc_repo.complete_check(
                binding=dm_binding,
                request_id=request_id,
                acting_seat_id=table.dm_actor.seat_id,
                execution_mode="dm_proxy",
                d20=1,
                constitution_save_modifier=0,
                roll_source="physical",
                idempotency_key="p4e-second-complete-diff-key",
            )
    finally:
        table.engine.dispose()


def test_end_combat_preserves_monster_concentration() -> None:
    table, running, caster_id, mage, _target_id = _running_mage_combat()
    try:
        spell_repo = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        # Mage casts Fly
        spell_repo.cast_monster_spell(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:fly",
            spell_level=3,
            slot_level=3,
            cast_mode=SpellCastMode.UTILITY,
            target_entry_id=caster_id,
            concentration=True,
            apply_effects=(
                EffectSpec(
                    effect_type="condition",
                    tag="flying",
                    duration=DurationSpec(kind=DurationKind.UNTIL_CONCENTRATION_ENDS),
                    source_ref="srd5.1:spell:fly",
                ),
            ),
            roll_source="physical",
            idempotency_key="p4e-conc-fly-end",
        )

        reloaded = table.monsters.get_instance(mage.id)
        assert reloaded is not None
        assert reloaded.concentration is not None
        assert reloaded.concentration["source_ref"] == "srd5.1:spell:fly"

        # End combat
        table.combat.end_combat(
            table.dm_actor,
            idempotency_key="p4e-end-combat-conc-check",
        )

        # Verify concentration pointer is still intact
        reloaded_after = table.monsters.get_instance(mage.id)
        assert reloaded_after is not None
        assert reloaded_after.concentration is not None
        assert reloaded_after.concentration["source_ref"] == "srd5.1:spell:fly"
    finally:
        table.engine.dispose()


def test_character_spell_damaging_concentrating_monster_creates_concentration_request() -> None:
    table, running, caster, target, enemy = _running_aoe_table()
    try:
        _enable_fireball_profile(table)
        spell_repo = CombatSpellRepository(table.engine, table.events.repository)
        player_binding = table.events._stored_binding(table.player_actor)

        # Set concentration pointer on enemy monster
        conc_payload = {"source_ref": "srd5.1:spell:fly", "effect_ids": ["fly-test:1"]}
        with table.engine.begin() as conn:
            conn.execute(
                update(monster_instances)
                .where(monster_instances.c.id == enemy.id)
                .values(concentration=conc_payload)
            )

        # Character casts attack spell (Magic Missile) hitting the monster
        attack, _event = spell_repo.cast_character_spell(
            binding=player_binding,
            combat_id=running.id,
            caster_entry_id=caster.id,
            subject_seat_id=table.player_seat_id,
            execution_mode="self",
            profile_id="wizard",
            spell_ref="srd5.1:spell:magic-missile",
            spell_level=1,
            slot_level=1,
            cast_mode=SpellCastMode.ATTACK,
            target_entry_id=target.id,
            attack_modifier=5,
            attack_d20s=(10,),
            damage_parts=(DamageRollPart(damage_type=DamageType.FORCE, dice=(2, 2)),),  # 4 damage
            roll_source="physical",
            idempotency_key="p4e-char-spell-dmg-conc",
        )

        assert attack.resolution_result is not None
        assert attack.resolution_result["damage"] == 4
        check = attack.resolution_result.get("concentration_check")
        assert check is not None
        assert check["dc"] == 10
        assert check["source_ref"] == "srd5.1:spell:fly"

        req_id = UUID(check["roll_request_id"])
        with table.engine.connect() as conn:
            req = conn.execute(
                select(roll_requests).where(roll_requests.c.id == req_id)
            ).mappings().one()
        assert req["target_combat_entry_id"] == target.id
        assert req["target_character_id"] is None
        assert req["ability_ref"] == "srd5.1:ability:constitution"
        assert req["dc"] == 10
        assert req["status"] == "pending"
    finally:
        table.engine.dispose()
