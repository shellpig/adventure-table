from __future__ import annotations

from app.domain.combat.initiative import RequestInitiativeInput
from app.domain.combat.lifecycle import StartCombatInput
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from tests.test_p4b_combat_lifecycle import _setup


def test_pc_initiative_is_formal_d20_plus_character_dexterity_modifier() -> None:
    table = _setup()
    try:
        pending = table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="start"),
        )
        entry = next(entry for entry in pending.entries if entry.character_id == table.character_id)
        request = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(
                entry_ids=(entry.id,),
                idempotency_key="pc-init",
            ),
        ).requests[0]
        result = table.initiative.complete_initiative(
            table.player_actor,
            FormalRollInput(
                roll_request_id=request.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(10,),
                idempotency_key="pc-result",
            ),
        )

        # The P0 Fighter/Wizard fixture has DEX 14, so initiative is 10 + 2.
        assert result.raw_dice == (10,)
        assert result.base_modifier == 2
        assert result.total == 12
        assert result.formula == "1d20+2"
        refreshed = table.combat.get_active_combat(table.dm_actor)
        persisted = next(item for item in refreshed.entries if item.id == entry.id)
        assert persisted.initiative_total == 12
        assert persisted.initiative_roll_request_id == request.id
        assert persisted.initiative_roll_result_id == result.result_id
    finally:
        table.engine.dispose()
