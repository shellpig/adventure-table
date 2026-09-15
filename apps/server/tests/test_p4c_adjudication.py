from __future__ import annotations

import pytest

from app.content import load_default_content_registry
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.attacks import (
    AttackAdjudicationInput,
    AttackRequestInput,
    CombatAttackService,
)
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.combat.semantic_hp import CombatResolutionService, SemanticDamageInput
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.persistence.characters import CharacterRepository
from app.persistence.combat.adjudication import CombatAdjudicationRepository
from app.persistence.combat.attacks import CombatAttackRepository
from app.persistence.combat.resolution import CombatResolutionRepository
import tests.test_p4b_combat_lifecycle as support


def _running_table():
    table = support._setup()
    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key="p4c-adjudication-start"),
    )
    enemy = support._quick_enemy(table, "Range Target")
    table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=enemy.id,
            idempotency_key="p4c-adjudication-enemy",
        ),
    )
    requested = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="p4c-adjudication-init"),
    )
    for request in requested.requests:
        actor = table.player_actor if request.target_seat_id is not None else table.dm_actor
        raw = 20 if request.target_seat_id is not None else 1
        table.initiative.complete_initiative(
            actor,
            FormalRollInput(
                roll_request_id=request.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(raw,),
                idempotency_key=f"p4c-adjudication-init-{request.id}",
            ),
        )
    order = table.initiative.suggested_order(table.dm_actor)
    running = table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=order,
            idempotency_key="p4c-adjudication-finalize",
        ),
    )
    attacker = next(entry for entry in running.entries if entry.character_id == table.character_id)
    target = next(entry for entry in running.entries if entry.monster_instance_id == enemy.id)
    assert running.current_turn_entry_id == attacker.id

    registry = load_default_content_registry()
    characters = CharacterRepository(table.engine, registry)
    attacks = CombatAttackService(
        CombatAttackRepository(table.engine, table.events.repository),
        CombatAdjudicationRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        AttackDefinitionResolver(characters, table.monsters, registry),
        table.rolls,
        table.events,
    )
    available = attacks.available_attacks(table.player_actor, attacker.id)
    assert available
    source_ref = available[0].source_ref
    return table, attacks, attacker.id, target.id, source_ref


def _entry(table, entry_id):
    current = table.combat.get_active_combat(table.dm_actor)
    assert current is not None
    return next(item for item in current.entries if item.id == entry_id)


def test_player_geometry_claim_stays_pending_and_survives_repository_reload() -> None:
    table, attacks, attacker_id, target_id, source_ref = _running_table()
    try:
        pending = attacks.request_attack(
            table.player_actor,
            AttackRequestInput(
                attacker_entry_id=attacker_id,
                target_entry_id=target_id,
                source_ref=source_ref,
                # A Player assertion is not authoritative in Quick Combat.
                range_confirmed=True,
                idempotency_key="pending-range",
            ),
        )
        assert pending.status == "dm_adjudication_required"
        assert pending.roll_request_id is None
        assert pending.in_range is None
        before = _entry(table, attacker_id)
        assert before.action_available is True
        assert before.attacks_used == 0

        # New repository instance proves the pending state is DB durable rather
        # than stored in the original service process.
        reloaded = CombatAdjudicationRepository(
            table.engine,
            table.events.repository,
        ).get(session_id=table.session_id, action_id=pending.action_id)
        assert reloaded is not None
        assert reloaded.status == "dm_adjudication_required"
        assert reloaded.roll_request_id is None

        rejected = attacks.adjudicate_attack(
            table.dm_actor,
            AttackAdjudicationInput(
                action_id=pending.action_id,
                in_range=False,
                idempotency_key="range-reject",
            ),
        )
        assert rejected.action_id == pending.action_id
        assert rejected.status == "resolved"
        assert rejected.roll_request_id is None
        assert rejected.resolution_result == {
            "status": "invalid",
            "reason": "out_of_range",
        }
        after = _entry(table, attacker_id)
        assert after.action_available is True
        assert after.attacks_used == 0
    finally:
        table.engine.dispose()


def test_dm_in_range_resumes_same_action_then_formal_roll_resolves_it() -> None:
    table, attacks, attacker_id, target_id, source_ref = _running_table()
    try:
        pending = attacks.request_attack(
            table.player_actor,
            AttackRequestInput(
                attacker_entry_id=attacker_id,
                target_entry_id=target_id,
                source_ref=source_ref,
                idempotency_key="pending-resume",
            ),
        )
        resumed = attacks.adjudicate_attack(
            table.dm_actor,
            AttackAdjudicationInput(
                action_id=pending.action_id,
                in_range=True,
                idempotency_key="range-accept",
            ),
        )
        assert resumed.action_id == pending.action_id
        assert resumed.status == "waiting_for_roll"
        assert resumed.roll_request_id is not None
        assert resumed.in_range is True
        spent = _entry(table, attacker_id)
        assert spent.action_available is False
        assert spent.attacks_used == 1

        result = attacks.complete_attack(
            table.player_actor,
            FormalRollInput(
                roll_request_id=resumed.roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="attack-after-adjudication",
            ),
        )
        assert result.action_id == pending.action_id
        assert result.hit is True
        assert result.critical is True
        assert result.damage_total > 0

        # Retry returns the canonical result and cannot consume a second Attack.
        duplicate = attacks.complete_attack(
            table.player_actor,
            FormalRollInput(
                roll_request_id=resumed.roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(1,),
                idempotency_key="attack-after-adjudication",
            ),
        )
        assert duplicate == result
        after_retry = _entry(table, attacker_id)
        assert after_retry.attacks_used == 1
    finally:
        table.engine.dispose()


def test_player_cannot_operate_enemy_combatant_or_directly_mutate_enemy_hp() -> None:
    table, attacks, attacker_id, target_id, _source_ref = _running_table()
    try:
        with pytest.raises(TableEventActorUnauthorizedError):
            attacks.request_attack(
                table.player_actor,
                AttackRequestInput(
                    attacker_entry_id=target_id,
                    target_entry_id=attacker_id,
                    source_ref="authorization-must-fail-before-definition-resolution",
                    range_confirmed=True,
                    idempotency_key="player-cannot-drive-enemy",
                ),
            )

        resolution = CombatResolutionService(
            CombatResolutionRepository(table.engine, table.events.repository),
            table.combat.repository,
            table.combat,
            table.events,
        )
        with pytest.raises(TableEventActorUnauthorizedError):
            resolution.apply_damage(
                table.player_actor,
                SemanticDamageInput(
                    target_entry_id=target_id,
                    amount=1,
                    idempotency_key="player-cannot-direct-damage-enemy",
                ),
            )
    finally:
        table.engine.dispose()
