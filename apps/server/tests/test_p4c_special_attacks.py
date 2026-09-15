from __future__ import annotations

import pytest
from sqlalchemy import update

from app.content import load_default_content_registry
from app.domain.character.schemas import CharacterState
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, CombatStateConflictError, StartCombatInput
from app.domain.combat.resolution import SpecialAttackKind
from app.domain.combat.special_attacks import (
    CombatSpecialAttackService,
    SpecialAttackAdjudicationInput,
    SpecialAttackRequestInput,
)
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.persistence.characters import CharacterRepository, character_states
from app.persistence.combat.core_rolls import CombatCoreRollRepository
from app.persistence.combat.special_attacks import GRAPPLED_REF, SpecialAttackRepository
import tests.test_p4b_combat_lifecycle as support


PRONE_REF = "srd5.1:condition:prone"


def _unequip_shield(table) -> None:
    registry = load_default_content_registry()
    characters = CharacterRepository(table.engine, registry)
    character = characters.load_character(table.character_id)
    payload = character.state.model_dump(mode="json")
    changed = False
    for item in payload["inventory_state"]:
        if item["item_ref"] == "srd5.1:equipment:shield" and item.get("equipped"):
            item["equipped"] = False
            changed = True
    assert changed
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


def _running_table(*, target_size: str = "Medium", free_hand: bool = False):
    table = support._setup()
    if free_hand:
        _unequip_shield(table)
    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key=f"special-start-{target_size}-{free_hand}"),
    )
    enemy = table.monsters.create_instance(
        campaign_id=table.campaign_id,
        name="Special Target",
        rules_snapshot={
            "armor_class": 12,
            "max_hp": 12,
            "speed": {"walk": "30 ft."},
            "size": target_size,
            "ability_scores": {
                "strength": 10,
                "dexterity": 10,
                "constitution": 10,
                "intelligence": 10,
                "wisdom": 10,
                "charisma": 10,
            },
            "proficiencies": [],
        },
    )
    table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=enemy.id,
            idempotency_key=f"special-enemy-{target_size}-{free_hand}",
        ),
    )
    requested = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key=f"special-init-{target_size}-{free_hand}"),
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
                idempotency_key=f"special-init-roll-{request.id}",
            ),
        )
    order = table.initiative.suggested_order(table.dm_actor)
    running = table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=order,
            idempotency_key=f"special-finalize-{target_size}-{free_hand}",
        ),
    )
    attacker = next(entry for entry in running.entries if entry.character_id == table.character_id)
    target = next(entry for entry in running.entries if entry.monster_instance_id == enemy.id)
    assert running.current_turn_entry_id == attacker.id

    registry = load_default_content_registry()
    characters = CharacterRepository(table.engine, registry)
    service = CombatSpecialAttackService(
        SpecialAttackRepository(table.engine, table.events.repository),
        CombatCoreRollRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        characters,
        table.monsters,
        registry,
        table.rolls,
        table.events,
    )
    return table, service, attacker.id, target.id, enemy.id


def _entry(table, entry_id):
    current = table.combat.get_active_combat(table.dm_actor)
    assert current is not None
    return next(item for item in current.entries if item.id == entry_id)


def _resolve_success(table, service, pending):
    resumed = service.adjudicate_special_attack(
        table.dm_actor,
        SpecialAttackAdjudicationInput(
            action_id=pending.action_id,
            in_reach=True,
            idempotency_key=f"reach-{pending.action_id}",
        ),
    )
    assert resumed.action_id == pending.action_id
    assert resumed.status == "waiting_for_roll"
    assert resumed.attacker_roll_request_id is not None
    assert resumed.defender_roll_request_id is not None

    first = service.complete_special_attack_roll(
        table.player_actor,
        FormalRollInput(
            roll_request_id=resumed.attacker_roll_request_id,
            source=FormalRollSource.PHYSICAL,
            raw_dice=(20,),
            idempotency_key=f"attacker-roll-{pending.action_id}",
        ),
    )
    assert first.status == "waiting_for_roll"

    resolved = service.complete_special_attack_roll(
        table.dm_actor,
        FormalRollInput(
            roll_request_id=resumed.defender_roll_request_id,
            source=FormalRollSource.PHYSICAL,
            raw_dice=(1,),
            idempotency_key=f"defender-roll-{pending.action_id}",
        ),
    )
    assert resolved.status == "resolved"
    assert resolved.resolution_result is not None
    assert resolved.resolution_result["status"] == "success"
    return resumed, resolved


def test_grapple_without_free_hand_is_invalid_and_does_not_spend_attack() -> None:
    table, service, attacker_id, target_id, _monster_id = _running_table(free_hand=False)
    try:
        with pytest.raises(CombatStateConflictError, match="free_hand_required"):
            service.request_special_attack(
                table.player_actor,
                SpecialAttackRequestInput(
                    attacker_entry_id=attacker_id,
                    target_entry_id=target_id,
                    kind=SpecialAttackKind.GRAPPLE,
                    idempotency_key="no-free-hand",
                ),
            )
        attacker = _entry(table, attacker_id)
        assert attacker.action_available is True
        assert attacker.attacks_used == 0
    finally:
        table.engine.dispose()


def test_grapple_pending_survives_reload_then_formal_opposed_roll_applies_condition_once() -> None:
    table, service, attacker_id, target_id, monster_id = _running_table(free_hand=True)
    try:
        pending = service.request_special_attack(
            table.player_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=attacker_id,
                target_entry_id=target_id,
                kind=SpecialAttackKind.GRAPPLE,
                idempotency_key="grapple-pending",
            ),
        )
        assert pending.status == "dm_adjudication_required"
        assert pending.attacker_roll_request_id is None
        assert pending.defender_roll_request_id is None
        before = _entry(table, attacker_id)
        assert before.action_available is True
        assert before.attacks_used == 0

        reloaded = SpecialAttackRepository(table.engine, table.events.repository).get(
            session_id=table.session_id,
            action_id=pending.action_id,
        )
        assert reloaded is not None
        assert reloaded.status == "dm_adjudication_required"

        resumed, resolved = _resolve_success(table, service, pending)
        assert resolved.resolution_result["condition_to_apply"] == "grappled"
        spent = _entry(table, attacker_id)
        assert spent.action_available is False
        assert spent.attacks_used == 1
        monster = table.monsters.get_instance(monster_id)
        assert monster is not None
        refs = {
            condition.get("condition_ref") if isinstance(condition, dict) else condition
            for condition in monster.conditions
        }
        assert GRAPPLED_REF in refs

        duplicate = service.complete_special_attack_roll(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=resumed.defender_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key=f"defender-roll-{pending.action_id}",
            ),
        )
        assert duplicate == resolved
        after_retry = _entry(table, attacker_id)
        assert after_retry.attacks_used == 1
        monster_after_retry = table.monsters.get_instance(monster_id)
        assert monster_after_retry is not None
        grappled = [
            condition
            for condition in monster_after_retry.conditions
            if isinstance(condition, dict) and condition.get("condition_ref") == GRAPPLED_REF
        ]
        assert len(grappled) == 1
    finally:
        table.engine.dispose()


def test_shove_prone_uses_same_formal_flow_and_applies_prone() -> None:
    table, service, attacker_id, target_id, monster_id = _running_table(free_hand=False)
    try:
        pending = service.request_special_attack(
            table.player_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=attacker_id,
                target_entry_id=target_id,
                kind=SpecialAttackKind.SHOVE_PRONE,
                idempotency_key="shove-prone",
            ),
        )
        _resumed, resolved = _resolve_success(table, service, pending)
        assert resolved.resolution_result["condition_to_apply"] == "prone"
        monster = table.monsters.get_instance(monster_id)
        assert monster is not None
        refs = {
            condition.get("condition_ref") if isinstance(condition, dict) else condition
            for condition in monster.conditions
        }
        assert PRONE_REF in refs
    finally:
        table.engine.dispose()


def test_too_large_target_is_invalid_before_geometry_and_spends_nothing() -> None:
    table, service, attacker_id, target_id, _monster_id = _running_table(target_size="Huge", free_hand=True)
    try:
        with pytest.raises(CombatStateConflictError, match="target_too_large"):
            service.request_special_attack(
                table.player_actor,
                SpecialAttackRequestInput(
                    attacker_entry_id=attacker_id,
                    target_entry_id=target_id,
                    kind=SpecialAttackKind.SHOVE_PUSH,
                    idempotency_key="too-large",
                ),
            )
        attacker = _entry(table, attacker_id)
        assert attacker.action_available is True
        assert attacker.attacks_used == 0
    finally:
        table.engine.dispose()


def test_out_of_reach_adjudication_resolves_without_consuming_attack() -> None:
    table, service, attacker_id, target_id, _monster_id = _running_table(free_hand=True)
    try:
        pending = service.request_special_attack(
            table.player_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=attacker_id,
                target_entry_id=target_id,
                kind=SpecialAttackKind.SHOVE_PUSH,
                idempotency_key="push-out-of-reach",
            ),
        )
        rejected = service.adjudicate_special_attack(
            table.dm_actor,
            SpecialAttackAdjudicationInput(
                action_id=pending.action_id,
                in_reach=False,
                idempotency_key="push-rejected",
            ),
        )
        assert rejected.status == "resolved"
        assert rejected.resolution_result == {
            "status": "invalid",
            "reason": "out_of_reach",
            "kind": "shove_push",
        }
        attacker = _entry(table, attacker_id)
        assert attacker.action_available is True
        assert attacker.attacks_used == 0
    finally:
        table.engine.dispose()
