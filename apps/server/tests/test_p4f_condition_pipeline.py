from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, update

from app.content import load_default_content_registry
from app.domain.character.schemas import CharacterState
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.attacks import (
    AttackAdjudicationInput,
    AttackRequestInput,
    CombatAttackService,
)
from app.domain.combat.core_rolls import (
    CombatCoreRollService,
    SavingThrowInput,
)
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.combat.resolution import RollMode
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource, RollModifierMode
from app.persistence.characters import CharacterRepository, character_states
from app.persistence.combat.adjudication import CombatAdjudicationRepository
from app.persistence.combat.attacks import CombatAttackRepository
from app.persistence.combat.core_rolls import CombatCoreRollRepository
from app.persistence.combat.tables import combat_actions, combat_entries, monster_instances
from app.persistence.rooms.table_runtime import session_events
import tests.test_p4b_combat_lifecycle as support


def _equip_ranged_weapon(table) -> None:
    registry = load_default_content_registry()
    characters = CharacterRepository(table.engine, registry)
    character = characters.load_character(table.character_id)
    payload = character.state.model_dump(mode="json")
    payload["inventory_state"].append({
        "entry_id": "inventory:shortbow",
        "item_ref": "srd5.1:equipment:shortbow",
        "quantity": 1,
        "equipped": True,
    })
    CharacterState.model_validate(payload)
    with table.engine.begin() as connection:
        connection.execute(
            update(character_states)
            .where(character_states.c.character_id == table.character_id)
            .values(
                state_payload=payload,
                state_revision=character_states.c.state_revision + 1,
            )
        )


def _set_character_conditions(table, conditions: list[dict[str, Any]]) -> None:
    registry = load_default_content_registry()
    characters = CharacterRepository(table.engine, registry)
    character = characters.load_character(table.character_id)
    payload = character.state.model_dump(mode="json")
    payload["conditions"] = conditions
    CharacterState.model_validate(payload)
    with table.engine.begin() as connection:
        connection.execute(
            update(character_states)
            .where(character_states.c.character_id == table.character_id)
            .values(
                state_payload=payload,
                state_revision=character_states.c.state_revision + 1,
            )
        )


def _set_monster_conditions(table, monster_instance_id: UUID, conditions: list[dict[str, Any]]) -> None:
    with table.engine.begin() as connection:
        connection.execute(
            update(monster_instances)
            .where(monster_instances.c.id == monster_instance_id)
            .values(conditions=conditions)
        )


def _running_table(
    *,
    monster_conditions: list[dict[str, Any]] | None = None,
    character_conditions: list[dict[str, Any]] | None = None,
    equip_shortbow: bool = False,
    monster_first: bool = False,
    monster_ac: int = 12,
):
    table = support._setup()
    if equip_shortbow:
        _equip_ranged_weapon(table)
    if character_conditions:
        _set_character_conditions(table, character_conditions)

    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key="pipeline-start"),
    )

    enemy = table.monsters.create_instance(
        campaign_id=table.campaign_id,
        name="Pipeline Enemy",
        rules_snapshot={
            "armor_class": monster_ac,
            "max_hp": 20,
            "speed": {"walk": "30 ft."},
            "ability_scores": {
                "strength": 10,
                "dexterity": 10,
                "constitution": 10,
                "intelligence": 10,
                "wisdom": 10,
                "charisma": 10,
            },
            "actions": [
                {
                    "kind": "attack",
                    "name": "Claw",
                    "attack_kind": "melee",
                    "attack_bonus": 4,
                    "damage_parts": [
                        {"dice": "1d6+2", "damage_type": {"index": "slashing"}}
                    ],
                },
                {
                    "kind": "attack",
                    "name": "Dart",
                    "attack_kind": "ranged",
                    "attack_bonus": 4,
                    "damage_parts": [
                        {"dice": "1d4+2", "damage_type": {"index": "piercing"}}
                    ],
                },
            ],
        },
        conditions=monster_conditions or [],
    )

    table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=enemy.id,
            idempotency_key="pipeline-enemy",
        ),
    )
    requested = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="pipeline-init"),
    )
    for request in requested.requests:
        actor = table.player_actor if request.target_seat_id is not None else table.dm_actor
        raw = 20 if (request.target_seat_id is not None) != monster_first else 1
        table.initiative.complete_initiative(
            actor,
            FormalRollInput(
                roll_request_id=request.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(raw,),
                idempotency_key=f"pipeline-init-roll-{request.id}",
            ),
        )
    order = table.initiative.suggested_order(table.dm_actor)
    running = table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=order,
            idempotency_key="pipeline-finalize",
        ),
    )
    attacker_entry = next(entry for entry in running.entries if entry.character_id == table.character_id)
    target_entry = next(entry for entry in running.entries if entry.monster_instance_id == enemy.id)

    registry = load_default_content_registry()
    characters = CharacterRepository(table.engine, registry)
    attack_repo = CombatAttackRepository(table.engine, table.events.repository)
    adjudication_repo = CombatAdjudicationRepository(table.engine, table.events.repository)
    attacks = CombatAttackService(
        attack_repo,
        adjudication_repo,
        table.combat.repository,
        table.combat,
        AttackDefinitionResolver(characters, table.monsters, registry),
        table.rolls,
        table.events,
    )
    core_rolls = CombatCoreRollService(
        CombatCoreRollRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        table.monsters,
        table.rolls,
        table.events,
    )
    return table, attacks, core_rolls, attacker_entry, target_entry, enemy.id


def test_player_attack_vs_prone_monster_melee_advantage_and_ranged_disadvantage() -> None:
    # 1. Player melee attack vs prone Monster -> after DM adjudicate_attack(in_range=True) the pending
    # roll request has modifier_mode == "advantage"; action payload modifier_decision.advantage_sources
    # contains "target:prone"; the combat.adjudication_resolved event payload carries modifier_decision.
    # Same setup with a ranged attack source_ref -> "disadvantage".
    table, attacks, _core, hero, monster, _ = _running_table(
        monster_conditions=[{"condition_ref": "srd5.1:condition:prone", "note": "test", "visibility": "public"}],
        equip_shortbow=True,
    )
    try:
        available = attacks.available_attacks(table.player_actor, hero.id)
        melee_attack = next(a for a in available if a.attack_kind == "melee")
        ranged_attack = next(a for a in available if a.attack_kind == "ranged")

        pending_melee = attacks.request_attack(
            table.player_actor,
            AttackRequestInput(
                attacker_entry_id=hero.id,
                target_entry_id=monster.id,
                source_ref=melee_attack.source_ref,
                idempotency_key="t1-melee-req",
            ),
        )
        resumed_melee = attacks.adjudicate_attack(
            table.dm_actor,
            AttackAdjudicationInput(
                action_id=pending_melee.action_id,
                in_range=True,
                idempotency_key="t1-melee-adj",
            ),
        )
        assert resumed_melee.modifier_mode == "advantage"

        # Check action payload modifier_decision
        stored_action = attacks.adjudication_repository.get_action(
            session_id=table.session_id, action_id=pending_melee.action_id
        )
        assert stored_action is not None
        decision = stored_action.payload.get("modifier_decision")
        assert decision is not None
        assert decision["mode"] == "advantage"
        assert "target:prone" in decision["advantage_sources"]

        # Check combat.adjudication_resolved event payload carries modifier_decision
        with table.engine.connect() as conn:
            row = conn.execute(
                select(session_events).where(
                    session_events.c.session_id == table.session_id,
                    session_events.c.kind == "combat.adjudication_resolved",
                ).order_by(session_events.c.seq.desc())
            ).mappings().first()
            assert row is not None
            assert "modifier_decision" in row["payload"]
            assert row["payload"]["modifier_decision"]["mode"] == "advantage"
            assert "target:prone" in row["payload"]["modifier_decision"]["advantage_sources"]

        # Same setup with ranged attack -> disadvantage
        # Reset attacks_used so hero can attack again on their turn
        with table.engine.begin() as conn:
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == hero.id)
                .values(action_available=True, attacks_used=0)
            )

        pending_ranged = attacks.request_attack(
            table.player_actor,
            AttackRequestInput(
                attacker_entry_id=hero.id,
                target_entry_id=monster.id,
                source_ref=ranged_attack.source_ref,
                idempotency_key="t1-ranged-req",
            ),
        )
        resumed_ranged = attacks.adjudicate_attack(
            table.dm_actor,
            AttackAdjudicationInput(
                action_id=pending_ranged.action_id,
                in_range=True,
                idempotency_key="t1-ranged-adj",
            ),
        )
        assert resumed_ranged.modifier_mode == "disadvantage"
        stored_ranged_action = attacks.adjudication_repository.get_action(
            session_id=table.session_id, action_id=pending_ranged.action_id
        )
        assert stored_ranged_action is not None
        ranged_decision = stored_ranged_action.payload.get("modifier_decision")
        assert ranged_decision is not None
        assert ranged_decision["mode"] == "disadvantage"
        assert "target:prone" in ranged_decision["disadvantage_sources"]
    finally:
        table.engine.dispose()


def test_dm_direct_path_blinded_monster_and_chosen_advantage_cancel() -> None:
    # 2. DM direct path (range_confirmed=True, DM attacking with a blinded Monster attacker)
    # -> modifier_mode == "disadvantage"; DM chooses advantage -> "normal" with both sources recorded.
    table, attacks, _core, hero, monster, monster_id = _running_table(
        monster_conditions=[{"condition_ref": "srd5.1:condition:blinded", "note": "blind", "visibility": "public"}],
        monster_first=True,
    )
    try:
        available = attacks.available_attacks(table.dm_actor, monster.id)
        claw = next(a for a in available if a.name == "Claw")

        # Attack 1: Default modifier_mode (NORMAL) -> effective disadvantage due to blinded
        req1 = attacks.request_attack(
            table.dm_actor,
            AttackRequestInput(
                attacker_entry_id=monster.id,
                target_entry_id=hero.id,
                source_ref=claw.source_ref,
                modifier_mode=RollModifierMode.NORMAL,
                range_confirmed=True,
                idempotency_key="t2-req-1",
            ),
        )
        assert req1.modifier_mode == "disadvantage"
        with table.engine.connect() as conn:
            row = conn.execute(
                select(combat_actions).where(combat_actions.c.id == req1.action_id)
            ).mappings().one()
            dec = row["payload"]["modifier_decision"]
            assert dec["mode"] == "disadvantage"
            assert "attacker:blinded" in dec["disadvantage_sources"]

        # Reset attack budget for monster
        with table.engine.begin() as conn:
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == monster.id)
                .values(action_available=True, attacks_used=0)
            )

        # Attack 2: DM chooses advantage -> cancels with blinded to normal
        req2 = attacks.request_attack(
            table.dm_actor,
            AttackRequestInput(
                attacker_entry_id=monster.id,
                target_entry_id=hero.id,
                source_ref=claw.source_ref,
                modifier_mode=RollModifierMode.ADVANTAGE,
                range_confirmed=True,
                idempotency_key="t2-req-2",
            ),
        )
        assert req2.modifier_mode == "normal"
        with table.engine.connect() as conn:
            row2 = conn.execute(
                select(combat_actions).where(combat_actions.c.id == req2.action_id)
            ).mappings().one()
            dec2 = row2["payload"]["modifier_decision"]
            assert dec2["mode"] == "normal"
            assert "chosen:advantage" in dec2["advantage_sources"]
            assert "attacker:blinded" in dec2["disadvantage_sources"]
    finally:
        table.engine.dispose()


def test_paralyzed_target_melee_critical_hit_and_ranged_plain_hit() -> None:
    # 3. Paralyzed target, melee, DM path, roll a plain hit (raw d20 = 10 vs AC 1)
    # -> resolution critical is True, resolution_result["attack"]["automatic"] is None;
    # same with a ranged attack -> critical is False.
    table, attacks, _core, hero, monster, monster_id = _running_table(
        monster_conditions=[{"condition_ref": "srd5.1:condition:paralyzed", "note": "paralyzed", "visibility": "public"}],
        monster_ac=1,
    )
    try:
        # We need monster AC=1 on target (monster).
        available = attacks.available_attacks(table.player_actor, hero.id)
        melee = next(a for a in available if a.attack_kind == "melee")

        req_melee = attacks.request_attack(
            table.dm_actor,
            AttackRequestInput(
                attacker_entry_id=hero.id,
                target_entry_id=monster.id,
                source_ref=melee.source_ref,
                range_confirmed=True,
                idempotency_key="t3-melee-req",
            ),
        )
        assert req_melee.roll_request_id is not None
        # Complete attack with raw d20 = 10
        res_melee = attacks.complete_attack(
            table.player_actor,
            FormalRollInput(
                roll_request_id=req_melee.roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(10, 10),  # advantage from paralyzed target
                idempotency_key="t3-melee-roll",
            ),
        )
        assert res_melee.hit is True
        assert res_melee.critical is True
        assert res_melee.resolution_result["attack"]["automatic"] is None

        # Now test with ranged attack against paralyzed target -> critical is False
        _equip_ranged_weapon(table)
        with table.engine.begin() as conn:
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == hero.id)
                .values(action_available=True, attacks_used=0)
            )
        available_again = attacks.available_attacks(table.player_actor, hero.id)
        ranged = next(a for a in available_again if a.attack_kind == "ranged")

        req_ranged = attacks.request_attack(
            table.dm_actor,
            AttackRequestInput(
                attacker_entry_id=hero.id,
                target_entry_id=monster.id,
                source_ref=ranged.source_ref,
                range_confirmed=True,
                idempotency_key="t3-ranged-req",
            ),
        )
        assert req_ranged.roll_request_id is not None
        res_ranged = attacks.complete_attack(
            table.player_actor,
            FormalRollInput(
                roll_request_id=req_ranged.roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(10, 10),
                idempotency_key="t3-ranged-roll",
            ),
        )
        assert res_ranged.hit is True
        assert res_ranged.critical is False
        assert res_ranged.resolution_result["attack"]["automatic"] is None
    finally:
        table.engine.dispose()


def test_adjudication_dm_disadvantage_against_paralyzed_cancels_to_normal() -> None:
    # 4. Adjudication with DM roll_mode=disadvantage against a paralyzed target
    # -> "normal" (cancel), decision chosen == "disadvantage".
    table, attacks, _core, hero, monster, _ = _running_table(
        monster_conditions=[{"condition_ref": "srd5.1:condition:paralyzed", "note": "paralyzed", "visibility": "public"}],
    )
    try:
        available = attacks.available_attacks(table.player_actor, hero.id)
        melee = next(a for a in available if a.attack_kind == "melee")

        pending = attacks.request_attack(
            table.player_actor,
            AttackRequestInput(
                attacker_entry_id=hero.id,
                target_entry_id=monster.id,
                source_ref=melee.source_ref,
                idempotency_key="t4-req",
            ),
        )
        resumed = attacks.adjudicate_attack(
            table.dm_actor,
            AttackAdjudicationInput(
                action_id=pending.action_id,
                in_range=True,
                roll_mode=RollMode.DISADVANTAGE,
                idempotency_key="t4-adj",
            ),
        )
        assert resumed.modifier_mode == "normal"
        stored_action = attacks.adjudication_repository.get_action(
            session_id=table.session_id, action_id=pending.action_id
        )
        assert stored_action is not None
        decision = stored_action.payload["modifier_decision"]
        assert decision["chosen"] == "disadvantage"
        assert decision["mode"] == "normal"
        assert "chosen:disadvantage" in decision["disadvantage_sources"]
        assert "target:paralyzed" in decision["advantage_sources"]
    finally:
        table.engine.dispose()


def test_frightened_attacker_records_unresolved() -> None:
    # 5. Frightened attacker -> mode unaffected; the stored modifier_decision.unresolved
    # equals ["attacker:frightened:source_visibility"].
    table, attacks, _core, hero, monster, _ = _running_table(
        character_conditions=[{"condition_ref": "srd5.1:condition:frightened", "note": "scared"}],
    )
    try:
        available = attacks.available_attacks(table.player_actor, hero.id)
        melee = next(a for a in available if a.attack_kind == "melee")

        req = attacks.request_attack(
            table.dm_actor,
            AttackRequestInput(
                attacker_entry_id=hero.id,
                target_entry_id=monster.id,
                source_ref=melee.source_ref,
                range_confirmed=True,
                idempotency_key="t5-req",
            ),
        )
        assert req.modifier_mode == "normal"
        with table.engine.connect() as conn:
            row = conn.execute(
                select(combat_actions).where(combat_actions.c.id == req.action_id)
            ).mappings().one()
            dec = row["payload"]["modifier_decision"]
            assert dec["mode"] == "normal"
            assert dec["unresolved"] == ["attacker:frightened:source_visibility"]
    finally:
        table.engine.dispose()


def test_saving_throws_pipeline_per_target_effective_modes_and_auto_fail_decisions() -> None:
    # 6. Saving throws: one request targeting a restrained Character and a paralyzed Monster
    # with ability dexterity, chosen normal -> Character request modifier_mode == "disadvantage",
    # Monster request "normal" with auto_fail is True and "target:paralyzed" in auto_fail_sources inside the event payload decisions;
    # REST / service view pending rolls shows per-request modes.
    table, _attacks, core_rolls, hero, monster, monster_id = _running_table(
        character_conditions=[{"condition_ref": "srd5.1:condition:restrained", "note": "tied"}],
        monster_conditions=[{"condition_ref": "srd5.1:condition:paralyzed", "note": "stiff", "visibility": "public"}],
    )
    try:
        response = core_rolls.request_saving_throws(
            table.dm_actor,
            SavingThrowInput(
                target_entry_ids=(hero.id, monster.id),
                ability_ref="dexterity",
                dc=15,
                modifier_mode=RollModifierMode.NORMAL,
                idempotency_key="t6-saves",
            ),
        )
        hero_req = next(r for r in response.requests if r.target_entry_id == hero.id)
        monster_req = next(r for r in response.requests if r.target_entry_id == monster.id)

        assert hero_req.modifier_mode is RollModifierMode.DISADVANTAGE
        assert monster_req.modifier_mode is RollModifierMode.NORMAL

        # Assert decisions in event payload
        with table.engine.connect() as conn:
            event = conn.execute(
                select(session_events).where(
                    session_events.c.session_id == table.session_id,
                    session_events.c.kind == "combat.saves_requested",
                ).order_by(session_events.c.seq.desc())
            ).mappings().first()
            assert event is not None
            decisions = event["payload"]["decisions"]
            assert str(hero_req.id) in decisions
            assert str(monster_req.id) in decisions
            monster_dec = decisions[str(monster_req.id)]
            assert monster_dec["auto_fail"] is True
            assert "target:paralyzed" in monster_dec["auto_fail_sources"]
            hero_dec = decisions[str(hero_req.id)]
            assert hero_dec["mode"] == "disadvantage"
            assert "target:restrained" in hero_dec["disadvantage_sources"]

        # Assert list_pending_rolls (DM) reports per-request modes
        pending = core_rolls.list_pending_rolls(table.dm_actor)
        pending_hero = next(p for p in pending if p.id == hero_req.id)
        pending_monster = next(p for p in pending if p.id == monster_req.id)
        assert pending_hero.modifier_mode is RollModifierMode.DISADVANTAGE
        assert pending_monster.modifier_mode is RollModifierMode.NORMAL
    finally:
        table.engine.dispose()


def test_legacy_action_without_modifier_decision_completes_defensively() -> None:
    # 7. Legacy action without modifier_decision still completes (insert the action row the way test_p4c tests do,
    # or monkeypatch the payload) — proves D's defensive read.
    table, attacks, _core, hero, monster, _ = _running_table()
    try:
        available = attacks.available_attacks(table.player_actor, hero.id)
        melee = next(a for a in available if a.attack_kind == "melee")

        req = attacks.request_attack(
            table.dm_actor,
            AttackRequestInput(
                attacker_entry_id=hero.id,
                target_entry_id=monster.id,
                source_ref=melee.source_ref,
                range_confirmed=True,
                idempotency_key="t7-req",
            ),
        )
        assert req.roll_request_id is not None

        # Strip modifier_decision from combat_actions payload to simulate legacy row
        with table.engine.begin() as conn:
            row = conn.execute(
                select(combat_actions).where(combat_actions.c.id == req.action_id)
            ).mappings().one()
            legacy_payload = dict(row["payload"])
            legacy_payload.pop("modifier_decision", None)
            conn.execute(
                update(combat_actions)
                .where(combat_actions.c.id == req.action_id)
                .values(payload=legacy_payload)
            )

        # Complete attack
        result = attacks.complete_attack(
            table.player_actor,
            FormalRollInput(
                roll_request_id=req.roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(15,),
                idempotency_key="t7-roll",
            ),
        )
        assert result.hit is True
        assert result.critical is False
    finally:
        table.engine.dispose()
