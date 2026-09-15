from __future__ import annotations

from app.domain.combat.core_rolls import (
    CombatCoreRollService,
    DeathSaveRequestInput,
    SavingThrowInput,
)
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.combat.resolution import DamageType
from app.domain.combat.semantic_hp import CombatResolutionService, SemanticDamageInput
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.persistence.characters import CharacterRepository
from app.persistence.combat.core_rolls import CombatCoreRollRepository
from app.persistence.combat.resolution import CombatResolutionRepository, UNCONSCIOUS_REF
import tests.test_p4b_combat_lifecycle as support


def _running_table():
    table = support._setup()
    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key="p4c-core-roll-start"),
    )
    enemy = support._quick_enemy(table, "Save Target")
    combat = table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=enemy.id,
            idempotency_key="p4c-core-roll-enemy",
        ),
    )
    requested = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="p4c-core-roll-init"),
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
                idempotency_key=f"p4c-core-roll-init-{request.id}",
            ),
        )
    order = table.initiative.suggested_order(table.dm_actor)
    running = table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=order,
            idempotency_key="p4c-core-roll-finalize",
        ),
    )
    character_entry = next(
        item for item in running.entries if item.character_id == table.character_id
    )
    monster_entry = next(
        item for item in running.entries if item.monster_instance_id == enemy.id
    )
    assert running.current_turn_entry_id == character_entry.id

    core = CombatCoreRollService(
        CombatCoreRollRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        table.monsters,
        table.rolls,
        table.events,
    )
    semantic = CombatResolutionService(
        CombatResolutionRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        table.events,
    )
    return table, core, semantic, character_entry.id, monster_entry.id


def test_multi_target_formal_saving_throw_uses_character_and_monster_modifiers() -> None:
    table, core, _semantic, character_entry_id, monster_entry_id = _running_table()
    try:
        requested = core.request_saving_throws(
            table.dm_actor,
            SavingThrowInput(
                target_entry_ids=(character_entry_id, monster_entry_id),
                ability_ref="dexterity",
                dc=12,
                idempotency_key="multi-save",
            ),
        )
        assert len(requested.requests) == 2
        character_request = next(
            item for item in requested.requests if item.target_character_id == table.character_id
        )
        monster_request = next(
            item for item in requested.requests if item.target_character_id is None
        )
        assert character_request.modifier == 2
        assert monster_request.modifier == 0
        assert character_request.dc == 12

        character_result = core.complete_saving_throw(
            table.player_actor,
            FormalRollInput(
                roll_request_id=character_request.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(10,),
                idempotency_key="character-save",
            ),
        )
        assert character_result.total == 12
        assert character_result.succeeded is True

        monster_result = core.complete_saving_throw(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=monster_request.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(11,),
                idempotency_key="monster-save",
            ),
        )
        assert monster_result.total == 11
        assert monster_result.succeeded is False

        # Combat formal rolls stay isolated from the legacy P3 Check projection.
        assert table.rolls.list_requests(table.dm_actor) == ()
    finally:
        table.engine.dispose()


def test_formal_death_save_nat20_atomically_recovers_hp_and_retry_is_idempotent() -> None:
    table, core, semantic, character_entry_id, _monster_entry_id = _running_table()
    try:
        downed = semantic.apply_damage(
            table.player_actor,
            SemanticDamageInput(
                target_entry_id=character_entry_id,
                amount=74,
                damage_type=DamageType.UNTYPED,
                idempotency_key="down-character",
            ),
        )
        assert downed.after_hp == 0

        requested = core.request_death_save(
            table.player_actor,
            DeathSaveRequestInput(
                entry_id=character_entry_id,
                idempotency_key="death-save-request",
            ),
        )
        result = core.complete_death_save(
            table.player_actor,
            FormalRollInput(
                roll_request_id=requested.roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="death-save-result",
            ),
        )
        assert result.d20 == 20
        assert result.current_hp == 1
        assert result.successes == 0
        assert result.failures == 0
        assert result.stable is False
        assert result.dead is False
        assert result.natural_20_recovery is True

        duplicate = core.complete_death_save(
            table.player_actor,
            FormalRollInput(
                roll_request_id=requested.roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(1,),
                idempotency_key="death-save-result",
            ),
        )
        assert duplicate == result

        character = CharacterRepository(
            table.engine,
            table.combat.character_repository.registry,
        ).load_character(table.character_id)
        assert character.state.current_hp == 1
        assert all(
            condition.condition_ref != UNCONSCIOUS_REF
            for condition in character.state.conditions
        )
    finally:
        table.engine.dispose()
