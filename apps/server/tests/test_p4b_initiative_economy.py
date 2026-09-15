from __future__ import annotations

import pytest
from sqlalchemy import select

from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    CombatActionInput,
    CombatActionKind,
    CombatEconomyCost,
    CombatStateConflictError,
    ReactionWindowInput,
    StartCombatInput,
)
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource, RollModifierMode
from app.persistence.rooms.p3c_runtime import roll_results
from tests.test_p4b_combat_lifecycle import _quick_enemy, _setup


def _physical(table, request, raw_dice: tuple[int, ...], key: str):
    actor = table.dm_actor if request.target_seat_id is None else table.player_actor
    return table.initiative.complete_initiative(
        actor,
        FormalRollInput(
            roll_request_id=request.id,
            source=FormalRollSource.PHYSICAL,
            raw_dice=raw_dice,
            idempotency_key=key,
        ),
    )


def test_initiative_advantage_disadvantage_and_roll_audit_are_canonical() -> None:
    table = _setup()
    try:
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(include_active_party=False, idempotency_key="start"),
        )
        monster_a = _quick_enemy(table, "Advantage Monster")
        monster_b = _quick_enemy(table, "Disadvantage Monster")
        state = table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=monster_a.id, idempotency_key="a"),
        )
        state = table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=monster_b.id, idempotency_key="b"),
        )
        entry_a = next(entry for entry in state.entries if entry.monster_instance_id == monster_a.id)
        entry_b = next(entry for entry in state.entries if entry.monster_instance_id == monster_b.id)

        advantage = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(
                entry_ids=(entry_a.id,),
                modifier_mode=RollModifierMode.ADVANTAGE,
                idempotency_key="adv-request",
            ),
        ).requests[0]
        disadvantage = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(
                entry_ids=(entry_b.id,),
                modifier_mode=RollModifierMode.DISADVANTAGE,
                idempotency_key="dis-request",
            ),
        ).requests[0]

        adv_result = _physical(table, advantage, (2, 17), "adv-result")
        dis_result = _physical(table, disadvantage, (2, 17), "dis-result")
        assert adv_result.total == 17
        assert dis_result.total == 2

        with table.engine.connect() as connection:
            rows = {
                row["id"]: row
                for row in connection.execute(
                    select(roll_results).where(
                        roll_results.c.id.in_((adv_result.result_id, dis_result.result_id))
                    )
                ).mappings()
            }
        assert rows[adv_result.result_id]["raw_dice"] == [2, 17]
        assert rows[adv_result.result_id]["kept_dice"] == [17]
        assert rows[adv_result.result_id]["formula"].startswith("2d20kh1")
        assert rows[adv_result.result_id]["subject_combat_entry_id"] == entry_a.id
        assert rows[dis_result.result_id]["raw_dice"] == [2, 17]
        assert rows[dis_result.result_id]["kept_dice"] == [2]
        assert rows[dis_result.result_id]["formula"].startswith("2d20kl1")
        assert rows[dis_result.result_id]["subject_combat_entry_id"] == entry_b.id
    finally:
        table.engine.dispose()


def test_turn_action_bonus_reaction_extra_attack_and_round_refresh() -> None:
    table = _setup()
    try:
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="start"),
        )
        monster = _quick_enemy(table, "Goblin")
        pending = table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=monster.id, idempotency_key="monster"),
        )
        character_entry = next(entry for entry in pending.entries if entry.character_id == table.character_id)
        monster_entry = next(entry for entry in pending.entries if entry.monster_instance_id == monster.id)
        assert character_entry.attacks_allowed == 2  # Fighter 5 fixture.

        requested = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(idempotency_key="initiative"),
        )
        for request in requested.requests:
            raw = (20,) if request.target_character_id is not None else (1,)
            _physical(table, request, raw, f"roll-{request.id}")
        order = table.initiative.suggested_order(table.dm_actor)
        assert order[0] == character_entry.id
        running = table.initiative.finalize_initiative(
            table.dm_actor,
            FinalizeInitiativeInput(ordered_entry_ids=order, idempotency_key="finalize"),
        )
        assert running.round_number == 1
        assert running.current_turn_entry_id == character_entry.id

        first_attack = table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=character_entry.id,
                action_kind=CombatActionKind.ATTACK_BUDGET,
                economy_cost=CombatEconomyCost.ACTION,
                idempotency_key="attack-1",
            ),
        )
        assert first_attack.execution_mode == "dm_proxy"
        assert first_attack.subject_seat_id == table.player_seat_id
        second_attack = table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=character_entry.id,
                action_kind=CombatActionKind.ATTACK_BUDGET,
                economy_cost=CombatEconomyCost.ACTION,
                idempotency_key="attack-2",
            ),
        )
        assert second_attack.execution_mode == "dm_proxy"
        state = table.combat.get_active_combat(table.dm_actor)
        current = next(entry for entry in state.entries if entry.id == character_entry.id)
        assert current.action_available is False
        assert current.attacks_used == 2
        with pytest.raises(CombatStateConflictError):
            table.combat.use_action(
                table.dm_actor,
                CombatActionInput(
                    entry_id=character_entry.id,
                    action_kind=CombatActionKind.ATTACK_BUDGET,
                    economy_cost=CombatEconomyCost.ACTION,
                    idempotency_key="attack-3",
                ),
            )

        table.combat.use_action(
            table.player_actor,
            CombatActionInput(
                entry_id=character_entry.id,
                action_kind=CombatActionKind.FREEFORM,
                economy_cost=CombatEconomyCost.BONUS_ACTION,
                idempotency_key="bonus-1",
            ),
        )
        with pytest.raises(CombatStateConflictError):
            table.combat.use_action(
                table.player_actor,
                CombatActionInput(
                    entry_id=character_entry.id,
                    action_kind=CombatActionKind.FREEFORM,
                    economy_cost=CombatEconomyCost.BONUS_ACTION,
                    idempotency_key="bonus-2",
                ),
            )

        monster_turn = table.combat.advance_turn(table.dm_actor, idempotency_key="to-monster")
        assert monster_turn.current_turn_entry_id == monster_entry.id
        with pytest.raises(CombatStateConflictError):
            table.combat.use_action(
                table.player_actor,
                CombatActionInput(
                    entry_id=character_entry.id,
                    action_kind=CombatActionKind.ATTACK_BUDGET,
                    economy_cost=CombatEconomyCost.ACTION,
                    idempotency_key="wrong-turn-attack",
                ),
            )

        table.combat.set_reaction_window(
            table.dm_actor,
            ReactionWindowInput(
                entry_id=character_entry.id,
                open=True,
                reason="test reaction",
                source_entry_id=monster_entry.id,
                idempotency_key="reaction-window",
            ),
        )
        table.combat.use_action(
            table.player_actor,
            CombatActionInput(
                entry_id=character_entry.id,
                action_kind=CombatActionKind.FREEFORM,
                economy_cost=CombatEconomyCost.REACTION,
                idempotency_key="reaction",
            ),
        )
        with pytest.raises(CombatStateConflictError):
            table.combat.use_action(
                table.player_actor,
                CombatActionInput(
                    entry_id=character_entry.id,
                    action_kind=CombatActionKind.FREEFORM,
                    economy_cost=CombatEconomyCost.REACTION,
                    idempotency_key="reaction-twice",
                ),
            )

        disengage = table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=monster_entry.id,
                action_kind=CombatActionKind.DISENGAGE,
                economy_cost=CombatEconomyCost.ACTION,
                idempotency_key="disengage",
            ),
        )
        assert disengage.payload == {}
        assert all("movement" not in key for key in disengage.payload)

        round_two = table.combat.advance_turn(table.dm_actor, idempotency_key="round-two")
        assert round_two.round_number == 2
        assert round_two.current_turn_entry_id == character_entry.id
        refreshed = next(entry for entry in round_two.entries if entry.id == character_entry.id)
        assert refreshed.action_available is True
        assert refreshed.bonus_action_available is True
        assert refreshed.reaction_available is True
        assert refreshed.attacks_used == 0

        dash = table.combat.use_action(
            table.player_actor,
            CombatActionInput(
                entry_id=character_entry.id,
                action_kind=CombatActionKind.DASH,
                economy_cost=CombatEconomyCost.ACTION,
                idempotency_key="dash",
            ),
        )
        assert dash.payload == {}
        assert all("movement" not in key for key in dash.payload)
    finally:
        table.engine.dispose()
