from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from app.content import load_default_content_registry
from app.content.p4a_combat_templates import monster_to_reusable_rules
from app.content.p4a_monsters import MonsterData
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.combat.resolution import DamageRollPart, DamageType
from app.domain.combat.spell_resolver import SaveDamageMode, SpellCastMode
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.persistence.characters import CharacterRepository
from app.persistence.combat.spells import CombatSpellRepository, CombatSpellStateConflictError
from app.persistence.combat.tables import combat_actions, combat_entries, combats, monster_instances
from app.persistence.rooms.p3c_runtime import roll_requests, roll_results
from app.persistence.rooms.table_runtime import session_events
import tests.test_p4b_combat_lifecycle as support


def _mage_rules_and_resources() -> tuple[dict[str, Any], dict[str, int]]:
    registry = load_default_content_registry()
    mage_entry = registry.get("srd5.1:monster:mage")
    rules = monster_to_reusable_rules(MonsterData.model_validate(mage_entry.data))
    slots = rules["traits"][0]["spellcasting"]["slots"]
    resources = {f"spell_slot:{level}": count for level, count in slots.items()}
    return rules, resources


def _running_mage_combat(*, custom_resources: dict[str, Any] | None = None):
    table = support._setup()
    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key="p4e-test-start"),
    )
    rules, default_resources = _mage_rules_and_resources()
    resources = custom_resources if custom_resources is not None else default_resources
    mage_instance = table.monsters.create_instance(
        campaign_id=table.campaign_id,
        name="SRD Mage",
        rules_snapshot=rules,
        resources=resources,
    )
    table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=mage_instance.id,
            idempotency_key="p4e-test-add-mage",
        ),
    )
    requested = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="p4e-test-init"),
    )
    for index, request in enumerate(requested.requests):
        actor = table.player_actor if request.target_seat_id is not None else table.dm_actor
        raw = 1 if request.target_seat_id is not None else 20
        table.initiative.complete_initiative(
            actor,
            FormalRollInput(
                roll_request_id=request.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(raw,),
                idempotency_key=f"p4e-test-init-roll-{index}",
            ),
        )

    with table.engine.connect() as connection:
        rows = connection.execute(
            select(
                combat_entries.c.id,
                combat_entries.c.character_id,
                combat_entries.c.monster_instance_id,
            ).where(
                combat_entries.c.combat_id
                == table.combat.get_active_combat(table.dm_actor).id
            )
        ).mappings().all()
    mage_entry = next(r for r in rows if r["monster_instance_id"] == mage_instance.id)
    target_entry = next(r for r in rows if r["character_id"] == table.character_id)

    # Place mage first in order so it is the active turn caster
    running = table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=(mage_entry["id"], target_entry["id"]),
            idempotency_key="p4e-test-finalize",
        ),
    )
    assert running.current_turn_entry_id == mage_entry["id"]
    return table, running, mage_entry["id"], mage_instance, target_entry["id"]


def test_mage_instance_casts_leveled_spell_deducts_slot_and_writes_state_atomically() -> None:
    table, running, caster_id, mage, target_id = _running_mage_combat()
    try:
        registry = load_default_content_registry()
        before_character = CharacterRepository(table.engine, registry).load_character(
            table.character_id
        )
        before_hp = before_character.state.current_hp
        assert mage.resources["spell_slot:3"] == 3

        repository = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        # Cast Fireball (3rd level save spell, DC 14 from Mage stat block)
        cast_args = dict(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:fireball",
            spell_level=3,
            slot_level=3,
            cast_mode=SpellCastMode.SAVE,
            target_entry_id=target_id,
            target_seat_id=table.player_seat_id,
            save_ability_ref="srd5.1:ability:dex",
            save_modifier=2,
            save_d20=5,  # 5 + 2 = 7 < 14 (failed save)
            save_damage_mode=SaveDamageMode.HALF,
            damage_parts=(DamageRollPart(damage_type=DamageType.FIRE, dice=(8, 8)),),  # 16 dmg
            roll_source="physical",
            idempotency_key="p4e-fireball-cast-1",
        )

        stored, event = repository.cast_monster_spell(**cast_args)
        assert stored.status == "resolved"
        assert stored.cast_mode is SpellCastMode.SAVE
        assert stored.target_entry_id == target_id
        assert event.kind == "combat.spell_cast_resolved"
        assert stored.resolution_result is not None
        assert stored.resolution_result["damage"] == 16
        assert stored.resolution_result["roll"]["total"] == 7

        # 1) Slot deducted once on monster instance in DB
        reloaded_mage = table.monsters.get_instance(mage.id)
        assert reloaded_mage is not None
        assert reloaded_mage.resources["spell_slot:3"] == 2
        # Other slot pools remain untouched
        assert reloaded_mage.resources["spell_slot:1"] == 4
        assert reloaded_mage.resources["spell_slot:2"] == 3

        # 2) Target Character HP reduced by damage amount
        after_character = CharacterRepository(table.engine, registry).load_character(
            table.character_id
        )
        assert after_character.state.current_hp == before_hp - 16

        # 3) Mage action economy spent
        with table.engine.connect() as connection:
            caster_row = connection.execute(
                select(combat_entries.c.action_available).where(
                    combat_entries.c.id == caster_id
                )
            ).mappings().one()
            assert caster_row["action_available"] is False

            # 4) Roll record inserted in same transaction
            save_requests = connection.execute(
                select(roll_requests).where(
                    roll_requests.c.session_id == table.session_id,
                    roll_requests.c.ability_ref == "srd5.1:ability:dex",
                    roll_requests.c.target_combat_entry_id == target_id,
                )
            ).mappings().all()
            assert len(save_requests) == 1
            assert save_requests[0]["status"] == "resolved"
            assert save_requests[0]["dc"] == 14  # from Mage stat block dc

            results = connection.execute(
                select(roll_results).where(
                    roll_results.c.roll_request_id == save_requests[0]["id"]
                )
            ).mappings().all()
            assert len(results) == 1
            assert results[0]["total"] == 7

            # 5) combat_actions record committed
            action_row = connection.execute(
                select(combat_actions).where(combat_actions.c.id == stored.action_id)
            ).mappings().one()
            assert action_row["action_kind"] == "spell_cast"
            assert action_row["resolution_status"] == "resolved"
            assert action_row["idempotency_key"] == "p4e-fireball-cast-1"

            # 6) session_events committed
            event_rows = connection.execute(
                select(session_events).where(
                    session_events.c.idempotency_key == "p4e-monster-cast:p4e-fireball-cast-1"
                )
            ).mappings().all()
            assert len(event_rows) == 1
    finally:
        table.engine.dispose()


def test_duplicate_idempotency_key_prevents_second_deduction_and_damage() -> None:
    table, running, caster_id, mage, target_id = _running_mage_combat()
    try:
        registry = load_default_content_registry()
        before_character = CharacterRepository(table.engine, registry).load_character(
            table.character_id
        )
        before_hp = before_character.state.current_hp

        repository = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        cast_args = dict(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:fireball",
            spell_level=3,
            slot_level=3,
            cast_mode=SpellCastMode.SAVE,
            target_entry_id=target_id,
            target_seat_id=table.player_seat_id,
            save_ability_ref="srd5.1:ability:dex",
            save_modifier=2,
            save_d20=5,
            save_damage_mode=SaveDamageMode.HALF,
            damage_parts=(DamageRollPart(damage_type=DamageType.FIRE, dice=(8, 8)),),
            roll_source="physical",
            idempotency_key="p4e-idempotent-key",
        )

        first_stored, first_event = repository.cast_monster_spell(**cast_args)
        assert first_stored.status == "resolved"

        reloaded_mage = table.monsters.get_instance(mage.id)
        assert reloaded_mage is not None
        assert reloaded_mage.resources["spell_slot:3"] == 2

        with table.engine.connect() as connection:
            first_revision = connection.scalar(
                select(combats.c.revision).where(combats.c.id == running.id)
            )

        # Retry with identical idempotency_key
        duplicate_stored, duplicate_event = repository.cast_monster_spell(**cast_args)
        assert duplicate_stored.action_id == first_stored.action_id
        assert duplicate_event.id == first_event.id

        # Slot was NOT deducted a second time
        after_retry_mage = table.monsters.get_instance(mage.id)
        assert after_retry_mage is not None
        assert after_retry_mage.resources["spell_slot:3"] == 2

        # Target HP was NOT deducted a second time
        after_character = CharacterRepository(table.engine, registry).load_character(
            table.character_id
        )
        assert after_character.state.current_hp == before_hp - 16

        with table.engine.connect() as connection:
            # Combat revision not incremented again
            second_revision = connection.scalar(
                select(combats.c.revision).where(combats.c.id == running.id)
            )
            assert second_revision == first_revision

            # Exactly one spell save roll request and one session event
            reqs = connection.execute(
                select(roll_requests).where(
                    roll_requests.c.session_id == table.session_id,
                    roll_requests.c.ability_ref == "srd5.1:ability:dex",
                    roll_requests.c.target_combat_entry_id == target_id,
                )
            ).mappings().all()
            assert len(reqs) == 1

            evs = connection.execute(
                select(session_events).where(
                    session_events.c.idempotency_key == "p4e-monster-cast:p4e-idempotent-key"
                )
            ).mappings().all()
            assert len(evs) == 1
    finally:
        table.engine.dispose()


def test_insufficient_slot_rejected_with_zero_side_effects() -> None:
    # Set up mage with 0 remaining level 3 slots
    _, default_resources = _mage_rules_and_resources()
    exhausted_resources = dict(default_resources)
    exhausted_resources["spell_slot:3"] = 0

    table, running, caster_id, mage, target_id = _running_mage_combat(
        custom_resources=exhausted_resources
    )
    try:
        registry = load_default_content_registry()
        before_character = CharacterRepository(table.engine, registry).load_character(
            table.character_id
        )
        before_hp = before_character.state.current_hp

        with table.engine.connect() as connection:
            before_revision = connection.scalar(
                select(combats.c.revision).where(combats.c.id == running.id)
            )

        repository = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        cast_args = dict(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:fireball",
            spell_level=3,
            slot_level=3,
            cast_mode=SpellCastMode.SAVE,
            target_entry_id=target_id,
            target_seat_id=table.player_seat_id,
            save_ability_ref="srd5.1:ability:dex",
            save_modifier=2,
            save_d20=5,
            save_damage_mode=SaveDamageMode.HALF,
            damage_parts=(DamageRollPart(damage_type=DamageType.FIRE, dice=(8, 8)),),
            roll_source="physical",
            idempotency_key="p4e-insufficient-slot",
        )

        with pytest.raises(ValueError, match="monster spell resource is unavailable: spell_slot:3"):
            repository.cast_monster_spell(**cast_args)

        # Zero side effects:
        # 1) Slot still 0 (not corrupted or decremented to negative)
        reloaded_mage = table.monsters.get_instance(mage.id)
        assert reloaded_mage is not None
        assert reloaded_mage.resources["spell_slot:3"] == 0

        # 2) Target HP unchanged
        after_character = CharacterRepository(table.engine, registry).load_character(
            table.character_id
        )
        assert after_character.state.current_hp == before_hp

        # 3) Mage action economy still available
        with table.engine.connect() as connection:
            caster_row = connection.execute(
                select(combat_entries.c.action_available).where(
                    combat_entries.c.id == caster_id
                )
            ).mappings().one()
            assert caster_row["action_available"] is True

            # 4) No combat_actions row inserted
            actions = connection.execute(
                select(combat_actions).where(
                    combat_actions.c.idempotency_key == "p4e-insufficient-slot"
                )
            ).mappings().all()
            assert len(actions) == 0

            # 5) No session event appended
            events = connection.execute(
                select(session_events).where(
                    session_events.c.idempotency_key == "p4e-monster-cast:p4e-insufficient-slot"
                )
            ).mappings().all()
            assert len(events) == 0

            # 6) Combat revision unchanged
            assert (
                connection.scalar(select(combats.c.revision).where(combats.c.id == running.id))
                == before_revision
            )
    finally:
        table.engine.dispose()


def test_monster_with_no_spellcasting_rejected() -> None:
    table = support._setup()
    try:
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="p4e-no-spell-start"),
        )
        # Create a non-caster monster (e.g. Bandit)
        bandit = table.monsters.create_quick_enemy(
            campaign_id=table.campaign_id,
            name="Bandit",
            armor_class=12,
            max_hp=11,
            speed={"walk": "30 ft."},
            attack={"name": "Scimitar", "attack_bonus": 3, "damage": "1d6+1"},
        )
        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(
                monster_instance_id=bandit.id,
                idempotency_key="p4e-add-bandit",
            ),
        )
        requested = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(idempotency_key="p4e-bandit-init"),
        )
        for index, request in enumerate(requested.requests):
            actor = table.player_actor if request.target_seat_id is not None else table.dm_actor
            raw = 1 if request.target_seat_id is not None else 20
            table.initiative.complete_initiative(
                actor,
                FormalRollInput(
                    roll_request_id=request.id,
                    source=FormalRollSource.PHYSICAL,
                    raw_dice=(raw,),
                    idempotency_key=f"p4e-bandit-init-roll-{index}",
                ),
            )

        with table.engine.connect() as connection:
            rows = connection.execute(
                select(
                    combat_entries.c.id,
                    combat_entries.c.character_id,
                    combat_entries.c.monster_instance_id,
                ).where(
                    combat_entries.c.combat_id
                    == table.combat.get_active_combat(table.dm_actor).id
                )
            ).mappings().all()
        bandit_entry = next(r for r in rows if r["monster_instance_id"] == bandit.id)
        target_entry = next(r for r in rows if r["character_id"] == table.character_id)

        running = table.initiative.finalize_initiative(
            table.dm_actor,
            FinalizeInitiativeInput(
                ordered_entry_ids=(bandit_entry["id"], target_entry["id"]),
                idempotency_key="p4e-bandit-finalize",
            ),
        )

        repository = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        with pytest.raises(ValueError, match="monster stat block has no spellcasting source"):
            repository.cast_monster_spell(
                binding=dm_binding,
                combat_id=running.id,
                caster_entry_id=bandit_entry["id"],
                subject_seat_id=table.dm_actor.seat_id,
                execution_mode="dm_proxy",
                spell_ref="srd5.1:spell:fireball",
                spell_level=3,
                slot_level=3,
                cast_mode=SpellCastMode.SAVE,
                target_entry_id=target_entry["id"],
                save_ability_ref="srd5.1:ability:dex",
                save_modifier=2,
                save_d20=5,
                roll_source="physical",
                idempotency_key="p4e-no-spell-cast",
            )

        # Zero side effects: bandit action still available
        with table.engine.connect() as connection:
            bandit_row = connection.execute(
                select(combat_entries.c.action_available).where(
                    combat_entries.c.id == bandit_entry["id"]
                )
            ).mappings().one()
            assert bandit_row["action_available"] is True
    finally:
        table.engine.dispose()


def test_unknown_spell_for_monster_rejected() -> None:
    table, running, caster_id, _mage, target_id = _running_mage_combat()
    try:
        repository = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        # Mage does not have cure wounds
        with pytest.raises(ValueError, match="monster does not have requested spell"):
            repository.cast_monster_spell(
                binding=dm_binding,
                combat_id=running.id,
                caster_entry_id=caster_id,
                subject_seat_id=table.dm_actor.seat_id,
                execution_mode="dm_proxy",
                spell_ref="srd5.1:spell:cure-wounds",
                spell_level=1,
                slot_level=1,
                cast_mode=SpellCastMode.HEAL,
                target_entry_id=target_id,
                healing_amount=8,
                roll_source="physical",
                idempotency_key="p4e-unknown-spell",
            )
    finally:
        table.engine.dispose()


def test_wrong_caster_kind_rejected() -> None:
    table, running, _caster_id, _mage, target_id = _running_mage_combat()
    try:
        # Advance turn or attempt to call cast_monster_spell with the PC entry as caster
        repository = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        # target_id is the Character entry, not a monster
        with pytest.raises(
            CombatSpellStateConflictError,
            match="Monster spell caster must be a monster combatant",
        ):
            # Temporarily set PC as current turn
            with table.engine.begin() as connection:
                connection.execute(
                    combats.update()
                    .where(combats.c.id == running.id)
                    .values(current_turn_entry_id=target_id)
                )
            repository.cast_monster_spell(
                binding=dm_binding,
                combat_id=running.id,
                caster_entry_id=target_id,
                subject_seat_id=table.player_seat_id,
                execution_mode="self",
                spell_ref="srd5.1:spell:fireball",
                spell_level=3,
                slot_level=3,
                cast_mode=SpellCastMode.SAVE,
                target_entry_id=target_id,
                save_ability_ref="srd5.1:ability:dex",
                save_modifier=2,
                save_d20=5,
                roll_source="physical",
                idempotency_key="p4e-wrong-caster",
            )
    finally:
        table.engine.dispose()


def test_mage_attack_cast_uses_stat_block_modifier() -> None:
    table, running, caster_id, mage, target_id = _running_mage_combat()
    try:
        repository = CombatSpellRepository(table.engine, table.events.repository)
        dm_binding = table.events._stored_binding(table.dm_actor)

        # Mage casts Magic Missile or an attack spell; Magic Missile in 5e 2014 SRD Mage
        # has attack_bonus = 6 from Mage's spellcasting stat block trait (+6 modifier)
        cast_args = dict(
            binding=dm_binding,
            combat_id=running.id,
            caster_entry_id=caster_id,
            subject_seat_id=table.dm_actor.seat_id,
            execution_mode="dm_proxy",
            spell_ref="srd5.1:spell:magic-missile",
            spell_level=1,
            slot_level=1,
            cast_mode=SpellCastMode.ATTACK,
            target_entry_id=target_id,
            target_ac=12,
            attack_d20s=(10,),  # 10 + 6 = 16 >= 12 (hit)
            damage_parts=(DamageRollPart(damage_type=DamageType.FORCE, dice=(2, 2)),),
            roll_source="physical",
            idempotency_key="p4e-attack-cast-1",
        )
        stored, _event = repository.cast_monster_spell(**cast_args)
        assert stored.status == "resolved"
        assert stored.resolution_result is not None
        assert stored.resolution_result["roll"]["modifier"] == 6  # from Mage stat block modifier
        assert stored.resolution_result["roll"]["total"] == 16
        assert stored.resolution_result["damage"] == 4

        reloaded_mage = table.monsters.get_instance(mage.id)
        assert reloaded_mage is not None
        assert reloaded_mage.resources["spell_slot:1"] == 3
    finally:
        table.engine.dispose()
