from __future__ import annotations

import pytest

from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, CombatStateConflictError, StartCombatInput
from app.domain.combat.order import ReorderInitiativeInput
from tests.test_p4b_combat_lifecycle import _complete_request, _quick_enemy, _setup


def test_dm_can_only_adjudicate_ties_not_override_initiative_totals() -> None:
    table = _setup()
    try:
        pending = table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="start"),
        )
        original_character = next(
            entry for entry in pending.entries if entry.character_id == table.character_id
        )
        slow_monster = _quick_enemy(table, "Slow Guard")
        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=slow_monster.id, idempotency_key="slow"),
        )

        requested = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(idempotency_key="initial"),
        )
        for request in requested.requests:
            raw = 10 if request.target_character_id is not None else 5
            _complete_request(table, request, raw, f"initial-{request.id}")

        canonical = table.initiative.suggested_order(table.dm_actor)
        assert canonical[0] == original_character.id
        with pytest.raises(CombatStateConflictError, match="tied totals"):
            table.initiative.finalize_initiative(
                table.dm_actor,
                FinalizeInitiativeInput(
                    ordered_entry_ids=tuple(reversed(canonical)),
                    idempotency_key="invalid-total-override",
                ),
            )

        running = table.initiative.finalize_initiative(
            table.dm_actor,
            FinalizeInitiativeInput(
                ordered_entry_ids=canonical,
                idempotency_key="canonical-finalize",
            ),
        )
        assert running.current_turn_entry_id == original_character.id

        fast_a = _quick_enemy(table, "Fast A")
        fast_b = _quick_enemy(table, "Fast B")
        fast_entries = []
        for suffix, monster in (("a", fast_a), ("b", fast_b)):
            state = table.combat.add_monster(
                table.dm_actor,
                AddMonsterInput(
                    monster_instance_id=monster.id,
                    idempotency_key=f"add-{suffix}",
                ),
            )
            entry = next(
                item for item in state.entries if item.monster_instance_id == monster.id
            )
            fast_entries.append(entry)
            request = table.initiative.request_initiative(
                table.dm_actor,
                RequestInitiativeInput(
                    entry_ids=(entry.id,),
                    idempotency_key=f"request-{suffix}",
                ),
            ).requests[0]
            _complete_request(table, request, 20, f"fast-{suffix}")

        # Appending high-initiative entrants at the end would rewrite non-tie order.
        current_storage_order = tuple(
            entry.id for entry in table.combat.get_active_combat(table.dm_actor).entries
        )
        with pytest.raises(CombatStateConflictError, match="tied totals"):
            table.order.reorder_running(
                table.dm_actor,
                ReorderInitiativeInput(
                    ordered_entry_ids=current_storage_order,
                    idempotency_key="invalid-running-override",
                ),
            )

        canonical_running = list(table.initiative.suggested_order(table.dm_actor))
        fast_ids = {entry.id for entry in fast_entries}
        fast_positions = [
            index for index, entry_id in enumerate(canonical_running) if entry_id in fast_ids
        ]
        assert len(fast_positions) == 2
        first, second = fast_positions
        canonical_running[first], canonical_running[second] = (
            canonical_running[second],
            canonical_running[first],
        )
        tied_order = tuple(canonical_running)

        reordered = table.order.reorder_running(
            table.dm_actor,
            ReorderInitiativeInput(
                ordered_entry_ids=tied_order,
                idempotency_key="valid-tie-adjudication",
            ),
        )
        assert tuple(entry.id for entry in reordered.entries) == tied_order
        assert reordered.current_turn_entry_id == original_character.id
    finally:
        table.engine.dispose()
