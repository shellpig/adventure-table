from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.content import load_default_content_registry
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.attacks import AttackRequestInput, CombatAttackService
from app.domain.combat.condition_modifiers import attack_modifiers, save_modifiers
from app.domain.combat.core_rolls import CombatCoreRollService, SavingThrowInput
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    CombatActionInput,
    CombatActionKind,
    CombatEconomyCost,
    StartCombatInput,
)
from app.domain.combat.resolution import AttackKind, RollMode
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.domain.rooms.rolls import (
    FormalRollInput,
    FormalRollSource,
    RollModifierMode,
    RollService,
)
from app.main import app
from app.persistence.characters import CharacterRepository
from app.persistence.combat.adjudication import CombatAdjudicationRepository
from app.persistence.combat.attacks import CombatAttackRepository
from app.persistence.combat.core_rolls import CombatCoreRollRepository
from app.domain.combat.roll_compat import CombatAwareRollRepository
from app.persistence.combat.tables import combat_actions
from tests.test_p4b_combat_lifecycle import _setup
from tests.test_p4e_mcp_combat_context_and_effects import _mcp_call, mcp_combat_fixture


def test_dodge_unit_attack_modifiers() -> None:
    # 1. Normal attack vs dodging target -> DISADVANTAGE with "target:dodging"
    decision = attack_modifiers(
        chosen=RollMode.NORMAL,
        attack_kind=AttackKind.MELEE,
        attacker_conditions=(),
        target_conditions=(),
        target_dodging=True,
    )
    assert decision.mode is RollMode.DISADVANTAGE
    assert "target:dodging" in decision.disadvantage_sources
    assert decision.advantage_sources == ()

    # 2. Target paralyzed (blocks_actions) -> dodge benefit lost
    decision_paralyzed = attack_modifiers(
        chosen=RollMode.NORMAL,
        attack_kind=AttackKind.MELEE,
        attacker_conditions=(),
        target_conditions=("srd5.1:condition:paralyzed",),
        target_dodging=True,
    )
    assert "target:dodging" not in decision_paralyzed.disadvantage_sources
    # Paralyzed grants advantage to attacks against
    assert decision_paralyzed.mode is RollMode.ADVANTAGE
    assert "target:paralyzed" in decision_paralyzed.advantage_sources

    # 3. Target grappled (speed_zero) -> dodge benefit lost
    decision_grappled = attack_modifiers(
        chosen=RollMode.NORMAL,
        attack_kind=AttackKind.MELEE,
        attacker_conditions=(),
        target_conditions=("srd5.1:condition:grappled",),
        target_dodging=True,
    )
    assert "target:dodging" not in decision_grappled.disadvantage_sources
    assert decision_grappled.mode is RollMode.NORMAL

    # 4. Target restrained (speed_zero) -> dodge benefit lost
    decision_restrained = attack_modifiers(
        chosen=RollMode.NORMAL,
        attack_kind=AttackKind.MELEE,
        attacker_conditions=(),
        target_conditions=("srd5.1:condition:restrained",),
        target_dodging=True,
    )
    assert "target:dodging" not in decision_restrained.disadvantage_sources
    # Restrained gives advantage to attacks against
    assert decision_restrained.mode is RollMode.ADVANTAGE

    # 5. Chosen advantage + dodging -> cancel to NORMAL
    decision_cancelled = attack_modifiers(
        chosen=RollMode.ADVANTAGE,
        attack_kind=AttackKind.MELEE,
        attacker_conditions=(),
        target_conditions=(),
        target_dodging=True,
    )
    assert decision_cancelled.mode is RollMode.NORMAL
    assert "chosen:advantage" in decision_cancelled.advantage_sources
    assert "target:dodging" in decision_cancelled.disadvantage_sources


def test_dodge_unit_save_modifiers() -> None:
    # 1. Dexterity save with target_dodging -> ADVANTAGE with "target:dodging"
    decision_dex = save_modifiers(
        chosen=RollModifierMode.NORMAL,
        ability_ref="dexterity",
        target_conditions=(),
        target_dodging=True,
    )
    assert decision_dex.mode is RollModifierMode.ADVANTAGE
    assert "target:dodging" in decision_dex.advantage_sources
    assert decision_dex.disadvantage_sources == ()

    # 2. Wisdom save with target_dodging -> unchanged (NORMAL)
    decision_wis = save_modifiers(
        chosen=RollModifierMode.NORMAL,
        ability_ref="wisdom",
        target_conditions=(),
        target_dodging=True,
    )
    assert decision_wis.mode is RollModifierMode.NORMAL
    assert "target:dodging" not in decision_wis.advantage_sources

    # 3. Dexterity save with paralyzed target -> blocks_actions loses dodge benefit, auto-fails
    decision_paralyzed = save_modifiers(
        chosen=RollModifierMode.NORMAL,
        ability_ref="dexterity",
        target_conditions=("srd5.1:condition:paralyzed",),
        target_dodging=True,
    )
    assert "target:dodging" not in decision_paralyzed.advantage_sources
    assert decision_paralyzed.auto_fail is True


def test_dodge_lifecycle_through_services() -> None:
    table = _setup()
    try:
        monster = table.monsters.create_instance(
            campaign_id=table.campaign_id,
            name="Nimble Goblin",
            rules_snapshot={"armor_class": 15, "max_hp": 10, "speed": {"walk": 30}},
            current_hp=10,
        )
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="dodge-start-combat"),
        )
        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=monster.id, idempotency_key="dodge-add-goblin"),
        )

        requested = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(idempotency_key="dodge-init-req"),
        )
        # Monster rolls 20, player rolls 1 so monster goes first
        for req in requested.requests:
            actor = table.player_actor if req.target_seat_id is not None else table.dm_actor
            raw = 1 if req.target_seat_id is not None else 20
            table.initiative.complete_initiative(
                actor,
                FormalRollInput(
                    roll_request_id=req.id,
                    source=FormalRollSource.PHYSICAL,
                    raw_dice=(raw,),
                    idempotency_key=f"dodge-roll-{req.id}",
                ),
            )
        order = table.initiative.suggested_order(table.dm_actor)
        running = table.initiative.finalize_initiative(
            table.dm_actor,
            FinalizeInitiativeInput(ordered_entry_ids=order, idempotency_key="dodge-finalize-init"),
        )
        monster_entry = next(e for e in running.entries if e.monster_instance_id == monster.id)
        char_entry = next(e for e in running.entries if e.character_id == table.character_id)
        assert running.current_turn_entry_id == monster_entry.id

        # Setup attack and core roll services for assertions
        registry = load_default_content_registry()
        characters = CharacterRepository(table.engine, registry)
        attack_repo = CombatAttackRepository(table.engine, table.events.repository)
        adjudication_repo = CombatAdjudicationRepository(table.engine, table.events.repository)
        attacks = CombatAttackService(
            attack_repo,
            adjudication_repo,
            table.combat.repository,
            table.combat,
            AttackDefinitionResolver(characters, table.monsters, registry),
            table.rolls,
            table.events,
        )
        core_rolls = CombatCoreRollService(
            CombatCoreRollRepository(table.engine, table.events.repository),
            table.combat.repository,
            table.combat,
            table.monsters,
            table.rolls,
            table.events,
        )

        # 1. Monster takes Dodge action via use_action
        action_view = table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=monster_entry.id,
                action_kind=CombatActionKind.DODGE,
                economy_cost=CombatEconomyCost.ACTION,
                idempotency_key="goblin-action-dodge",
            ),
        )
        assert action_view.action_kind == "dodge"

        # 2. Detail view shows dodging True for monster entry only
        detail = table.combat.get_active_combat_detail(table.dm_actor)
        m_view = next(e for e in detail.entries if e.id == monster_entry.id)
        c_view = next(e for e in detail.entries if e.id == char_entry.id)
        assert m_view.dodging is True
        assert c_view.dodging is False

        # 3. DM requests DEX save on dodging monster -> advantage source "target:dodging"
        dex_save = core_rolls.request_saving_throws(
            table.dm_actor,
            SavingThrowInput(
                target_entry_ids=(monster_entry.id,),
                ability_ref="dexterity",
                dc=14,
                idempotency_key="save-dex-1",
            ),
        )
        assert dex_save.requests[0].modifier_mode is RollModifierMode.ADVANTAGE
        events = table.events.repository.list_after(
            room_id=table.room_id,
            campaign_id=table.campaign_id,
            session_id=table.session_id,
            after_seq=0,
            scan_limit=500,
        )
        save_event = next(e for e in reversed(events) if e.kind == "combat.saves_requested")
        assert "target:dodging" in save_event.payload["decisions"][str(dex_save.requests[0].id)]["advantage_sources"]

        # 4. DM requests WIS save on dodging monster -> no "target:dodging", NORMAL
        wis_save = core_rolls.request_saving_throws(
            table.dm_actor,
            SavingThrowInput(
                target_entry_ids=(monster_entry.id,),
                ability_ref="wisdom",
                dc=14,
                idempotency_key="save-wis-1",
            ),
        )
        assert wis_save.requests[0].modifier_mode is RollModifierMode.NORMAL
        events2 = table.events.repository.list_after(
            room_id=table.room_id,
            campaign_id=table.campaign_id,
            session_id=table.session_id,
            after_seq=0,
            scan_limit=500,
        )
        wis_event = next(e for e in reversed(events2) if e.kind == "combat.saves_requested")
        assert "target:dodging" not in wis_event.payload["decisions"][str(wis_save.requests[0].id)]["advantage_sources"]

        # 5. Advance turn to character: monster is STILL dodging
        turn_view = table.combat.advance_turn(table.dm_actor, idempotency_key="adv-to-char")
        assert turn_view.current_turn_entry_id == char_entry.id
        m_view_after_adv = next(e for e in turn_view.entries if e.id == monster_entry.id)
        assert m_view_after_adv.dodging is True

        # 6. Player attacks dodging monster -> produces decision with disadvantage and "target:dodging"
        available = attacks.available_attacks(table.player_actor, char_entry.id)
        attack_def = available[0]
        pending_attack = attacks.request_attack(
            table.player_actor,
            AttackRequestInput(
                attacker_entry_id=char_entry.id,
                target_entry_id=monster_entry.id,
                source_ref=attack_def.source_ref,
                idempotency_key="char-attack-dodging-monster",
            ),
        )
        with table.engine.connect() as conn:
            act_row = conn.execute(
                select(combat_actions).where(combat_actions.c.id == pending_attack.action_id)
            ).mappings().one()
        modifier_decision = act_row["payload"]["modifier_decision"]
        assert modifier_decision["mode"] == "disadvantage"
        assert "target:dodging" in modifier_decision["disadvantage_sources"]

        # 7. Advance turn back to monster -> when dodger's OWN turn starts, dodging is False
        turn_view2 = table.combat.advance_turn(table.dm_actor, idempotency_key="adv-to-monster")
        assert turn_view2.current_turn_entry_id == monster_entry.id
        m_view_own_turn = next(e for e in turn_view2.entries if e.id == monster_entry.id)
        assert m_view_own_turn.dodging is False

        # 8. Monster dodges again, then end_combat clears it
        table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=monster_entry.id,
                action_kind=CombatActionKind.DODGE,
                economy_cost=CombatEconomyCost.ACTION,
                idempotency_key="goblin-action-dodge-2",
            ),
        )
        assert next(
            e for e in table.combat.get_active_combat(table.dm_actor).entries if e.id == monster_entry.id
        ).dodging is True

        table.combat.end_combat(table.dm_actor, idempotency_key="end-dodge-combat")
        stored_monster = table.combat.repository.get_entry(monster_entry.id)
        assert stored_monster is not None
        assert stored_monster.dodging is False
    finally:
        table.engine.dispose()


def test_dodge_mcp(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        ai_service,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture
    client = TestClient(app)

    # In mcp_combat_fixture, turn is at character. Advance turn so it's monster's turn.
    adv_res = _mcp_call(client, dm_token, "combat_advance_turn", {"idempotency_key": "mcp-adv-to-mage"})
    assert not adv_res.get("isError")

    # 1. DM combat_use_action(dodge)
    res = _mcp_call(
        client,
        dm_token,
        "combat_use_action",
        {
            "entry_id": str(mage_entry_id),
            "action_kind": "dodge",
            "economy_cost": "action",
            "idempotency_key": "mcp-dodge-1",
        },
    )
    assert not res.get("isError")

    # 2. DM get_combat_context -> the entry has "dodging": true
    dm_ctx = _mcp_call(client, dm_token, "get_combat_context", {})
    dm_combat = dm_ctx["structuredContent"]["data"]["combat"]
    mage_view_dm = next(e for e in dm_combat["entries"] if e["id"] == str(mage_entry_id))
    assert mage_view_dm["dodging"] is True

    # 3. Player get_combat_context also sees it (public table state)
    p_ctx = _mcp_call(client, player_token, "get_combat_context", {})
    p_combat = p_ctx["structuredContent"]["data"]["combat"]
    mage_view_p = next(e for e in p_combat["entries"] if e["id"] == str(mage_entry_id))
    assert mage_view_p["dodging"] is True

    # 4. Player calling combat_use_action for the monster entry is rejected permission_denied with no event written
    initial_events = table.events.repository.list_after(
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        session_id=table.session_id,
        after_seq=0,
        scan_limit=500,
    )

    unauthorized_res = _mcp_call(
        client,
        player_token,
        "combat_use_action",
        {
            "entry_id": str(mage_entry_id),
            "action_kind": "dodge",
            "economy_cost": "action",
            "idempotency_key": "mcp-dodge-unauthorized",
        },
    )
    assert unauthorized_res["isError"] is True
    assert unauthorized_res["structuredContent"]["error"]["code"] == "permission_denied"

    after_events = table.events.repository.list_after(
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        session_id=table.session_id,
        after_seq=0,
        scan_limit=500,
    )
    assert len(after_events) == len(initial_events)
