from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import insert, update

from app.api.dependencies import get_content_registry, get_database_engine
from app.api.rooms.access import get_room_service
from app.api.rooms.ai_controllers import get_ai_controller_service
from app.api.rooms.dependencies import (
    get_combat_initiative_service,
    get_combat_service,
    get_monster_instance_service,
    get_table_event_service,
)
from app.content import load_default_content_registry
from app.content.registry import ContentRegistry
from app.domain.combat.ai_tools import CombatAIToolApplicationService
from app.domain.combat.initiative import (
    FinalizeInitiativeInput,
    RequestInitiativeInput,
)
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    CombatService,
    CombatStateConflictError,
    MonsterOutcomeInput,
    StartCombatInput,
)
from app.domain.combat.monster_instances import MonsterInstanceService
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import (
    AIControllerService,
)
from app.domain.rooms.service import RoomService
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
)
from app.main import app
from app.mcp.dependencies import get_ai_tool_application_service
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.persistence.combat.tables import (
    combat_entries,
    monster_instances,
)
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    sessions,
)
from tests.test_p4b_combat_lifecycle import (
    CombatTable,
    _complete_request,
    _quick_enemy,
    _setup,
)


def _start_combat_with_enemy(
    name: str = "Goblin A",
    *,
    monster_initiative_raw: int = 10,
    character_initiative_raw: int = 15,
) -> tuple[CombatTable, Any, Any, Any, Any]:
    table = _setup()
    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key="start"),
    )
    enemy = _quick_enemy(table, name)
    table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(monster_instance_id=enemy.id, idempotency_key=f"add-{name}"),
    )
    requests = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="init"),
    )
    for req in requests.requests:
        raw = character_initiative_raw if req.target_seat_id is not None else monster_initiative_raw
        _complete_request(table, req, raw, f"init-{req.id}")

    active_combat = table.combat.repository.get_active(table.campaign_id)
    assert active_combat is not None
    entries = table.combat.repository.list_entries(active_combat.id)
    char_entry = next(e for e in entries if e.subject_kind == "character")
    monster_entry = next(e for e in entries if e.subject_kind == "monster")

    running = table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=(char_entry.id, monster_entry.id),
            idempotency_key="finalize",
        ),
    )
    return table, enemy, monster_entry, char_entry, running


def test_outcome_values_entry_and_instance_status_and_event_payload() -> None:
    # 1. Test each standard outcome: dead, unconscious, surrendered, fled
    for outcome in ("dead", "unconscious", "surrendered", "fled"):
        table, enemy, monster_entry, char_entry, running = _start_combat_with_enemy(f"Goblin-{outcome}")
        res = table.combat.set_monster_outcome(
            table.dm_actor,
            MonsterOutcomeInput(entry_id=monster_entry.id, outcome=outcome),
        )
        # Entry in returned CombatView
        entry_view = next(e for e in res.entries if e.id == monster_entry.id)
        assert entry_view.status == outcome

        # Direct repository checks
        persisted_entry = table.combat.repository.get_entry(monster_entry.id)
        assert persisted_entry is not None
        assert persisted_entry.status == outcome

        persisted_instance = table.monsters.get_instance(enemy.id)
        assert persisted_instance is not None
        assert persisted_instance.combat_status == outcome

        # Event payload
        events = table.events.repository.list_after(
            room_id=table.room_id,
            campaign_id=table.campaign_id,
            session_id=table.session_id,
            after_seq=0,
            scan_limit=50,
        )
        outcome_events = [e for e in events if e.kind == "combat.monster_outcome_set"]
        assert len(outcome_events) == 1
        payload = outcome_events[0].payload
        assert payload == {
            "combat_id": str(running.id),
            "entry_id": str(monster_entry.id),
            "monster_instance_id": str(enemy.id),
            "outcome": outcome,
            "status": outcome,
            "note": None,
        }

        # Player projection check: public outcome exposed to Player
        detail = table.combat.get_active_combat_detail(table.player_actor)
        assert detail is not None
        combatant = next(c for c in detail.combatants if c.entry_id == monster_entry.id)
        assert combatant.projection["combat_status"] == outcome
        if outcome in ("dead", "unconscious"):
            assert combatant.projection["injury_level"] == "down"
        else:
            # Full HP monster remains healthy
            assert combatant.projection["injury_level"] == "healthy"

    # 2. Test 'other' outcome without note is rejected before any write
    table, enemy, monster_entry, char_entry, running = _start_combat_with_enemy("Goblin-other-fail")
    with pytest.raises(ValidationError):
        MonsterOutcomeInput(entry_id=monster_entry.id, outcome="other")
    with pytest.raises(ValidationError):
        MonsterOutcomeInput(entry_id=monster_entry.id, outcome="other", note="   ")

    persisted_entry = table.combat.repository.get_entry(monster_entry.id)
    assert persisted_entry is not None and persisted_entry.status == "active"
    persisted_instance = table.monsters.get_instance(enemy.id)
    assert persisted_instance is not None and persisted_instance.combat_status == "active"

    # 3. Test 'other' outcome with note -> status 'removed'
    table, enemy, monster_entry, char_entry, running = _start_combat_with_enemy("Goblin-other-ok")
    note_text = "Turned to stone by basilisk gaze"
    res = table.combat.set_monster_outcome(
        table.dm_actor,
        MonsterOutcomeInput(entry_id=monster_entry.id, outcome="other", note=note_text),
    )
    entry_view = next(e for e in res.entries if e.id == monster_entry.id)
    assert entry_view.status == "removed"

    persisted_entry = table.combat.repository.get_entry(monster_entry.id)
    assert persisted_entry is not None and persisted_entry.status == "removed"
    persisted_instance = table.monsters.get_instance(enemy.id)
    assert persisted_instance is not None and persisted_instance.combat_status == "removed"

    events = table.events.repository.list_after(
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        session_id=table.session_id,
        after_seq=0,
        scan_limit=50,
    )
    outcome_events = [e for e in events if e.kind == "combat.monster_outcome_set"]
    assert len(outcome_events) == 1
    assert outcome_events[0].payload == {
        "combat_id": str(running.id),
        "entry_id": str(monster_entry.id),
        "monster_instance_id": str(enemy.id),
        "outcome": "other",
        "status": "removed",
        "note": note_text,
    }


def test_player_actor_unauthorized_zero_rows_changed() -> None:
    table, enemy, monster_entry, char_entry, running = _start_combat_with_enemy("Goblin-unauth")
    with pytest.raises(TableEventActorUnauthorizedError):
        table.combat.set_monster_outcome(
            table.player_actor,
            MonsterOutcomeInput(entry_id=monster_entry.id, outcome="dead"),
        )

    # Zero rows changed
    entry = table.combat.repository.get_entry(monster_entry.id)
    assert entry is not None and entry.status == "active"
    instance = table.monsters.get_instance(enemy.id)
    assert instance is not None and instance.combat_status == "active"

    # No outcome event
    events = table.events.repository.list_after(
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        session_id=table.session_id,
        after_seq=0,
        scan_limit=50,
    )
    assert not any(e.kind == "combat.monster_outcome_set" for e in events)


def test_current_turn_monster_conflict_until_turn_advanced() -> None:
    table = _setup()
    table.combat.start_quick_combat(table.dm_actor, StartCombatInput(idempotency_key="start"))
    enemy = _quick_enemy(table, "Boss")
    table.combat.add_monster(table.dm_actor, AddMonsterInput(monster_instance_id=enemy.id, idempotency_key="add-boss"))
    requests = table.initiative.request_initiative(table.dm_actor, RequestInitiativeInput(idempotency_key="init"))
    for req in requests.requests:
        raw = 5 if req.target_seat_id is not None else 20
        _complete_request(table, req, raw, f"init-{req.id}")

    active_combat = table.combat.repository.get_active(table.campaign_id)
    assert active_combat is not None
    entries = table.combat.repository.list_entries(active_combat.id)
    char_entry = next(e for e in entries if e.subject_kind == "character")
    monster_entry = next(e for e in entries if e.subject_kind == "monster")

    # Put monster first on turn
    running = table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=(monster_entry.id, char_entry.id),
            idempotency_key="finalize",
        ),
    )
    assert running.current_turn_entry_id == monster_entry.id

    # Setting outcome on current turn monster must raise CombatStateConflictError
    with pytest.raises(CombatStateConflictError, match="advance the turn"):
        table.combat.set_monster_outcome(
            table.dm_actor,
            MonsterOutcomeInput(entry_id=monster_entry.id, outcome="dead"),
        )

    # Advance turn to character
    table.combat.advance_turn(table.dm_actor)
    active = table.combat.repository.get_active(table.campaign_id)
    assert active is not None and active.current_turn_entry_id == char_entry.id

    # Now setting outcome succeeds
    res = table.combat.set_monster_outcome(
        table.dm_actor,
        MonsterOutcomeInput(entry_id=monster_entry.id, outcome="dead"),
    )
    entry_view = next(e for e in res.entries if e.id == monster_entry.id)
    assert entry_view.status == "dead"


def test_idempotency_and_character_entry_rejected() -> None:
    table, enemy, monster_entry, char_entry, running = _start_combat_with_enemy("Goblin-idem")

    # Call with idempotency key
    res1 = table.combat.set_monster_outcome(
        table.dm_actor,
        MonsterOutcomeInput(entry_id=monster_entry.id, outcome="dead", idempotency_key="key-outcome-1"),
    )
    res2 = table.combat.set_monster_outcome(
        table.dm_actor,
        MonsterOutcomeInput(entry_id=monster_entry.id, outcome="dead", idempotency_key="key-outcome-1"),
    )
    assert res1.entries == res2.entries

    events = table.events.repository.list_after(
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        session_id=table.session_id,
        after_seq=0,
        scan_limit=50,
    )
    outcome_events = [e for e in events if e.kind == "combat.monster_outcome_set"]
    assert len(outcome_events) == 1

    # Character entry cannot take an outcome
    with pytest.raises(CombatStateConflictError, match="only Monster entries"):
        table.combat.set_monster_outcome(
            table.dm_actor,
            MonsterOutcomeInput(entry_id=char_entry.id, outcome="dead"),
        )


def test_end_combat_preserves_monster_outcome() -> None:
    table, enemy, monster_entry, char_entry, running = _start_combat_with_enemy("Goblin-surrender")

    table.combat.set_monster_outcome(
        table.dm_actor,
        MonsterOutcomeInput(entry_id=monster_entry.id, outcome="surrendered"),
    )

    ended = table.combat.end_combat(table.dm_actor)
    assert ended.status == "ended"

    persisted_entry = table.combat.repository.get_entry(monster_entry.id)
    assert persisted_entry is not None
    assert persisted_entry.status == "surrendered"

    persisted_instance = table.monsters.get_instance(enemy.id)
    assert persisted_instance is not None
    assert persisted_instance.combat_status == "surrendered"


def test_rest_and_mcp_parity_through_testclient() -> None:
    table, enemy, monster_entry, char_entry, running = _start_combat_with_enemy("Goblin-rest-mcp")

    # Add a second monster for MCP test
    second_enemy = _quick_enemy(table, "Goblin-second")
    table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(monster_instance_id=second_enemy.id, idempotency_key="add-second"),
    )
    entries = table.combat.repository.list_entries(running.id)
    second_monster_entry = next(e for e in entries if e.monster_instance_id == second_enemy.id)

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
        combat_special_attack_service=object(),
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
    app.dependency_overrides[get_ai_controller_service] = lambda: ai_controller_service
    app.dependency_overrides[get_ai_tool_application_service] = lambda: combat_ai_tool_service

    client = TestClient(app)
    try:
        # 1. REST DM POST outcome 200
        rest_url = (
            f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
            f"/sessions/{table.session_id}/combat/entries/{monster_entry.id}/outcome"
        )
        dm_resp = client.post(
            rest_url,
            json={"outcome": "dead"},
            headers={"Authorization": f"Bearer {table.dm_token}"},
        )
        assert dm_resp.status_code == 200, dm_resp.text
        data = dm_resp.json()
        entry_row = next(e for e in data["entries"] if e["id"] == str(monster_entry.id))
        assert entry_row["status"] == "dead"

        # 2. REST Player POST outcome 403
        player_resp = client.post(
            rest_url,
            json={"outcome": "unconscious"},
            headers={"Authorization": f"Bearer {table.player_token}"},
        )
        assert player_resp.status_code == 403
        assert player_resp.json()["error"]["code"] == "table_actor_unauthorized"

        # 3. Mint AI DM grant and test MCP combat_set_monster_outcome
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

        mcp_resp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "combat_set_monster_outcome",
                    "arguments": {
                        "entry_id": str(second_monster_entry.id),
                        "outcome": "surrendered",
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
                "Mcp-Name": "combat_set_monster_outcome",
            },
        )
        assert mcp_resp.status_code == 200, mcp_resp.text
        mcp_result = mcp_resp.json()["result"]
        assert not mcp_result.get("isError")
        # Check that second monster is now surrendered
        second_entry = table.combat.repository.get_entry(second_monster_entry.id)
        assert second_entry is not None and second_entry.status == "surrendered"
        second_inst = table.monsters.get_instance(second_enemy.id)
        assert second_inst is not None and second_inst.combat_status == "surrendered"

    finally:
        app.dependency_overrides.clear()
