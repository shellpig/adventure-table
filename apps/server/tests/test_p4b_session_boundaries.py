from __future__ import annotations

import pytest
from sqlalchemy import select

from app.content import load_default_content_registry
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.combat.initiative import RequestInitiativeInput
from app.domain.combat.lifecycle import (
    AddCharacterInput,
    AddMonsterInput,
    CombatActionInput,
    CombatActionKind,
    CombatEconomyCost,
    StartCombatInput,
)
from app.domain.combat.order import ReorderInitiativeInput
from app.domain.rooms.campaigns import CampaignService, RosterAdd
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.domain.rooms.seats import SeatService
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.table_runtime import session_events
from app.persistence.rooms.workspace import RoomWorkspaceRepository
from tests.test_p4b_combat_lifecycle import _quick_enemy, _setup


def _roll(table, actor, request_id, raw, key):
    return table.initiative.complete_initiative(
        actor,
        FormalRollInput(
            roll_request_id=request_id,
            source=FormalRollSource.PHYSICAL,
            raw_dice=(raw,),
            idempotency_key=key,
        ),
    )


def test_changed_party_and_abandoned_session_do_not_rebind_or_clear_combat() -> None:
    table = _setup()
    try:
        initial = table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="start"),
        )
        old_entry = next(entry for entry in initial.entries if entry.character_id == table.character_id)
        monster = _quick_enemy(table, "Guard")
        pending = table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=monster.id, idempotency_key="guard"),
        )
        monster_entry = next(entry for entry in pending.entries if entry.monster_instance_id == monster.id)

        requests = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(idempotency_key="initial-init"),
        )
        for request in requests.requests:
            if request.target_character_id == table.character_id:
                _roll(table, table.player_actor, request.id, 20, "old-character")
            else:
                _roll(table, table.dm_actor, request.id, 1, "monster")
        order = table.initiative.suggested_order(table.dm_actor)
        running = table.initiative.finalize_initiative(
            table.dm_actor,
            __import__("app.domain.combat.initiative", fromlist=["FinalizeInitiativeInput"]).FinalizeInitiativeInput(
                ordered_entry_ids=order,
                idempotency_key="finalize",
            ),
        )
        assert running.current_turn_entry_id == old_entry.id

        # Reach Round 3 with the original Character as current turn.
        table.combat.advance_turn(table.dm_actor, idempotency_key="r1-monster")
        table.combat.advance_turn(table.dm_actor, idempotency_key="r2-character")
        table.combat.advance_turn(table.dm_actor, idempotency_key="r2-monster")
        round_three = table.combat.advance_turn(table.dm_actor, idempotency_key="r3-character")
        assert round_three.round_number == 3
        assert round_three.current_turn_entry_id == old_entry.id

        table.session_service.end_session(
            table.room_id,
            table.campaign_id,
            table.session_id,
            table.dm_context,
        )

        # Change the next Session's party Character. The old Character remains a
        # durable CombatEntry, while the new Session Character must not auto-enter.
        registry = load_default_content_registry()
        characters = CharacterRepository(table.engine, registry)
        build = build_p0_fighter_wizard_fixture()
        new_character = characters.create_character(
            name="New Session Hero",
            build=build,
            state=build_p0_fighter_wizard_state(build),
        )
        RoomWorkspaceRepository(table.engine).attach_character(
            room_id=table.room_id,
            character_id=new_character.id,
        )
        CampaignService(CampaignRepository(table.engine)).add_character(
            table.room_id,
            table.campaign_id,
            RosterAdd(character_id=new_character.id),
        )
        SeatService(SeatRepository(table.engine)).select_character(
            table.room_id,
            table.campaign_id,
            table.player_seat_id,
            new_character.id,
        )

        session_b = table.session_service.start_session(
            table.room_id,
            table.campaign_id,
            table.dm_context,
        )
        dm_b = table.actor_for_session(session_b.id, table.dm_context)
        player_b = table.actor_for_session(session_b.id, table.player_context)
        resumed = table.combat.get_active_combat(dm_b)
        assert resumed is not None
        assert resumed.id == running.id
        assert resumed.round_number == 3
        assert resumed.current_turn_entry_id == old_entry.id
        assert old_entry.id in {entry.id for entry in resumed.entries}
        assert new_character.id not in {entry.character_id for entry in resumed.entries}

        # No Player is silently rebound to the absent old Character.
        with pytest.raises(TableEventActorUnauthorizedError):
            table.combat.use_action(
                player_b,
                CombatActionInput(
                    entry_id=old_entry.id,
                    action_kind=CombatActionKind.DODGE,
                    economy_cost=CombatEconomyCost.ACTION,
                    idempotency_key="player-cannot-steal-old-entry",
                ),
            )

        # The current DM may explicitly proxy that durable Character entry; the
        # audit intentionally has no fabricated subject Seat for the absent PC,
        # while retaining the durable Character and CombatEntry identities.
        proxied = table.combat.use_action(
            dm_b,
            CombatActionInput(
                entry_id=old_entry.id,
                action_kind=CombatActionKind.DODGE,
                economy_cost=CombatEconomyCost.ACTION,
                idempotency_key="dm-proxy-old-entry",
            ),
        )
        assert proxied.execution_mode == "dm_proxy"
        assert proxied.subject_seat_id is None
        assert proxied.acting_seat_id == dm_b.seat_id
        with table.engine.connect() as connection:
            audit = connection.execute(
                select(session_events).where(
                    session_events.c.session_id == session_b.id,
                    session_events.c.idempotency_key == "p4b-action:dm-proxy-old-entry",
                )
            ).mappings().one()
        assert audit["acting_seat_id"] == dm_b.seat_id
        assert audit["subject_seat_id"] is None
        assert audit["subject_character_id"] == table.character_id
        assert audit["payload"]["entry_id"] == str(old_entry.id)

        # New Session Character joins only through an explicit mid-combat entrant.
        before_add = table.combat.get_active_combat(dm_b)
        assert new_character.id not in {entry.character_id for entry in before_add.entries}
        with_new = table.combat.add_character(
            dm_b,
            AddCharacterInput(
                character_id=new_character.id,
                idempotency_key="explicit-new-entrant",
            ),
        )
        new_entry = next(entry for entry in with_new.entries if entry.character_id == new_character.id)
        request = table.initiative.request_initiative(
            dm_b,
            RequestInitiativeInput(
                entry_ids=(new_entry.id,),
                idempotency_key="new-entrant-init",
            ),
        ).requests[0]
        assert request.target_seat_id == table.player_seat_id
        _roll(table, player_b, request.id, 12, "new-entrant-roll")

        before_reorder = table.combat.get_active_combat(dm_b)
        reordered = table.order.reorder_running(
            dm_b,
            ReorderInitiativeInput(
                ordered_entry_ids=tuple(entry.id for entry in before_reorder.entries),
                idempotency_key="new-entrant-order",
            ),
        )
        assert reordered.round_number == 3
        assert reordered.current_turn_entry_id == old_entry.id

        # Abandoning the Session also leaves Campaign Combat state intact.
        table.session_service.abandon_session(
            table.room_id,
            table.campaign_id,
            session_b.id,
            table.dm_context,
        )
        session_c = table.session_service.start_session(
            table.room_id,
            table.campaign_id,
            table.dm_context,
        )
        dm_c = table.actor_for_session(session_c.id, table.dm_context)
        after_abandon = table.combat.get_active_combat(dm_c)
        assert after_abandon is not None
        assert after_abandon.id == reordered.id
        assert after_abandon.round_number == reordered.round_number
        assert after_abandon.current_turn_entry_id == reordered.current_turn_entry_id
        assert [entry.id for entry in after_abandon.entries] == [entry.id for entry in reordered.entries]
    finally:
        table.engine.dispose()
