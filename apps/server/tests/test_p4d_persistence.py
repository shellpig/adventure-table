from __future__ import annotations

from sqlalchemy import func, select, update

from app.content import load_default_content_registry
from app.domain.character.schemas import CharacterConcentrationState, CharacterState
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import StartCombatInput
from app.domain.combat.reaction_service import ReactionKind, open_reaction_window
from app.domain.combat.resolution import DamageRollPart, DamageType
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.persistence.characters import CharacterRepository, character_states
from app.persistence.combat.reactions import CombatReactionRepository
from app.persistence.combat.resolution import CombatResolutionRepository
from app.persistence.combat.tables import combat_entries, combats
from app.persistence.rooms.p3c_runtime import roll_requests
from app.persistence.rooms.table_runtime import session_events
import tests.test_p4b_combat_lifecycle as support


def _running_character_table():
    table = support._setup()
    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key="p4d-persistence-start"),
    )
    requested = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="p4d-persistence-init"),
    )
    assert len(requested.requests) == 1
    request = requested.requests[0]
    table.initiative.complete_initiative(
        table.player_actor,
        FormalRollInput(
            roll_request_id=request.id,
            source=FormalRollSource.PHYSICAL,
            raw_dice=(15,),
            idempotency_key="p4d-persistence-init-roll",
        ),
    )
    order = table.initiative.suggested_order(table.dm_actor)
    running = table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=order,
            idempotency_key="p4d-persistence-finalize",
        ),
    )
    entry = next(item for item in running.entries if item.character_id == table.character_id)
    return table, running, entry


def _set_concentration(table, *, source_ref: str = "srd5.1:spell:web") -> int:
    characters = CharacterRepository(table.engine, load_default_content_registry())
    stored = characters.load_character(table.character_id)
    payload = stored.state.model_dump(mode="json")
    payload["concentration"] = CharacterConcentrationState(
        source_ref=source_ref,
        effect_ids=("web:1",),
    ).model_dump(mode="json")
    state = CharacterState.model_validate(payload)
    with table.engine.begin() as connection:
        row = connection.execute(
            select(character_states.c.state_revision).where(
                character_states.c.character_id == table.character_id
            )
        ).mappings().one()
        result = connection.execute(
            update(character_states)
            .where(
                character_states.c.character_id == table.character_id,
                character_states.c.state_revision == int(row["state_revision"]),
            )
            .values(
                state_payload=state.model_dump(mode="json"),
                state_revision=character_states.c.state_revision + 1,
                updated_at=func.now(),
            )
        )
        assert result.rowcount == 1
    return stored.state.current_hp


def test_damage_concentration_request_is_atomic_durable_and_idempotent() -> None:
    table, running, entry = _running_character_table()
    try:
        before_hp = _set_concentration(table)
        binding = table.events._stored_binding(table.dm_actor)
        repository = CombatResolutionRepository(table.engine, table.events.repository)
        request = dict(
            binding=binding,
            combat_id=running.id,
            target_entry_id=entry.id,
            damage_parts=(
                DamageRollPart(
                    damage_type=DamageType.FORCE,
                    dice=(11, 11),
                ),
            ),
            critical=False,
            source_entry_id=None,
            subject_seat_id=table.player_seat_id,
            execution_mode="dm_proxy",
            idempotency_key="p4d-concentration-damage",
        )

        result = repository.apply_damage(**request)
        assert result.after_hp == before_hp - 22
        concentration = result.payload["concentration_check"]
        assert concentration is not None
        assert concentration["source_ref"] == "srd5.1:spell:web"
        assert concentration["damage_taken"] == 22
        assert concentration["dc"] == 11

        reloaded_character = CharacterRepository(
            table.engine,
            load_default_content_registry(),
        ).load_character(table.character_id)
        assert reloaded_character.state.current_hp == before_hp - 22
        assert reloaded_character.state.concentration is not None
        assert reloaded_character.state.concentration.source_ref == "srd5.1:spell:web"

        with table.engine.connect() as connection:
            requests = connection.execute(
                select(roll_requests).where(
                    roll_requests.c.session_id == table.session_id,
                    roll_requests.c.target_character_id == table.character_id,
                    roll_requests.c.target_combat_entry_id == entry.id,
                    roll_requests.c.request_type == "saving_throw",
                    roll_requests.c.ability_ref == "srd5.1:ability:constitution",
                )
            ).mappings().all()
            events = connection.execute(
                select(session_events).where(
                    session_events.c.session_id == table.session_id,
                    session_events.c.idempotency_key
                    == "p4c-damage:p4d-concentration-damage",
                )
            ).mappings().all()
            revision_after_first = connection.scalar(
                select(combats.c.revision).where(combats.c.id == running.id)
            )
        assert len(requests) == 1
        assert requests[0]["status"] == "pending"
        assert requests[0]["dc"] == 11
        assert str(requests[0]["id"]) == concentration["roll_request_id"]
        assert len(events) == 1

        duplicate = CombatResolutionRepository(
            table.engine,
            table.events.repository,
        ).apply_damage(**request)
        assert duplicate == result

        after_retry = CharacterRepository(
            table.engine,
            load_default_content_registry(),
        ).load_character(table.character_id)
        assert after_retry.state.current_hp == before_hp - 22
        with table.engine.connect() as connection:
            assert len(
                connection.execute(
                    select(roll_requests).where(
                        roll_requests.c.session_id == table.session_id,
                        roll_requests.c.target_character_id == table.character_id,
                        roll_requests.c.target_combat_entry_id == entry.id,
                        roll_requests.c.request_type == "saving_throw",
                        roll_requests.c.ability_ref == "srd5.1:ability:constitution",
                    )
                ).mappings().all()
            ) == 1
            assert len(
                connection.execute(
                    select(session_events).where(
                        session_events.c.session_id == table.session_id,
                        session_events.c.idempotency_key
                        == "p4c-damage:p4d-concentration-damage",
                    )
                ).mappings().all()
            ) == 1
            assert connection.scalar(
                select(combats.c.revision).where(combats.c.id == running.id)
            ) == revision_after_first
    finally:
        table.engine.dispose()


def test_reaction_window_survives_reload_and_retry_without_double_spend() -> None:
    table, running, entry = _running_character_table()
    try:
        dm_binding = table.events._stored_binding(table.dm_actor)
        player_binding = table.events._stored_binding(table.player_actor)
        window = open_reaction_window(
            window_id="shield-window-1",
            entry_id=str(entry.id),
            kind=ReactionKind.SHIELD,
            reason="incoming_attack",
            eligible_entry_ids=(str(entry.id),),
            safe_payload={"spell_ref": "srd5.1:spell:shield"},
            secret_payload={"server_only": "kept"},
            session_ref=str(table.session_id),
        )
        repository = CombatReactionRepository(table.engine, table.events.repository)
        persisted, opened_event = repository.set_window(
            binding=dm_binding,
            combat_id=running.id,
            entry_id=entry.id,
            window=window,
            idempotency_key="p4d-reaction-open-1",
        )
        assert persisted == window
        assert opened_event.kind == "combat.reaction_requested"

        restored = CombatReactionRepository(
            table.engine,
            table.events.repository,
        ).get(combat_id=running.id, entry_id=entry.id)
        assert restored == window
        assert restored is not None
        assert restored.secret_payload == {"server_only": "kept"}

        duplicate_window, duplicate_open_event = CombatReactionRepository(
            table.engine,
            table.events.repository,
        ).set_window(
            binding=dm_binding,
            combat_id=running.id,
            entry_id=entry.id,
            window=window,
            idempotency_key="p4d-reaction-open-1",
        )
        assert duplicate_window == window
        assert duplicate_open_event.id == opened_event.id

        with table.engine.connect() as connection:
            opened_events = connection.execute(
                select(session_events).where(
                    session_events.c.session_id == table.session_id,
                    session_events.c.idempotency_key
                    == "p4d-reaction-open:p4d-reaction-open-1",
                )
            ).mappings().all()
            row = connection.execute(
                select(
                    combat_entries.c.pending_reaction_state,
                    combat_entries.c.reaction_available,
                ).where(combat_entries.c.id == entry.id)
            ).mappings().one()
            revision_after_open = connection.scalar(
                select(combats.c.revision).where(combats.c.id == running.id)
            )
        assert len(opened_events) == 1
        assert row["pending_reaction_state"]["window_id"] == "shield-window-1"
        assert row["reaction_available"] is True

        resolved_event = CombatReactionRepository(
            table.engine,
            table.events.repository,
        ).resolve_window(
            binding=player_binding,
            combat_id=running.id,
            owner_entry_id=entry.id,
            actor_entry_id=entry.id,
            accept=True,
            idempotency_key="p4d-reaction-resolve-1",
        )
        assert resolved_event.kind == "combat.reaction_resolved"
        assert resolved_event.payload["window_id"] == "shield-window-1"
        assert resolved_event.payload["status"] == "resolved"
        assert resolved_event.payload["accepted"] is True

        after_resolution = CombatReactionRepository(
            table.engine,
            table.events.repository,
        ).get(combat_id=running.id, entry_id=entry.id)
        assert after_resolution is None

        with table.engine.connect() as connection:
            resolved_row = connection.execute(
                select(
                    combat_entries.c.pending_reaction_state,
                    combat_entries.c.reaction_available,
                ).where(combat_entries.c.id == entry.id)
            ).mappings().one()
            revision_after_resolve = connection.scalar(
                select(combats.c.revision).where(combats.c.id == running.id)
            )
        assert resolved_row["pending_reaction_state"] == {}
        assert resolved_row["reaction_available"] is False
        assert revision_after_resolve == revision_after_open + 1

        duplicate_resolve = CombatReactionRepository(
            table.engine,
            table.events.repository,
        ).resolve_window(
            binding=player_binding,
            combat_id=running.id,
            owner_entry_id=entry.id,
            actor_entry_id=entry.id,
            accept=True,
            idempotency_key="p4d-reaction-resolve-1",
        )
        assert duplicate_resolve.id == resolved_event.id

        with table.engine.connect() as connection:
            resolved_events = connection.execute(
                select(session_events).where(
                    session_events.c.session_id == table.session_id,
                    session_events.c.idempotency_key
                    == "p4d-reaction-resolve:p4d-reaction-resolve-1",
                )
            ).mappings().all()
            final_row = connection.execute(
                select(
                    combat_entries.c.pending_reaction_state,
                    combat_entries.c.reaction_available,
                ).where(combat_entries.c.id == entry.id)
            ).mappings().one()
            final_revision = connection.scalar(
                select(combats.c.revision).where(combats.c.id == running.id)
            )
        assert len(resolved_events) == 1
        assert final_row["pending_reaction_state"] == {}
        assert final_row["reaction_available"] is False
        assert final_revision == revision_after_resolve
    finally:
        table.engine.dispose()
