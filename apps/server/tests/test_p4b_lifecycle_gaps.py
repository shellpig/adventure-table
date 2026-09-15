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
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.persistence.combat.tables import combat_entries
from tests.test_p4b_combat_lifecycle import _complete_request, _quick_enemy, _setup


def _finalize_single_monster(table, *, surprised: bool):
    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(include_active_party=False, idempotency_key="start"),
    )
    monster = _quick_enemy(table, "Guard")
    pending = table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=monster.id,
            surprised=surprised,
            idempotency_key="monster",
        ),
    )
    entry = next(item for item in pending.entries if item.monster_instance_id == monster.id)
    requested = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="initiative"),
    )
    assert len(requested.requests) == 1
    _complete_request(table, requested.requests[0], 12, "monster")
    running = table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=(entry.id,),
            idempotency_key="finalize",
        ),
    )
    return entry, running


def test_surprise_blocks_first_turn_economy_and_clears_when_own_turn_ends() -> None:
    table = _setup()
    try:
        entry, running = _finalize_single_monster(table, surprised=True)
        assert running.round_number == 1
        assert running.current_turn_entry_id == entry.id
        current = next(item for item in running.entries if item.id == entry.id)
        assert current.surprised is True
        assert current.reaction_available is False

        with pytest.raises(CombatStateConflictError, match="Surprised combatant"):
            table.combat.use_action(
                table.dm_actor,
                CombatActionInput(
                    entry_id=entry.id,
                    action_kind=CombatActionKind.DODGE,
                    economy_cost=CombatEconomyCost.ACTION,
                    idempotency_key="surprised-action",
                ),
            )

        with pytest.raises(CombatStateConflictError, match="Surprised combatant"):
            table.combat.use_action(
                table.dm_actor,
                CombatActionInput(
                    entry_id=entry.id,
                    action_kind=CombatActionKind.FREEFORM,
                    economy_cost=CombatEconomyCost.BONUS_ACTION,
                    idempotency_key="surprised-bonus",
                ),
            )

        table.combat.set_reaction_window(
            table.dm_actor,
            ReactionWindowInput(
                entry_id=entry.id,
                open=True,
                reason="enemy moves",
                idempotency_key="surprised-window",
            ),
        )
        with pytest.raises(CombatStateConflictError, match="Reaction is unavailable"):
            table.combat.use_action(
                table.dm_actor,
                CombatActionInput(
                    entry_id=entry.id,
                    action_kind=CombatActionKind.FREEFORM,
                    economy_cost=CombatEconomyCost.REACTION,
                    idempotency_key="surprised-reaction",
                ),
            )

        round_two = table.combat.advance_turn(table.dm_actor, idempotency_key="end-first-turn")
        assert round_two.round_number == 2
        refreshed = next(item for item in round_two.entries if item.id == entry.id)
        assert refreshed.surprised is False
        assert refreshed.action_available is True
        assert refreshed.bonus_action_available is True
        assert refreshed.reaction_available is True
        assert refreshed.pending_reaction_state == {}

        # This specifically exercises the window guard while reaction economy is
        # otherwise available. The older regression only exercised the spent-reaction guard.
        with pytest.raises(CombatStateConflictError, match="No reaction window is open"):
            table.combat.use_action(
                table.dm_actor,
                CombatActionInput(
                    entry_id=entry.id,
                    action_kind=CombatActionKind.FREEFORM,
                    economy_cost=CombatEconomyCost.REACTION,
                    idempotency_key="no-window-reaction",
                ),
            )

        action = table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=entry.id,
                action_kind=CombatActionKind.DODGE,
                economy_cost=CombatEconomyCost.ACTION,
                idempotency_key="post-surprise-action",
            ),
        )
        assert action.entry_id == entry.id
    finally:
        table.engine.dispose()


def test_withdraw_remove_and_no_hostile_warning_do_not_auto_end_combat() -> None:
    table = _setup()
    try:
        started = table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="start"),
        )
        assert started.status == "initiative_pending"
        assert started.warnings == ("no_hostile_combatants",)

        monster_a = _quick_enemy(table, "Goblin A")
        monster_b = _quick_enemy(table, "Goblin B")
        state = table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=monster_a.id, idempotency_key="a"),
        )
        state = table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=monster_b.id, idempotency_key="b"),
        )
        assert state.warnings == ()
        entry_a = next(item for item in state.entries if item.monster_instance_id == monster_a.id)
        entry_b = next(item for item in state.entries if item.monster_instance_id == monster_b.id)

        withdrawn = table.combat.withdraw_entry(
            table.dm_actor,
            entry_a.id,
            idempotency_key="withdraw-a",
        )
        assert next(item for item in withdrawn.entries if item.id == entry_a.id).status == "withdrawn"
        assert withdrawn.status == "initiative_pending"
        assert withdrawn.warnings == ()

        removed = table.combat.remove_entry(
            table.dm_actor,
            entry_b.id,
            idempotency_key="remove-b",
        )
        assert next(item for item in removed.entries if item.id == entry_b.id).status == "removed"
        assert removed.status == "initiative_pending"
        assert removed.warnings == ("no_hostile_combatants",)
        assert table.combat.get_active_combat(table.dm_actor) is not None

        with pytest.raises(TableEventActorUnauthorizedError):
            table.combat.remove_entry(
                table.player_actor,
                next(item for item in removed.entries if item.character_id == table.character_id).id,
                idempotency_key="player-remove",
            )

        with table.engine.connect() as connection:
            hostility = {
                row.id: bool(row.is_hostile)
                for row in connection.execute(
                    select(combat_entries.c.id, combat_entries.c.is_hostile).where(
                        combat_entries.c.combat_id == removed.id
                    )
                )
            }
        character_entry = next(item for item in removed.entries if item.character_id == table.character_id)
        assert hostility[character_entry.id] is False
        assert hostility[entry_a.id] is True
        assert hostility[entry_b.id] is True
    finally:
        table.engine.dispose()
