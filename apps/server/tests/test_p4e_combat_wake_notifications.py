"""P4-E E12: Combat lifecycle mutations must wake long-poll event waiters.

The Session page and AI ``wait_for_event`` both sit on ``GET .../events/wait``;
without a notifier hint after each Combat mutation, other participants only
see Start / add enemy / advance turn / End after the 30 s long-poll timeout.
"""

from __future__ import annotations

from uuid import UUID

from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    CombatActionInput,
    CombatActionKind,
    CombatEconomyCost,
    StartCombatInput,
)
from app.domain.combat.order import ReorderInitiativeInput
from tests.test_p4b_combat_lifecycle import _complete_request, _quick_enemy, _setup


class RecordingNotifier:
    def __init__(self) -> None:
        self.notified: list[UUID] = []

    def notify(self, session_id: UUID) -> None:
        self.notified.append(session_id)

    def register(self, session_id: UUID):  # pragma: no cover - never awaited here
        raise AssertionError("register is not exercised by this test")


def test_combat_lifecycle_mutations_notify_event_waiters() -> None:
    table = _setup()
    notifier = RecordingNotifier()
    table.events.notifier = notifier
    try:
        def expect_wake(step: str) -> None:
            assert notifier.notified, f"{step} did not wake event waiters"
            assert notifier.notified[-1] == table.session_id
            notifier.notified.clear()

        table.combat.start_quick_combat(table.dm_actor, StartCombatInput(idempotency_key="start"))
        expect_wake("start_quick_combat")

        enemy = _quick_enemy(table, "Goblin")
        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=enemy.id, idempotency_key="add-goblin"),
        )
        expect_wake("add_monster")

        requests = table.initiative.request_initiative(
            table.dm_actor, RequestInitiativeInput(idempotency_key="initiative"),
        )
        expect_wake("request_initiative")
        for index, request in enumerate(requests.requests):
            _complete_request(table, request, 15 - index, f"init-{index}")
        expect_wake("complete_initiative")

        ordered = table.initiative.suggested_order(table.dm_actor)
        running = table.initiative.finalize_initiative(
            table.dm_actor,
            FinalizeInitiativeInput(ordered_entry_ids=ordered, idempotency_key="finalize"),
        )
        expect_wake("finalize_initiative")

        table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=running.current_turn_entry_id,
                action_kind=CombatActionKind.DODGE,
                economy_cost=CombatEconomyCost.ACTION,
                idempotency_key="dodge",
            ),
        )
        expect_wake("use_action")

        table.combat.advance_turn(table.dm_actor, idempotency_key="advance")
        expect_wake("advance_turn")

        table.order.reorder_running(
            table.dm_actor,
            # Same order: the wake hint matters here, not the permutation rules (P4-B covers those).
            ReorderInitiativeInput(ordered_entry_ids=ordered, idempotency_key="reorder"),
        )
        expect_wake("reorder_running")

        current = table.combat.get_active_combat(table.dm_actor)
        assert current is not None
        idle_entry = next(entry for entry in current.entries if entry.id != current.current_turn_entry_id)
        table.combat.withdraw_entry(table.dm_actor, idle_entry.id, idempotency_key="withdraw")
        expect_wake("withdraw_entry")

        table.combat.end_combat(table.dm_actor, idempotency_key="end")
        expect_wake("end_combat")
    finally:
        table.engine.dispose()
