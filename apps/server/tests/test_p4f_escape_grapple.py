from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, insert, select, update

from app.api.dependencies import get_content_registry, get_database_engine
from app.api.rooms.access import get_room_service
from app.api.rooms.ai_controllers import get_ai_controller_service
from app.api.rooms.dependencies import (
    get_combat_initiative_service,
    get_combat_service,
    get_combat_special_attack_service,
    get_monster_instance_service,
    get_table_event_service,
)
from app.content import load_default_content_registry
from app.domain.character.schemas import CharacterState
from app.domain.combat.ai_tools import CombatAIToolApplicationService
from app.domain.combat.lifecycle import CombatStateConflictError
from app.domain.combat.monster_instances import MonsterInstanceService
from app.domain.combat.resolution import SpecialAttackKind
from app.domain.combat.special_attacks import (
    CombatSpecialAttackService,
    SpecialAttackAdjudicationInput,
    SpecialAttackRequestInput,
)
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import AIControllerService
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.domain.rooms.service import RoomService
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.main import app
from app.mcp.dependencies import get_ai_tool_application_service
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.persistence.characters import CharacterRepository, character_states
from app.persistence.combat.resolution import PRONE_REF, _condition_ref
from app.persistence.combat.special_attacks import GRAPPLED_REF
from app.persistence.combat.tables import combat_actions, combat_entries
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.p3c_runtime import roll_requests
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.table_runtime import session_events
from app.persistence.rooms.tables import ai_controller_grants, campaign_seats, sessions
from tests.test_p4c_special_attacks import _entry, _resolve_success, _running_table


def test_monster_escapes_grapple_success_and_idempotency() -> None:
    table, service, player_entry_id, monster_entry_id, monster_id = _running_table(free_hand=True)
    try:
        # 1. Player grapples the monster on Player's turn
        pending = service.request_special_attack(
            table.player_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=player_entry_id,
                target_entry_id=monster_entry_id,
                kind=SpecialAttackKind.GRAPPLE,
                idempotency_key="p4f-init-grapple",
            ),
        )
        _resolve_success(table, service, pending)
        monster_inst = table.monsters.get_instance(monster_id)
        assert monster_inst is not None
        assert any(_condition_ref(c) == GRAPPLED_REF for c in monster_inst.conditions)

        # 2. Advance to monster's turn
        table.combat.advance_turn(table.dm_actor, idempotency_key="p4f-adv-to-monster")
        combat = table.combat.get_active_combat(table.dm_actor)
        assert combat is not None
        assert combat.current_turn_entry_id == monster_entry_id
        rev_before = combat.revision
        m_entry_before = _entry(table, monster_entry_id)
        assert m_entry_before.action_available is True
        attacks_used_before = m_entry_before.attacks_used

        # 3. DM requests escape_grapple for monster
        escape_view = service.request_special_attack(
            table.dm_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=monster_entry_id,
                target_entry_id=player_entry_id,
                kind=SpecialAttackKind.ESCAPE_GRAPPLE,
                idempotency_key="p4f-escape-req-1",
            ),
        )
        assert escape_view.status == "waiting_for_roll"
        assert escape_view.in_reach is None
        assert escape_view.attacker_roll_request_id is not None
        assert escape_view.defender_roll_request_id is not None
        assert escape_view.defender_skill == "srd5.1:skill:athletics"

        # Monster entry economy: Action spent, attacks_used untouched
        m_entry_during = _entry(table, monster_entry_id)
        assert m_entry_during.action_available is False
        assert m_entry_during.attacks_used == attacks_used_before
        combat_after_req = table.combat.get_active_combat(table.dm_actor)
        assert combat_after_req is not None
        assert combat_after_req.revision == rev_before + 1

        # 4. Both rolls (escaper high = 20, grappler low = 1)
        r1 = service.complete_special_attack_roll(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=escape_view.attacker_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="esc-roll-attacker",
            ),
        )
        assert r1.status == "waiting_for_roll"

        r2 = service.complete_special_attack_roll(
            table.player_actor,
            FormalRollInput(
                roll_request_id=escape_view.defender_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(1,),
                idempotency_key="esc-roll-defender",
            ),
        )
        assert r2.status == "resolved"
        assert r2.resolution_result is not None
        assert r2.resolution_result["status"] == "success"
        assert r2.resolution_result["condition_to_remove"] == "grappled"

        # Monster instance conditions no longer contain GRAPPLED_REF
        inst_after = table.monsters.get_instance(monster_id)
        assert inst_after is not None
        assert not any(_condition_ref(c) == GRAPPLED_REF for c in inst_after.conditions)

        # 5. Retry of the second roll with the same idempotency_key is a no-op
        with table.engine.connect() as conn:
            events_after_r2 = conn.execute(
                select(func.count()).select_from(session_events).where(session_events.c.session_id == table.session_id)
            ).scalar_one()
        retry_r2 = service.complete_special_attack_roll(
            table.player_actor,
            FormalRollInput(
                roll_request_id=escape_view.defender_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(1,),
                idempotency_key="esc-roll-defender",
            ),
        )
        with table.engine.connect() as conn:
            events_after_retry = conn.execute(
                select(func.count()).select_from(session_events).where(session_events.c.session_id == table.session_id)
            ).scalar_one()
        assert events_after_retry == events_after_r2
        inst_retry = table.monsters.get_instance(monster_id)
        assert inst_retry is not None
        assert not any(_condition_ref(c) == GRAPPLED_REF for c in inst_retry.conditions)
        assert retry_r2.status == "resolved"
    finally:
        table.engine.dispose()


def test_escape_grapple_failure_and_tie_keep_grappled_and_action_spent() -> None:
    # Part A: escaper rolls 5 vs grappler rolls 15 (lost)
    table, service, player_entry_id, monster_entry_id, monster_id = _running_table(free_hand=True)
    try:
        pending = service.request_special_attack(
            table.player_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=player_entry_id,
                target_entry_id=monster_entry_id,
                kind=SpecialAttackKind.GRAPPLE,
                idempotency_key="init-grapple-fail",
            ),
        )
        _resolve_success(table, service, pending)
        table.combat.advance_turn(table.dm_actor, idempotency_key="adv-monster-fail")

        escape_view = service.request_special_attack(
            table.dm_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=monster_entry_id,
                target_entry_id=player_entry_id,
                kind=SpecialAttackKind.ESCAPE_GRAPPLE,
                idempotency_key="req-fail",
            ),
        )
        assert escape_view.attacker_roll_request_id is not None
        assert escape_view.defender_roll_request_id is not None

        service.complete_special_attack_roll(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=escape_view.attacker_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(5,),
                idempotency_key="roll-esc-5",
            ),
        )
        resolved = service.complete_special_attack_roll(
            table.player_actor,
            FormalRollInput(
                roll_request_id=escape_view.defender_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(15,),
                idempotency_key="roll-grp-15",
            ),
        )
        assert resolved.status == "resolved"
        assert resolved.resolution_result is not None
        assert resolved.resolution_result["status"] == "failure"
        assert resolved.resolution_result["reason"] == "opposed_check_lost_or_tied"
        assert resolved.resolution_result["condition_to_remove"] is None

        inst = table.monsters.get_instance(monster_id)
        assert inst is not None
        assert any(_condition_ref(c) == GRAPPLED_REF for c in inst.conditions)
        m_entry = _entry(table, monster_entry_id)
        assert m_entry.action_available is False
    finally:
        table.engine.dispose()

    # Part B: equal totals (tie: escaper total == grappler total)
    table2, service2, p_id2, m_id2, inst_id2 = _running_table(free_hand=True)
    try:
        pending2 = service2.request_special_attack(
            table2.player_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=p_id2,
                target_entry_id=m_id2,
                kind=SpecialAttackKind.GRAPPLE,
                idempotency_key="init-grapple-tie",
            ),
        )
        _resolve_success(table2, service2, pending2)
        table2.combat.advance_turn(table2.dm_actor, idempotency_key="adv-monster-tie")

        escape_view2 = service2.request_special_attack(
            table2.dm_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=m_id2,
                target_entry_id=p_id2,
                kind=SpecialAttackKind.ESCAPE_GRAPPLE,
                idempotency_key="req-tie",
            ),
        )
        assert escape_view2.attacker_roll_request_id is not None
        assert escape_view2.defender_roll_request_id is not None

        with table2.engine.connect() as conn:
            esc_mod = int(conn.execute(
                select(roll_requests.c.flat_adjustment).where(
                    roll_requests.c.id == escape_view2.attacker_roll_request_id
                )
            ).scalar_one())
            grp_mod = int(conn.execute(
                select(roll_requests.c.flat_adjustment).where(
                    roll_requests.c.id == escape_view2.defender_roll_request_id
                )
            ).scalar_one())
        target_total = max(10, 1 + esc_mod, 1 + grp_mod)
        raw_esc = target_total - esc_mod
        raw_grp = target_total - grp_mod
        assert 1 <= raw_esc <= 20
        assert 1 <= raw_grp <= 20

        service2.complete_special_attack_roll(
            table2.dm_actor,
            FormalRollInput(
                roll_request_id=escape_view2.attacker_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(raw_esc,),
                idempotency_key="roll-esc-tie",
            ),
        )
        resolved_tie = service2.complete_special_attack_roll(
            table2.player_actor,
            FormalRollInput(
                roll_request_id=escape_view2.defender_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(raw_grp,),
                idempotency_key="roll-grp-tie",
            ),
        )
        assert resolved_tie.status == "resolved"
        assert resolved_tie.resolution_result is not None
        assert resolved_tie.resolution_result["status"] == "failure"
        assert resolved_tie.resolution_result["reason"] == "opposed_check_lost_or_tied"
        assert resolved_tie.resolution_result["attacker_total"] == resolved_tie.resolution_result["target_total"]

        inst2 = table2.monsters.get_instance(inst_id2)
        assert inst2 is not None
        assert any(_condition_ref(c) == GRAPPLED_REF for c in inst2.conditions)
        m_entry2 = _entry(table2, m_id2)
        assert m_entry2.action_available is False
    finally:
        table2.engine.dispose()


def test_character_escapes_grapple_success_and_preserves_other_conditions() -> None:
    table, service, player_entry_id, monster_entry_id, _monster_id = _running_table(free_hand=True)
    try:
        # Advance to monster's turn so monster grapples the character
        table.combat.advance_turn(table.dm_actor, idempotency_key="adv-monster-p3")
        combat = table.combat.get_active_combat(table.dm_actor)
        assert combat is not None
        assert combat.current_turn_entry_id == monster_entry_id

        m_grapple = service.request_special_attack(
            table.dm_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=monster_entry_id,
                target_entry_id=player_entry_id,
                kind=SpecialAttackKind.GRAPPLE,
                idempotency_key="m-grapple-p3",
            ),
        )
        resumed = service.adjudicate_special_attack(
            table.dm_actor,
            SpecialAttackAdjudicationInput(
                action_id=m_grapple.action_id,
                in_reach=True,
                idempotency_key="m-reach-p3",
            ),
        )
        assert resumed.attacker_roll_request_id is not None
        assert resumed.defender_roll_request_id is not None
        service.complete_special_attack_roll(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=resumed.attacker_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="m-r1-p3",
            ),
        )
        service.complete_special_attack_roll(
            table.player_actor,
            FormalRollInput(
                roll_request_id=resumed.defender_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(1,),
                idempotency_key="m-r2-p3",
            ),
        )

        char_repo = CharacterRepository(table.engine, load_default_content_registry())
        char_pre = char_repo.load_character(table.character_id)
        assert any(c.condition_ref == GRAPPLED_REF for c in char_pre.state.conditions)

        # Add another condition (PRONE_REF) to character state
        payload = char_pre.state.model_dump(mode="json")
        payload["conditions"].append({"condition_ref": PRONE_REF, "note": "Knocked prone earlier"})
        CharacterState.model_validate(payload)
        with table.engine.begin() as conn:
            conn.execute(
                update(character_states)
                .where(character_states.c.character_id == table.character_id)
                .values(state_payload=payload, state_revision=character_states.c.state_revision + 1)
            )

        with table.engine.connect() as conn:
            rev_before = conn.execute(
                select(character_states.c.state_revision).where(
                    character_states.c.character_id == table.character_id
                )
            ).scalar_one()

        char_before = char_repo.load_character(table.character_id)
        assert any(c.condition_ref == GRAPPLED_REF for c in char_before.state.conditions)
        assert any(c.condition_ref == PRONE_REF for c in char_before.state.conditions)

        # Advance to character's turn
        table.combat.advance_turn(table.dm_actor, idempotency_key="adv-char-p3")
        combat = table.combat.get_active_combat(table.dm_actor)
        assert combat is not None
        assert combat.current_turn_entry_id == player_entry_id

        p_entry_before = _entry(table, player_entry_id)
        assert p_entry_before.action_available is True

        # Player requests escape
        escape_view = service.request_special_attack(
            table.player_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=player_entry_id,
                target_entry_id=monster_entry_id,
                kind=SpecialAttackKind.ESCAPE_GRAPPLE,
                idempotency_key="char-esc-p3",
            ),
        )
        assert escape_view.status == "waiting_for_roll"
        assert escape_view.attacker_roll_request_id is not None
        assert escape_view.defender_roll_request_id is not None

        p_entry_during = _entry(table, player_entry_id)
        assert p_entry_during.action_available is False

        # Complete rolls (player rolls 20, monster rolls 1)
        service.complete_special_attack_roll(
            table.player_actor,
            FormalRollInput(
                roll_request_id=escape_view.attacker_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="char-r1-p3",
            ),
        )
        res = service.complete_special_attack_roll(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=escape_view.defender_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(1,),
                idempotency_key="char-r2-p3",
            ),
        )
        assert res.status == "resolved"
        assert res.resolution_result is not None
        assert res.resolution_result["status"] == "success"
        assert res.resolution_result["condition_to_remove"] == "grappled"

        # Check conditions on character: grappled removed, prone remains
        char_after = char_repo.load_character(table.character_id)
        assert not any(c.condition_ref == GRAPPLED_REF for c in char_after.state.conditions)
        assert any(c.condition_ref == PRONE_REF for c in char_after.state.conditions)

        # Check state_revision bumped exactly once
        with table.engine.connect() as conn:
            rev_after = conn.execute(
                select(character_states.c.state_revision).where(
                    character_states.c.character_id == table.character_id
                )
            ).scalar_one()
        assert rev_after == rev_before + 1
    finally:
        table.engine.dispose()


def test_escape_grapple_rejections_have_zero_side_effects() -> None:
    table, service, player_entry_id, monster_entry_id, _monster_id = _running_table(free_hand=True)
    try:
        def assert_no_escape_side_effects(expected_action_avail: bool, expected_attacks: int, entry_id: UUID) -> None:
            with table.engine.connect() as conn:
                escape_actions = conn.execute(
                    select(combat_actions).where(
                        combat_actions.c.action_kind == "escape_grapple"
                    )
                ).mappings().all()
            with table.engine.connect() as conn:
                events = conn.execute(
                    select(session_events.c.kind).where(
                        session_events.c.session_id == table.session_id
                    )
                ).scalars().all()
            assert escape_actions == []
            assert not any(e == "combat.escape_grapple_requested" for e in events)
            entry = _entry(table, entry_id)
            assert entry.action_available == expected_action_avail
            assert entry.attacks_used == expected_attacks

        # 1. Escaper not grappled
        p_before = _entry(table, player_entry_id)
        with pytest.raises(CombatStateConflictError, match="Combatant is not grappled"):
            service.request_special_attack(
                table.player_actor,
                SpecialAttackRequestInput(
                    attacker_entry_id=player_entry_id,
                    target_entry_id=monster_entry_id,
                    kind=SpecialAttackKind.ESCAPE_GRAPPLE,
                    idempotency_key="not-grappled-fail",
                ),
            )
        assert_no_escape_side_effects(p_before.action_available, p_before.attacks_used, player_entry_id)

        # Grapple the monster so it IS grappled
        pending = service.request_special_attack(
            table.player_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=player_entry_id,
                target_entry_id=monster_entry_id,
                kind=SpecialAttackKind.GRAPPLE,
                idempotency_key="grapple-for-rejections",
            ),
        )
        _resolve_success(table, service, pending)

        # 2. Not the escaper's turn (monster is grappled, but current turn is player)
        combat = table.combat.get_active_combat(table.dm_actor)
        assert combat is not None
        assert combat.current_turn_entry_id == player_entry_id
        m_before = _entry(table, monster_entry_id)
        with pytest.raises(CombatStateConflictError, match="current turn"):
            service.request_special_attack(
                table.dm_actor,
                SpecialAttackRequestInput(
                    attacker_entry_id=monster_entry_id,
                    target_entry_id=player_entry_id,
                    kind=SpecialAttackKind.ESCAPE_GRAPPLE,
                    idempotency_key="not-turn-fail",
                ),
            )
        assert_no_escape_side_effects(m_before.action_available, m_before.attacks_used, monster_entry_id)

        # Advance to monster turn
        table.combat.advance_turn(table.dm_actor, idempotency_key="adv-to-monster-rej")

        # 3. Action already spent
        with table.engine.begin() as conn:
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == monster_entry_id)
                .values(action_available=False)
            )
        with pytest.raises(CombatStateConflictError, match="Action is already spent"):
            service.request_special_attack(
                table.dm_actor,
                SpecialAttackRequestInput(
                    attacker_entry_id=monster_entry_id,
                    target_entry_id=player_entry_id,
                    kind=SpecialAttackKind.ESCAPE_GRAPPLE,
                    idempotency_key="action-spent-fail",
                ),
            )
        assert_no_escape_side_effects(False, 0, monster_entry_id)

        # Restore action_available
        with table.engine.begin() as conn:
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == monster_entry_id)
                .values(action_available=True)
            )

        # 4. Player requesting escape for the monster entry
        with pytest.raises(TableEventActorUnauthorizedError):
            service.request_special_attack(
                table.player_actor,
                SpecialAttackRequestInput(
                    attacker_entry_id=monster_entry_id,
                    target_entry_id=player_entry_id,
                    kind=SpecialAttackKind.ESCAPE_GRAPPLE,
                    idempotency_key="player-for-monster-fail",
                ),
            )
        assert_no_escape_side_effects(True, 0, monster_entry_id)

        # 5. Regression guard: kind="grapple" still requires adjudication
        grapple_guard = service.request_special_attack(
            table.dm_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=monster_entry_id,
                target_entry_id=player_entry_id,
                kind=SpecialAttackKind.GRAPPLE,
                idempotency_key="guard-grapple-req",
            ),
        )
        assert grapple_guard.status == "dm_adjudication_required"
        assert grapple_guard.in_reach is None
        assert grapple_guard.attacker_roll_request_id is None
    finally:
        table.engine.dispose()


def test_escape_grapple_rest_and_mcp_parity() -> None:
    table, service, player_entry_id, monster_entry_id, monster_id = _running_table(free_hand=True)
    registry = load_default_content_registry()
    room_service = RoomService(RoomRepository(table.engine))
    monster_service = MonsterInstanceService(
        monster_repository=table.monsters,
        content_registry=registry,
        table_event_service=table.events,
    )
    grant_repo = AIControllerGrantRepository(table.engine)
    ai_controller_service = AIControllerService(grant_repo, table.events)

    combat_ai_tool_service = CombatAIToolApplicationService(
        ai_controller_service=ai_controller_service,
        session_service=table.session_service,
        stage_service=object(),
        action_service=object(),
        roll_service=table.rolls,
        state_service=object(),
        pending_action_service=object(),
        event_service=table.events,
        workspace_service=object(),
        combat_service=table.combat,
        combat_attack_service=object(),
        combat_resolution_service=object(),
        combat_core_roll_service=object(),
        combat_special_attack_service=service,
        combat_initiative_service=table.initiative,
        monster_instance_service=monster_service,
        combat_spell_service=object(),
        combat_concentration_service=object(),
        combat_reaction_service=object(),
        combat_adjudication_service=object(),
    )

    app.state.ai_tool_application_service = combat_ai_tool_service
    app.dependency_overrides[get_database_engine] = lambda: table.engine
    app.dependency_overrides[get_content_registry] = lambda: registry
    app.dependency_overrides[get_room_service] = lambda: room_service
    app.dependency_overrides[get_combat_service] = lambda: table.combat
    app.dependency_overrides[get_combat_initiative_service] = lambda: table.initiative
    app.dependency_overrides[get_monster_instance_service] = lambda: monster_service
    app.dependency_overrides[get_table_event_service] = lambda: table.events
    app.dependency_overrides[get_combat_special_attack_service] = lambda: service
    app.dependency_overrides[get_ai_controller_service] = lambda: ai_controller_service
    app.dependency_overrides[get_ai_tool_application_service] = lambda: combat_ai_tool_service

    client = TestClient(app)
    try:
        # Part A: Character is grappled, Player calls REST to escape
        # 1. Advance to monster's turn, monster grapples character
        table.combat.advance_turn(table.dm_actor, idempotency_key="adv-monster-parity")
        pending_m = service.request_special_attack(
            table.dm_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=monster_entry_id,
                target_entry_id=player_entry_id,
                kind=SpecialAttackKind.GRAPPLE,
                idempotency_key="m-grapple-parity",
            ),
        )
        resumed_m = service.adjudicate_special_attack(
            table.dm_actor,
            SpecialAttackAdjudicationInput(
                action_id=pending_m.action_id,
                in_reach=True,
                idempotency_key="m-reach-parity",
            ),
        )
        assert resumed_m.attacker_roll_request_id is not None
        assert resumed_m.defender_roll_request_id is not None
        service.complete_special_attack_roll(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=resumed_m.attacker_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="m-r1-parity",
            ),
        )
        service.complete_special_attack_roll(
            table.player_actor,
            FormalRollInput(
                roll_request_id=resumed_m.defender_roll_request_id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(1,),
                idempotency_key="m-r2-parity",
            ),
        )

        # Advance to character's turn
        table.combat.advance_turn(table.dm_actor, idempotency_key="adv-char-parity")
        rest_url = (
            f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
            f"/sessions/{table.session_id}/combat/special-attacks/request"
        )
        rest_resp = client.post(
            rest_url,
            json={
                "attacker_entry_id": str(player_entry_id),
                "target_entry_id": str(monster_entry_id),
                "kind": "escape_grapple",
                "idempotency_key": "rest-escape-char",
            },
            headers={"Authorization": f"Bearer {table.player_token}"},
        )
        assert rest_resp.status_code == 200, rest_resp.text
        rest_data = rest_resp.json()
        assert rest_data["status"] == "waiting_for_roll"
        assert rest_data["kind"] == "escape_grapple"
        assert rest_data["attacker_roll_request_id"] is not None
        assert rest_data["defender_roll_request_id"] is not None

        # Resolve Player's escape rolls
        service.complete_special_attack_roll(
            table.player_actor,
            FormalRollInput(
                roll_request_id=UUID(rest_data["attacker_roll_request_id"]),
                source=FormalRollSource.PHYSICAL,
                raw_dice=(20,),
                idempotency_key="p-esc-r1",
            ),
        )
        service.complete_special_attack_roll(
            table.dm_actor,
            FormalRollInput(
                roll_request_id=UUID(rest_data["defender_roll_request_id"]),
                source=FormalRollSource.PHYSICAL,
                raw_dice=(1,),
                idempotency_key="p-esc-r2",
            ),
        )

        # Part B: Advance turn, Player grapples monster, AI DM calls MCP combat_request_special_attack
        # Advance to round 2, player turn
        table.combat.advance_turn(table.dm_actor, idempotency_key="adv-to-monster-r2")
        table.combat.advance_turn(table.dm_actor, idempotency_key="adv-to-player-r2")
        pending_p = service.request_special_attack(
            table.player_actor,
            SpecialAttackRequestInput(
                attacker_entry_id=player_entry_id,
                target_entry_id=monster_entry_id,
                kind=SpecialAttackKind.GRAPPLE,
                idempotency_key="p-grapple-r2",
            ),
        )
        _resolve_success(table, service, pending_p)
        # Advance to monster turn
        table.combat.advance_turn(table.dm_actor, idempotency_key="adv-to-monster-r2b")

        # Mint AI DM grant
        dm_seat_id = table.dm_actor.seat_id
        minted = mint_ai_controller_token()
        now = datetime.now(timezone.utc)
        with table.engine.begin() as connection:
            connection.execute(
                insert(ai_controller_grants).values(
                    id=minted.grant_id,
                    room_id=table.room_id,
                    campaign_id=table.campaign_id,
                    seat_id=dm_seat_id,
                    role="dm",
                    session_id=table.session_id,
                    secret_hash=minted.secret_hash,
                    secret_prefix=minted.display_hint,
                    generation=1,
                    status="active",
                    pre_session_expires_at=None,
                    handoff_return_access_session_id=None,
                    temporary_instruction=None,
                    created_at=now,
                    bound_at=now,
                    revoked_at=None,
                    last_seen_at=None,
                )
            )
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == dm_seat_id)
                .values(
                    controller_kind="ai",
                    ai_controller_grant_id=minted.grant_id,
                    controller_epoch=1,
                    controller_access_session_id=None,
                    updated_at=now,
                )
            )
            connection.execute(
                update(sessions)
                .where(sessions.c.id == table.session_id)
                .values(
                    dm_controller_kind="ai",
                    dm_controller_ai_grant_id=minted.grant_id,
                    dm_controller_generation=1,
                    dm_controller_access_session_id=None,
                )
            )

        # AI DM calls MCP combat_request_special_attack
        mcp_req = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "combat_request_special_attack",
                    "arguments": {
                        "attacker_entry_id": str(monster_entry_id),
                        "target_entry_id": str(player_entry_id),
                        "kind": "escape_grapple",
                    },
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                        "io.modelcontextprotocol/clientCapabilities": {},
                        "io.modelcontextprotocol/clientInfo": {"name": "p4f-test", "version": "1"},
                    },
                },
            },
            headers={
                "Authorization": f"Bearer {minted.plaintext}",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "Mcp-Method": "tools/call",
                "Mcp-Name": "combat_request_special_attack",
            },
        )
        assert mcp_req.status_code == 200, mcp_req.text
        mcp_req_data = mcp_req.json()["result"]["structuredContent"]["data"]
        assert mcp_req_data["status"] == "waiting_for_roll"
        assert mcp_req_data["kind"] == "escape_grapple"
        esc_roll_id = mcp_req_data["attacker_roll_request_id"]
        grp_roll_id = mcp_req_data["defender_roll_request_id"]

        # AI DM calls MCP combat_roll_special_attack for monster
        mcp_roll1 = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "combat_roll_special_attack",
                    "arguments": {
                        "roll_request_id": esc_roll_id,
                    },
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                        "io.modelcontextprotocol/clientCapabilities": {},
                        "io.modelcontextprotocol/clientInfo": {"name": "p4f-test", "version": "1"},
                    },
                },
            },
            headers={
                "Authorization": f"Bearer {minted.plaintext}",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "Mcp-Method": "tools/call",
                "Mcp-Name": "combat_roll_special_attack",
            },
        )
        assert mcp_roll1.status_code == 200, mcp_roll1.text
        assert not mcp_roll1.json()["result"].get("isError")
        roll1_data = mcp_roll1.json()["result"]["structuredContent"]["data"]
        assert roll1_data["status"] == "waiting_for_roll"

        # AI DM calls MCP combat_roll_special_attack for defender (DM proxy)
        mcp_roll2 = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "combat_roll_special_attack",
                    "arguments": {
                        "roll_request_id": grp_roll_id,
                    },
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                        "io.modelcontextprotocol/clientCapabilities": {},
                        "io.modelcontextprotocol/clientInfo": {"name": "p4f-test", "version": "1"},
                    },
                },
            },
            headers={
                "Authorization": f"Bearer {minted.plaintext}",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "Mcp-Method": "tools/call",
                "Mcp-Name": "combat_roll_special_attack",
            },
        )
        assert mcp_roll2.status_code == 200, mcp_roll2.text
        assert not mcp_roll2.json()["result"].get("isError")
        roll2_data = mcp_roll2.json()["result"]["structuredContent"]["data"]
        assert roll2_data["status"] == "resolved"
        assert roll2_data["resolution_result"] is not None
        assert "condition_to_remove" in roll2_data["resolution_result"]
    finally:
        app.dependency_overrides.clear()
        table.engine.dispose()
