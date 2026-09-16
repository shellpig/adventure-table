from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update

from app.content import load_default_content_registry
from app.domain.character.schemas import (
    CharacterBuild,
    CharacterConcentrationState,
    CharacterState,
    PersistentTemporaryEffect,
    SpellResourcePool,
    SpellSlotCapacity,
    SpellcastingProfile,
)
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.combat.reaction_service import ReactionKind, open_reaction_window
from app.domain.combat.resolution import DamageRollPart, DamageType
from app.domain.combat.spell_resolver import SaveDamageMode
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.persistence.characters import (
    CharacterRepository,
    character_states,
    character_versions,
    characters,
)
from app.persistence.combat.concentration import CombatConcentrationRepository
from app.persistence.combat.reactions import CombatReactionRepository
from app.persistence.combat.resolution import CombatResolutionRepository
from app.persistence.combat.spells import CombatSpellRepository
from app.persistence.combat.tables import combat_entries, combats, monster_instances
from app.persistence.rooms.p3c_runtime import roll_requests, roll_results
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


def _running_aoe_table():
    table = support._setup()
    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key="p4d-aoe-start"),
    )
    enemy = support._quick_enemy(table, "Fireball Target")
    table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=enemy.id,
            idempotency_key="p4d-aoe-enemy",
        ),
    )
    requested = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="p4d-aoe-init"),
    )
    for index, request in enumerate(requested.requests):
        actor = table.player_actor if request.target_seat_id is not None else table.dm_actor
        raw = 20 if request.target_seat_id is not None else 1
        table.initiative.complete_initiative(
            actor,
            FormalRollInput(
                roll_request_id=request.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(raw,),
                idempotency_key=f"p4d-aoe-init-roll-{index}",
            ),
        )
    order = table.initiative.suggested_order(table.dm_actor)
    running = table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=order,
            idempotency_key="p4d-aoe-finalize",
        ),
    )
    caster = next(item for item in running.entries if item.character_id == table.character_id)
    target = next(item for item in running.entries if item.monster_instance_id == enemy.id)
    assert running.current_turn_entry_id == caster.id
    return table, running, caster, target, enemy


def _set_concentration(table, *, source_ref: str = "srd5.1:spell:web") -> int:
    characters_repository = CharacterRepository(table.engine, load_default_content_registry())
    stored = characters_repository.load_character(table.character_id)
    payload = stored.state.model_dump(mode="json")
    payload["concentration"] = CharacterConcentrationState(
        source_ref=source_ref,
        effect_ids=("web:1",),
    ).model_dump(mode="json")
    payload["temporary_effects"] = [
        effect
        for effect in payload.get("temporary_effects", [])
        if effect.get("effect_id") != "web:1"
    ]
    payload["temporary_effects"].append(
        PersistentTemporaryEffect(
            effect_id="web:1",
            source_ref=source_ref,
            tag="restrained",
            duration="concentration",
        ).model_dump(mode="json")
    )
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


def _enable_fireball_profile(table) -> None:
    with table.engine.begin() as connection:
        version_id = connection.scalar(
            select(characters.c.current_version_id).where(
                characters.c.id == table.character_id
            )
        )
        assert version_id is not None
        row = connection.execute(
            select(character_versions.c.build_payload).where(
                character_versions.c.id == version_id
            )
        ).mappings().one()
        build = CharacterBuild.model_validate(row["build_payload"])
        wizard = "srd5.1:class:wizard"
        profile = SpellcastingProfile(
            profile_id="wizard",
            source_type="class",
            source_key=wizard,
            class_ref=wizard,
            ability="intelligence",
            access_model="spellbook",
            resource_pool_type="normal_multiclass_slots",
            max_spell_level=3,
            prepared_limit=8,
        )
        pool = SpellResourcePool(
            pool_id="normal_multiclass",
            pool_type="normal_multiclass_slots",
            slots=(
                SpellSlotCapacity(level=1, capacity=4),
                SpellSlotCapacity(level=2, capacity=3),
                SpellSlotCapacity(level=3, capacity=2),
            ),
        )
        next_build = build.model_copy(
            update={
                "spellcasting_profiles": (profile,),
                "spell_resource_pools": (pool,),
            },
            deep=True,
        )
        connection.execute(
            update(character_versions)
            .where(character_versions.c.id == version_id)
            .values(build_payload=next_build.model_dump(mode="json"))
        )


def test_damage_concentration_request_is_atomic_durable_and_idempotent() -> None:
    table, running, entry = _running_character_table()
    try:
        before_hp = _set_concentration(table)
        dm_binding = table.events._stored_binding(table.dm_actor)
        repository = CombatResolutionRepository(table.engine, table.events.repository)
        request = dict(
            binding=dm_binding,
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

        concentration_request_id = UUID(concentration["roll_request_id"])
        player_binding = table.events._stored_binding(table.player_actor)
        resolved, resolved_event = CombatConcentrationRepository(
            table.engine,
            table.events.repository,
        ).complete_check(
            binding=player_binding,
            request_id=concentration_request_id,
            acting_seat_id=table.player_actor.seat_id,
            execution_mode="self",
            d20=1,
            constitution_save_modifier=0,
            roll_source="physical",
            idempotency_key="p4d-concentration-fail",
        )
        assert resolved.succeeded is False
        assert resolved.total == 1
        assert resolved.dc == 11
        assert resolved_event.kind == "combat.concentration_resolved"

        after_failure = CharacterRepository(
            table.engine,
            load_default_content_registry(),
        ).load_character(table.character_id)
        assert after_failure.state.concentration is None
        assert all(
            effect.effect_id != "web:1"
            for effect in after_failure.state.temporary_effects
        )

        duplicate_resolution, duplicate_event = CombatConcentrationRepository(
            table.engine,
            table.events.repository,
        ).complete_check(
            binding=player_binding,
            request_id=concentration_request_id,
            acting_seat_id=table.player_actor.seat_id,
            execution_mode="self",
            d20=20,
            constitution_save_modifier=99,
            roll_source="physical",
            idempotency_key="p4d-concentration-fail",
        )
        assert duplicate_resolution == resolved
        assert duplicate_event.id == resolved_event.id
        with table.engine.connect() as connection:
            assert len(
                connection.execute(
                    select(roll_results).where(
                        roll_results.c.roll_request_id == concentration_request_id
                    )
                ).mappings().all()
            ) == 1
            assert len(
                connection.execute(
                    select(session_events).where(
                        session_events.c.session_id == table.session_id,
                        session_events.c.idempotency_key
                        == "p4d-concentration-result:p4d-concentration-fail",
                    )
                ).mappings().all()
            ) == 1
    finally:
        table.engine.dispose()


def test_aoe_spell_resolution_is_atomic_durable_and_idempotent() -> None:
    table, running, caster, target, enemy = _running_aoe_table()
    try:
        _enable_fireball_profile(table)
        before_hp = _set_concentration(table)
        before_character = CharacterRepository(
            table.engine,
            load_default_content_registry(),
        ).load_character(table.character_id)
        assert before_character.state.spell_slots[3].remaining == 1

        repository = CombatSpellRepository(table.engine, table.events.repository)
        player_binding = table.events._stored_binding(table.player_actor)
        dm_binding = table.events._stored_binding(table.dm_actor)
        proposal_args = dict(
            binding=player_binding,
            combat_id=running.id,
            caster_entry_id=caster.id,
            subject_seat_id=table.player_seat_id,
            execution_mode="self",
            profile_id="wizard",
            spell_ref="srd5.1:spell:fireball",
            spell_level=3,
            slot_level=3,
            save_ability_ref="srd5.1:ability:dex",
            save_dc=15,
            save_damage_mode=SaveDamageMode.HALF,
            proposed_target_ids=(caster.id, target.id),
            idempotency_key="p4d-fireball-propose",
        )
        proposed, proposal_event = repository.propose_character_aoe(**proposal_args)
        assert proposed.status == "dm_adjudication_required"
        duplicate_proposal, duplicate_proposal_event = CombatSpellRepository(
            table.engine,
            table.events.repository,
        ).propose_character_aoe(**proposal_args)
        assert duplicate_proposal.action_id == proposed.action_id
        assert duplicate_proposal_event.id == proposal_event.id

        resolve_args = dict(
            binding=dm_binding,
            action_id=proposed.action_id,
            confirmed_target_ids=(caster.id, target.id),
            save_modifiers={caster.id: 0, target.id: 0},
            save_d20s={caster.id: 20, target.id: 1},
            damage_parts=(
                DamageRollPart(
                    damage_type=DamageType.FIRE,
                    dice=(8, 8),
                ),
            ),
            roll_source="physical",
            idempotency_key="p4d-fireball-resolve",
            target_seat_ids={caster.id: table.player_seat_id, target.id: None},
        )
        resolved, resolve_event = repository.resolve_character_aoe(**resolve_args)
        assert resolved.status == "resolved"
        assert resolve_event.kind == "combat.spell_aoe_resolved"
        assert resolved.resolution_result is not None
        assert len(resolved.resolution_result["rolls"]) == 2
        assert len(resolved.resolution_result["concentration_checks"]) == 1
        concentration = resolved.resolution_result["concentration_checks"][0]
        assert concentration["target_entry_id"] == str(caster.id)
        assert concentration["damage_taken"] == 8
        assert concentration["dc"] == 10

        after = CharacterRepository(
            table.engine,
            load_default_content_registry(),
        ).load_character(table.character_id)
        assert after.state.current_hp == before_hp - 8
        assert after.state.spell_slots[3].used == 2
        assert after.state.spell_slots[3].remaining == 0
        assert after.state.concentration is not None
        assert after.state.concentration.source_ref == "srd5.1:spell:web"

        with table.engine.connect() as connection:
            enemy_hp = connection.scalar(
                select(monster_instances.c.current_hp).where(
                    monster_instances.c.id == enemy.id
                )
            )
            caster_row = connection.execute(
                select(combat_entries.c.action_available).where(
                    combat_entries.c.id == caster.id
                )
            ).mappings().one()
            dex_requests = connection.execute(
                select(roll_requests).where(
                    roll_requests.c.session_id == table.session_id,
                    roll_requests.c.ability_ref == "srd5.1:ability:dex",
                    roll_requests.c.target_combat_entry_id.in_((caster.id, target.id)),
                )
            ).mappings().all()
            concentration_requests = connection.execute(
                select(roll_requests).where(
                    roll_requests.c.session_id == table.session_id,
                    roll_requests.c.ability_ref == "srd5.1:ability:constitution",
                    roll_requests.c.target_combat_entry_id == caster.id,
                )
            ).mappings().all()
            revision_after_resolve = connection.scalar(
                select(combats.c.revision).where(combats.c.id == running.id)
            )
        assert enemy_hp == 0
        assert caster_row["action_available"] is False
        assert len(dex_requests) == 2
        assert all(row["status"] == "resolved" for row in dex_requests)
        assert len(concentration_requests) == 1
        assert concentration_requests[0]["status"] == "pending"
        concentration_request_id = concentration_requests[0]["id"]
        with table.engine.connect() as connection:
            assert len(
                connection.execute(
                    select(roll_results).where(
                        roll_results.c.roll_request_id.in_(
                            tuple(row["id"] for row in dex_requests)
                        )
                    )
                ).mappings().all()
            ) == 2

        duplicate_resolved, duplicate_resolve_event = CombatSpellRepository(
            table.engine,
            table.events.repository,
        ).resolve_character_aoe(**resolve_args)
        assert duplicate_resolved == resolved
        assert duplicate_resolve_event.id == resolve_event.id
        after_retry = CharacterRepository(
            table.engine,
            load_default_content_registry(),
        ).load_character(table.character_id)
        assert after_retry.state.current_hp == before_hp - 8
        assert after_retry.state.spell_slots[3].used == 2
        assert after_retry.state.spell_slots[3].remaining == 0
        with table.engine.connect() as connection:
            assert connection.scalar(
                select(monster_instances.c.current_hp).where(
                    monster_instances.c.id == enemy.id
                )
            ) == 0
            assert len(
                connection.execute(
                    select(roll_requests).where(
                        roll_requests.c.session_id == table.session_id,
                        roll_requests.c.ability_ref == "srd5.1:ability:dex",
                        roll_requests.c.target_combat_entry_id.in_((caster.id, target.id)),
                    )
                ).mappings().all()
            ) == 2
            assert len(
                connection.execute(
                    select(roll_requests).where(
                        roll_requests.c.id == concentration_request_id
                    )
                ).mappings().all()
            ) == 1
            assert connection.scalar(
                select(combats.c.revision).where(combats.c.id == running.id)
            ) == revision_after_resolve

        failed, failed_event = CombatConcentrationRepository(
            table.engine,
            table.events.repository,
        ).complete_check(
            binding=player_binding,
            request_id=concentration_request_id,
            acting_seat_id=table.player_actor.seat_id,
            execution_mode="self",
            d20=1,
            constitution_save_modifier=0,
            roll_source="physical",
            idempotency_key="p4d-fireball-concentration-fail",
        )
        assert failed.succeeded is False
        assert failed_event.kind == "combat.concentration_resolved"
        final_character = CharacterRepository(
            table.engine,
            load_default_content_registry(),
        ).load_character(table.character_id)
        assert final_character.state.concentration is None
        assert all(
            effect.effect_id != "web:1"
            for effect in final_character.state.temporary_effects
        )
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
