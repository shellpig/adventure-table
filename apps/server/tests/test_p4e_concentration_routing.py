from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.content import load_default_content_registry
from app.domain.combat.concentration import (
    CombatConcentrationNotFoundError,
    CombatConcentrationService,
    CombatConcentrationStateConflictError,
    ConcentrationCheckResultView,
)
from app.domain.combat.core_rolls import CombatCoreRollService, SavingThrowResultView
from app.domain.combat.effect_resolver import DurationKind, DurationSpec, EffectSpec
from app.domain.combat.resolution import DamageRollPart, DamageType
from app.domain.combat.spell_resolver import SpellCastMode
from app.domain.rooms.rolls import (
    FormalRollComputation,
    FormalRollInput,
    FormalRollSource,
    RollModifierMode,
)
from app.domain.rooms.seats import ControllerKind, SeatControllerPatch, SeatCreate, SeatRole, SeatService
from app.domain.rooms.table_events import TableActorContext, TableEventActorUnauthorizedError
from app.persistence.characters import CharacterRepository
from app.persistence.combat.concentration import CombatConcentrationRepository
from app.persistence.combat.core_rolls import (
    CombatCoreRollRepository,
    CombatCoreRollStateConflictError,
    CoreRollComputation,
)
from app.persistence.combat.resolution import CombatResolutionRepository
from app.persistence.combat.spells import CombatSpellRepository
from app.persistence.rooms.p3c_rolls import (
    RollRepository,
    RollRequestNotFoundPersistenceError,
)
from app.persistence.rooms.p3c_runtime import roll_requests, roll_results
from app.persistence.rooms.seats import SeatRepository
from tests.test_p4d_persistence import _running_character_table, _set_concentration
from tests.test_p4e_monster_cast import _running_mage_combat


def _make_character_concentration_request(table, running, entry, idempotency_suffix: str = "1") -> UUID:
    _set_concentration(table)
    dm_binding = table.events._stored_binding(table.dm_actor)
    res_repo = CombatResolutionRepository(table.engine, table.events.repository)
    damage_res = res_repo.apply_damage(
        binding=dm_binding,
        combat_id=running.id,
        target_entry_id=entry.id,
        damage_parts=(DamageRollPart(damage_type=DamageType.FORCE, dice=(11, 11)),),
        critical=False,
        source_entry_id=None,
        subject_seat_id=table.player_seat_id,
        execution_mode="dm_proxy",
        idempotency_key=f"setup-char-damage-{idempotency_suffix}",
    )
    check = damage_res.payload["concentration_check"]
    return UUID(check["roll_request_id"])


def _make_monster_concentration_request(table, running, caster_id, target_id, idempotency_suffix: str = "1") -> UUID:
    spell_repo = CombatSpellRepository(table.engine, table.events.repository)
    dm_binding = table.events._stored_binding(table.dm_actor)
    spell_repo.cast_monster_spell(
        binding=dm_binding,
        combat_id=running.id,
        caster_entry_id=caster_id,
        subject_seat_id=table.dm_actor.seat_id,
        execution_mode="dm_proxy",
        spell_ref="srd5.1:spell:fly",
        spell_level=3,
        slot_level=3,
        cast_mode=SpellCastMode.UTILITY,
        target_entry_id=caster_id,
        concentration=True,
        apply_effects=(
            EffectSpec(
                effect_type="condition",
                tag="flying",
                duration=DurationSpec(kind=DurationKind.UNTIL_CONCENTRATION_ENDS),
                source_ref="srd5.1:spell:fly",
            ),
        ),
        roll_source="physical",
        idempotency_key=f"setup-monster-fly-{idempotency_suffix}",
    )
    res_repo = CombatResolutionRepository(table.engine, table.events.repository)
    damage_res = res_repo.apply_damage(
        binding=dm_binding,
        combat_id=running.id,
        target_entry_id=caster_id,
        damage_parts=(DamageRollPart(damage_type=DamageType.FORCE, dice=(20,)),),
        critical=False,
        source_entry_id=target_id,
        subject_seat_id=table.dm_actor.seat_id,
        execution_mode="dm_proxy",
        idempotency_key=f"setup-monster-damage-{idempotency_suffix}",
    )
    check = damage_res.payload["concentration_check"]
    return UUID(check["roll_request_id"])


def _make_services(table) -> tuple[CombatConcentrationService, CombatCoreRollService]:
    conc_repo = CombatConcentrationRepository(table.engine, table.events.repository)
    conc_service = CombatConcentrationService(
        repository=conc_repo,
        combat_repository=table.combat.repository,
        monster_repository=table.monsters,
        roll_service=table.rolls,
        table_event_service=table.events,
    )
    core_repo = CombatCoreRollRepository(table.engine, table.events.repository)
    core_service = CombatCoreRollService(
        repository=core_repo,
        combat_repository=table.combat.repository,
        combat_service=table.combat,
        monster_repository=table.monsters,
        roll_service=table.rolls,
        table_event_service=table.events,
        concentration_service=conc_service,
    )
    return conc_service, core_service


def test_generic_roll_repository_refuses_character_concentration_request() -> None:
    table, running, entry = _running_character_table()
    try:
        req_id = _make_character_concentration_request(table, running, entry)
        plain_repo = RollRepository(table.engine, table.events.repository)
        player_binding = table.events._stored_binding(table.player_actor)

        with pytest.raises(RollRequestNotFoundPersistenceError):
            plain_repo.complete_request(
                binding=player_binding,
                request_id=req_id,
                acting_seat_id=table.player_seat_id,
                execution_mode="self",
                result_factory=lambda: FormalRollComputation(
                    source="physical",
                    formula="1d20",
                    raw_dice=(15,),
                    kept_dice=(15,),
                    base_modifier=0,
                    flat_adjustment=0,
                    total=15,
                ),
                event_visibility="public",
                idempotency_key="generic-roll-attempt",
            )

        with table.engine.connect() as connection:
            req = connection.execute(
                select(roll_requests).where(roll_requests.c.id == req_id)
            ).mappings().one()
            assert req["status"] == "pending"

            results = connection.execute(
                select(roll_results).where(roll_results.c.roll_request_id == req_id)
            ).mappings().all()
            assert len(results) == 0

        reloaded = CharacterRepository(
            table.engine, load_default_content_registry()
        ).load_character(table.character_id)
        assert reloaded.state.concentration is not None
        assert reloaded.state.concentration.source_ref == "srd5.1:spell:web"
    finally:
        table.engine.dispose()


def test_combat_core_roll_repository_refuses_concentration_request() -> None:
    table, running, entry = _running_character_table()
    try:
        req_id = _make_character_concentration_request(table, running, entry)
        core_repo = CombatCoreRollRepository(table.engine, table.events.repository)
        player_binding = table.events._stored_binding(table.player_actor)

        with pytest.raises(CombatCoreRollStateConflictError) as exc_info:
            core_repo.complete_saving_throw(
                binding=player_binding,
                request_id=req_id,
                acting_seat_id=table.player_seat_id,
                execution_mode="self",
                result_factory=lambda: CoreRollComputation(
                    source="physical",
                    formula="1d20",
                    raw_dice=(15,),
                    kept_dice=(15,),
                    base_modifier=0,
                    flat_adjustment=0,
                    total=15,
                ),
                idempotency_key="core-repo-roll-attempt",
            )
        assert "Concentration saving throws must be completed via CombatConcentrationRepository" in str(exc_info.value)

        with table.engine.connect() as connection:
            req = connection.execute(
                select(roll_requests).where(roll_requests.c.id == req_id)
            ).mappings().one()
            assert req["status"] == "pending"

            results = connection.execute(
                select(roll_results).where(roll_results.c.roll_request_id == req_id)
            ).mappings().all()
            assert len(results) == 0

        reloaded = CharacterRepository(
            table.engine, load_default_content_registry()
        ).load_character(table.character_id)
        assert reloaded.state.concentration is not None
    finally:
        table.engine.dispose()


def test_combat_core_roll_service_delegates_to_concentration_service() -> None:
    # 1. Failing save: clears pointer and removes linked effects
    table, running, entry = _running_character_table()
    try:
        req_id = _make_character_concentration_request(table, running, entry, idempotency_suffix="fail")
        _conc_service, core_service = _make_services(table)

        # DC is 11 (22 damage taken // 2). Roll raw 1 -> total is 1 (+ CON mod <= 10) -> Fail
        res = core_service.complete_saving_throw(
            table.player_actor,
            FormalRollInput(
                roll_request_id=req_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(1,),
                idempotency_key="core-save-fail",
            ),
        )
        assert isinstance(res, SavingThrowResultView)
        assert res.succeeded is False
        assert res.roll_request_id == req_id

        reloaded = CharacterRepository(
            table.engine, load_default_content_registry()
        ).load_character(table.character_id)
        assert reloaded.state.concentration is None
        assert all(eff.effect_id != "web:1" for eff in reloaded.state.temporary_effects)
    finally:
        table.engine.dispose()

    # 2. Passing save: keeps pointer and keeps linked effects
    table2, running2, entry2 = _running_character_table()
    try:
        req_id2 = _make_character_concentration_request(table2, running2, entry2, idempotency_suffix="pass")
        _conc_service2, core_service2 = _make_services(table2)

        # Roll raw 20 -> Pass
        res2 = core_service2.complete_saving_throw(
            table2.player_actor,
            FormalRollInput(
                roll_request_id=req_id2,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="core-save-pass",
            ),
        )
        assert isinstance(res2, SavingThrowResultView)
        assert res2.succeeded is True
        assert res2.roll_request_id == req_id2

        reloaded2 = CharacterRepository(
            table2.engine, load_default_content_registry()
        ).load_character(table2.character_id)
        assert reloaded2.state.concentration is not None
        assert reloaded2.state.concentration.source_ref == "srd5.1:spell:web"
        assert any(eff.effect_id == "web:1" for eff in reloaded2.state.temporary_effects)
    finally:
        table2.engine.dispose()


def test_combat_concentration_service_actor_authorization() -> None:
    # Character target
    table, running, entry = _running_character_table()
    try:
        req_id = _make_character_concentration_request(table, running, entry)
        conc_service, _core = _make_services(table)

        # Player actor (controlling seat) can roll
        result = conc_service.complete_check(
            table.player_actor,
            FormalRollInput(
                roll_request_id=req_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(15,),
                idempotency_key="player-auth-success",
            ),
        )
        assert isinstance(result, ConcentrationCheckResultView)
        assert result.succeeded is True
    finally:
        table.engine.dispose()

    # Character target with DM proxy
    table_dm, running_dm, entry_dm = _running_character_table()
    try:
        req_id_dm = _make_character_concentration_request(table_dm, running_dm, entry_dm, idempotency_suffix="dm")
        conc_service_dm, _core = _make_services(table_dm)

        # DM actor can roll on behalf of character via dm_proxy
        result_dm = conc_service_dm.complete_check(
            table_dm.dm_actor,
            FormalRollInput(
                roll_request_id=req_id_dm,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(15,),
                idempotency_key="dm-auth-success",
            ),
        )
        assert isinstance(result_dm, ConcentrationCheckResultView)
    finally:
        table_dm.engine.dispose()

    # Monster target: Player rejected, DM allowed
    table_m, running_m, caster_id, _mage, target_id = _running_mage_combat()
    try:
        req_id_m = _make_monster_concentration_request(table_m, running_m, caster_id, target_id)
        conc_service_m, _core = _make_services(table_m)

        # Player actor cannot roll for seatless monster
        with pytest.raises(TableEventActorUnauthorizedError):
            conc_service_m.complete_check(
                table_m.player_actor,
                FormalRollInput(
                    roll_request_id=req_id_m,
                    source=FormalRollSource.PHYSICAL,
                    raw_dice=(15,),
                    idempotency_key="player-monster-unauth",
                ),
            )

        # Verify zero side effects on unauthorized attempt
        with table_m.engine.connect() as connection:
            req = connection.execute(
                select(roll_requests).where(roll_requests.c.id == req_id_m)
            ).mappings().one()
            assert req["status"] == "pending"
            results = connection.execute(
                select(roll_results).where(roll_results.c.roll_request_id == req_id_m)
            ).mappings().all()
            assert len(results) == 0

        # DM actor can roll for monster
        dm_res = conc_service_m.complete_check(
            table_m.dm_actor,
            FormalRollInput(
                roll_request_id=req_id_m,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(15,),
                idempotency_key="dm-monster-auth",
            ),
        )
        assert isinstance(dm_res, ConcentrationCheckResultView)
        assert dm_res.target_entry_id == caster_id
    finally:
        table_m.engine.dispose()


def test_combat_concentration_service_physical_roll_source_with_raw_die() -> None:
    table, running, entry = _running_character_table()
    try:
        req_id = _make_character_concentration_request(table, running, entry)
        conc_service, _core = _make_services(table)

        view = conc_service.complete_check(
            table.player_actor,
            FormalRollInput(
                roll_request_id=req_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(18,),
                idempotency_key="physical-d20-test",
            ),
        )
        assert view.d20 == 18
        assert view.total == 18 + view.modifier

        with table.engine.connect() as connection:
            result_row = connection.execute(
                select(roll_results).where(roll_results.c.roll_request_id == req_id)
            ).mappings().one()
            assert result_row["source"] == "physical"
            assert list(result_row["raw_dice"]) == [18]
            assert list(result_row["kept_dice"]) == [18]
    finally:
        table.engine.dispose()


def test_combat_concentration_service_idempotent_replay() -> None:
    table, running, entry = _running_character_table()
    try:
        req_id = _make_character_concentration_request(table, running, entry)
        conc_service, _core = _make_services(table)

        # Initial completion
        result1 = conc_service.complete_check(
            table.player_actor,
            FormalRollInput(
                roll_request_id=req_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(14,),
                idempotency_key="idemp-key-conc-1",
            ),
        )

        # 1. Replay with identical idempotency_key
        result2 = conc_service.complete_check(
            table.player_actor,
            FormalRollInput(
                roll_request_id=req_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(2,),
                idempotency_key="idemp-key-conc-1",
            ),
        )
        assert result2.result_id == result1.result_id
        assert result2.d20 == result1.d20
        assert result2.total == result1.total
        assert result2.succeeded == result1.succeeded

        # 2. Replay with different idempotency key on already resolved request
        result3 = conc_service.complete_check(
            table.player_actor,
            FormalRollInput(
                roll_request_id=req_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="idemp-key-conc-different",
            ),
        )
        assert result3.result_id == result1.result_id
        assert result3.d20 == result1.d20
        assert result3.total == result1.total
        assert result3.succeeded == result1.succeeded

        # Ensure only 1 roll_results row in database
        with table.engine.connect() as connection:
            all_results = connection.execute(
                select(roll_results).where(roll_results.c.roll_request_id == req_id)
            ).mappings().all()
            assert len(all_results) == 1
    finally:
        table.engine.dispose()
