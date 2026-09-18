from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.api.dependencies import get_database_engine
from app.api.rooms.access import get_room_service
from app.api.rooms.dependencies import (
    get_combat_core_roll_service,
    get_table_event_service,
)
from app.domain.combat.core_rolls import (
    SavingThrowInput,
    SavingThrowResultView,
)
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource, RollModifierMode
from app.domain.rooms.service import RoomService
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.main import app
from app.persistence.rooms.p3c_runtime import roll_results
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.table_runtime import session_events
from tests.test_p4d_persistence import _running_character_table
from tests.test_p4e_concentration_routing import (
    _make_character_concentration_request,
    _make_services,
)
from tests.test_p4f_condition_pipeline import _running_table


def test_paralyzed_monster_dex_save_auto_fails_and_records_roll() -> None:
    # 1. DEX save vs paralyzed Monster (DM rolls) + restrained Character:
    # Monster view auto_fail is True, Character view auto_fail is False;
    # list_pending_rolls for DM shows the same;
    # DM completes Monster save with physical raw die 20 -> succeeded is False,
    # auto_fail is True, total is 20 + modifier; exactly one roll_results row;
    # combat.save_resolved event payload has succeeded False and auto_fail True.
    table, _attacks, core_rolls, hero, monster, _monster_id = _running_table(
        character_conditions=[{"condition_ref": "srd5.1:condition:restrained", "note": "tied"}],
        monster_conditions=[{"condition_ref": "srd5.1:condition:paralyzed", "note": "stiff", "visibility": "public"}],
    )
    try:
        response = core_rolls.request_saving_throws(
            table.dm_actor,
            SavingThrowInput(
                target_entry_ids=(hero.id, monster.id),
                ability_ref="dexterity",
                dc=15,
                modifier_mode=RollModifierMode.NORMAL,
                idempotency_key="t1-dex-saves",
            ),
        )
        hero_req = next(r for r in response.requests if r.target_entry_id == hero.id)
        monster_req = next(r for r in response.requests if r.target_entry_id == monster.id)

        assert hero_req.auto_fail is False
        assert monster_req.auto_fail is True

        # DM list_pending_rolls
        dm_pending = core_rolls.list_pending_rolls(table.dm_actor)
        pending_hero = next(p for p in dm_pending if p.id == hero_req.id)
        pending_monster = next(p for p in dm_pending if p.id == monster_req.id)
        assert pending_hero.auto_fail is False
        assert pending_monster.auto_fail is True

        # DM completes Monster save with raw die 20
        result = core_rolls.complete_saving_throw(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=monster_req.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="t1-monster-dex-roll",
            ),
        )
        assert isinstance(result, SavingThrowResultView)
        assert result.succeeded is False
        assert result.auto_fail is True
        assert result.total == 20 + monster_req.modifier

        # Exactly one roll_results row
        with table.engine.connect() as conn:
            rows = conn.execute(
                select(roll_results).where(roll_results.c.roll_request_id == monster_req.id)
            ).mappings().all()
            assert len(rows) == 1

            # combat.save_resolved event payload
            event = conn.execute(
                select(session_events).where(
                    session_events.c.session_id == table.session_id,
                    session_events.c.kind == "combat.save_resolved",
                ).order_by(session_events.c.seq.desc())
            ).mappings().first()
            assert event is not None
            assert event["payload"]["succeeded"] is False
            assert event["payload"]["auto_fail"] is True
    finally:
        table.engine.dispose()


def test_auto_fail_saving_throw_idempotent_retry_preserves_auto_fail() -> None:
    # 2. Retry with same idempotency_key -> same result_id, succeeded is False,
    # auto_fail is True, still exactly one roll_results row.
    table, _attacks, core_rolls, hero, monster, _monster_id = _running_table(
        monster_conditions=[{"condition_ref": "srd5.1:condition:paralyzed", "note": "stiff", "visibility": "public"}],
    )
    try:
        response = core_rolls.request_saving_throws(
            table.dm_actor,
            SavingThrowInput(
                target_entry_ids=(monster.id,),
                ability_ref="dexterity",
                dc=15,
                modifier_mode=RollModifierMode.NORMAL,
                idempotency_key="t2-dex-save",
            ),
        )
        monster_req = response.requests[0]
        assert monster_req.auto_fail is True

        first = core_rolls.complete_saving_throw(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=monster_req.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="t2-retry-key",
            ),
        )
        assert first.succeeded is False
        assert first.auto_fail is True

        second = core_rolls.complete_saving_throw(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=monster_req.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="t2-retry-key",
            ),
        )
        assert second.result_id == first.result_id
        assert second.succeeded is False
        assert second.auto_fail is True

        with table.engine.connect() as conn:
            rows = conn.execute(
                select(roll_results).where(roll_results.c.roll_request_id == monster_req.id)
            ).mappings().all()
            assert len(rows) == 1
    finally:
        table.engine.dispose()


def test_paralyzed_monster_wis_save_does_not_auto_fail() -> None:
    # 3. WIS save against paralyzed Monster -> request auto_fail is False;
    # rolling 20 vs DC 15 -> succeeded is True.
    table, _attacks, core_rolls, _hero, monster, _monster_id = _running_table(
        monster_conditions=[{"condition_ref": "srd5.1:condition:paralyzed", "note": "stiff", "visibility": "public"}],
    )
    try:
        response = core_rolls.request_saving_throws(
            table.dm_actor,
            SavingThrowInput(
                target_entry_ids=(monster.id,),
                ability_ref="wisdom",
                dc=15,
                modifier_mode=RollModifierMode.NORMAL,
                idempotency_key="t3-wis-save",
            ),
        )
        monster_req = response.requests[0]
        assert monster_req.auto_fail is False

        result = core_rolls.complete_saving_throw(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=monster_req.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="t3-wis-roll",
            ),
        )
        assert result.succeeded is True
        assert result.auto_fail is False
    finally:
        table.engine.dispose()


def test_restrained_character_dex_save_rolls_with_disadvantage_and_can_succeed() -> None:
    # 4. Restrained Character DEX save -> modifier_mode disadvantage, auto_fail is False,
    # a total >= DC succeeds (disadvantage physical roll expects two dice).
    table, _attacks, core_rolls, hero, _monster, _monster_id = _running_table(
        character_conditions=[{"condition_ref": "srd5.1:condition:restrained", "note": "tied"}],
    )
    try:
        response = core_rolls.request_saving_throws(
            table.dm_actor,
            SavingThrowInput(
                target_entry_ids=(hero.id,),
                ability_ref="dexterity",
                dc=15,
                modifier_mode=RollModifierMode.NORMAL,
                idempotency_key="t4-hero-dex-save",
            ),
        )
        hero_req = response.requests[0]
        assert hero_req.modifier_mode is RollModifierMode.DISADVANTAGE
        assert hero_req.auto_fail is False

        # Two dice for disadvantage: min(18, 19) = 18; 18 + modifier >= DC 15
        result = core_rolls.complete_saving_throw(
            table.player_actor,
            FormalRollInput(
                roll_request_id=hero_req.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(18, 19),
                idempotency_key="t4-hero-roll",
            ),
        )
        assert result.succeeded is True
        assert result.auto_fail is False
        assert result.total == 18 + hero_req.modifier
    finally:
        table.engine.dispose()


def test_player_pending_rolls_view_and_unauthorized_completion_rejection() -> None:
    # 5. Player calling list_pending_rolls sees own request with auto_fail present
    # and no dc; Player must NOT be able to complete Monster request.
    table, _attacks, core_rolls, hero, monster, _monster_id = _running_table(
        character_conditions=[{"condition_ref": "srd5.1:condition:restrained", "note": "tied"}],
        monster_conditions=[{"condition_ref": "srd5.1:condition:paralyzed", "note": "stiff", "visibility": "public"}],
    )
    try:
        response = core_rolls.request_saving_throws(
            table.dm_actor,
            SavingThrowInput(
                target_entry_ids=(hero.id, monster.id),
                ability_ref="dexterity",
                dc=15,
                modifier_mode=RollModifierMode.NORMAL,
                idempotency_key="t5-dex-saves",
            ),
        )
        hero_req = next(r for r in response.requests if r.target_entry_id == hero.id)
        monster_req = next(r for r in response.requests if r.target_entry_id == monster.id)

        player_pending = core_rolls.list_pending_rolls(table.player_actor)
        assert len(player_pending) == 1
        hero_pending = player_pending[0]
        assert hero_pending.id == hero_req.id
        assert hero_pending.auto_fail is False
        assert hero_pending.dc is None

        # Player cannot complete Monster's request
        with pytest.raises(TableEventActorUnauthorizedError):
            core_rolls.complete_saving_throw(
                table.player_actor,
                FormalRollInput(
                    roll_request_id=monster_req.id,
                    source=FormalRollSource.PHYSICAL,
                    raw_dice=(20,),
                    idempotency_key="t5-player-illegal-roll",
                ),
            )
    finally:
        table.engine.dispose()


def test_concentration_saving_throw_has_auto_fail_false() -> None:
    # 6. Concentration check request: stored request auto_fail is False and
    # completing it through CombatCoreRollService.complete_saving_throw returns auto_fail is False.
    table, running, entry = _running_character_table()
    try:
        req_id = _make_character_concentration_request(table, running, entry, idempotency_suffix="t6-conc")
        _conc_service, core_service = _make_services(table)

        stored_req = core_service.repository.get_request(session_id=table.session_id, request_id=req_id)
        assert stored_req is not None
        assert stored_req.auto_fail is False

        result = core_service.complete_saving_throw(
            table.player_actor,
            FormalRollInput(
                roll_request_id=req_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="t6-conc-roll",
            ),
        )
        assert isinstance(result, SavingThrowResultView)
        assert result.auto_fail is False
        assert result.succeeded is True
    finally:
        table.engine.dispose()


def test_rest_pending_rolls_includes_auto_fail_flag() -> None:
    # 7. REST: GET .../combat/pending-rolls (DM) includes "auto_fail": true
    # for the paralyzed Monster's DEX request.
    table, _attacks, core_rolls, hero, monster, _monster_id = _running_table(
        character_conditions=[{"condition_ref": "srd5.1:condition:restrained", "note": "tied"}],
        monster_conditions=[{"condition_ref": "srd5.1:condition:paralyzed", "note": "stiff", "visibility": "public"}],
    )
    try:
        core_rolls.request_saving_throws(
            table.dm_actor,
            SavingThrowInput(
                target_entry_ids=(hero.id, monster.id),
                ability_ref="dexterity",
                dc=15,
                modifier_mode=RollModifierMode.NORMAL,
                idempotency_key="t7-rest-saves",
            ),
        )
        room_repo = RoomRepository(table.engine)
        app.dependency_overrides[get_database_engine] = lambda: table.engine
        app.dependency_overrides[get_room_service] = lambda: RoomService(room_repo)
        app.dependency_overrides[get_table_event_service] = lambda: table.events
        app.dependency_overrides[get_combat_core_roll_service] = lambda: core_rolls

        client = TestClient(app)
        combat_url = (
            f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
            f"/sessions/{table.session_id}/combat"
        )
        response = client.get(
            f"{combat_url}/pending-rolls",
            headers={"Authorization": f"Bearer {table.dm_token}"},
        )
        assert response.status_code == 200
        items = response.json()
        monster_item = next(item for item in items if item["target_entry_id"] == str(monster.id))
        hero_item = next(item for item in items if item["target_entry_id"] == str(hero.id))

        assert monster_item["auto_fail"] is True
        assert hero_item["auto_fail"] is False
    finally:
        app.dependency_overrides.clear()
        table.engine.dispose()
