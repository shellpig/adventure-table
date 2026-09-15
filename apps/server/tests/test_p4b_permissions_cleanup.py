from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    CombatActionInput,
    CombatActionKind,
    CombatEconomyCost,
    StartCombatInput,
)
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from tests.test_p4b_combat_lifecycle import _complete_request, _quick_enemy, _setup


def test_only_current_dm_controls_combat_lifecycle_and_mode_is_fixed_quick() -> None:
    table = _setup()
    try:
        with pytest.raises(TableEventActorUnauthorizedError):
            table.combat.start_quick_combat(
                table.player_actor,
                StartCombatInput(idempotency_key="player-start"),
            )

        started = table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="dm-start"),
        )
        assert started.mode == "quick"
        with pytest.raises(ValidationError):
            StartCombatInput.model_validate({"mode": "tactical"})

        with pytest.raises(TableEventActorUnauthorizedError):
            table.combat.end_combat(table.player_actor, idempotency_key="player-end")
    finally:
        table.engine.dispose()


def test_end_combat_clears_only_combat_bookkeeping() -> None:
    table = _setup()
    try:
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="start"),
        )
        monster = _quick_enemy(table, "Surprised Guard")
        pending = table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(
                monster_instance_id=monster.id,
                surprised=True,
                idempotency_key="monster",
            ),
        )
        requests = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(idempotency_key="initiative"),
        )
        for index, request in enumerate(requests.requests):
            _complete_request(table, request, 15 - index, f"cleanup-{index}")
        running = table.initiative.finalize_initiative(
            table.dm_actor,
            FinalizeInitiativeInput(
                ordered_entry_ids=table.initiative.suggested_order(table.dm_actor),
                idempotency_key="finalize",
            ),
        )
        table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=running.current_turn_entry_id,
                action_kind=CombatActionKind.READY,
                economy_cost=CombatEconomyCost.ACTION,
                payload={"intent": "hold position"},
                idempotency_key="ready",
            ),
        )

        ended = table.combat.end_combat(table.dm_actor, idempotency_key="end")
        assert ended.status == "ended"
        assert ended.round_number is None
        assert ended.current_turn_entry_id is None
        for entry in ended.entries:
            assert entry.initiative_roll_request_id is None
            assert entry.initiative_roll_result_id is None
            assert entry.initiative_total is None
            assert entry.turn_order is None
            assert entry.surprised is False
            assert entry.action_available is True
            assert entry.bonus_action_available is True
            assert entry.reaction_available is True
            assert entry.attacks_used == 0
            assert entry.ready_state == {}
            assert entry.pending_reaction_state == {}

        # Persistent Monster live state is not reset by ending Combat.
        persisted_monster = table.monsters.get_instance(monster.id)
        assert persisted_monster is not None
        assert persisted_monster.current_hp == 9
        assert persisted_monster.combat_status == "active"
    finally:
        table.engine.dispose()
