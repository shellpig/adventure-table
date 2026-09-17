from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, insert, select, update

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
from app.domain.combat.ai_tools import (
    CombatAIToolApplicationService,
    CombatEntryMutationToolInput,
    CombatMutationToolInput,
    CombatRollToolInput,
)
from app.domain.combat.monster_instances import MonsterInstanceService
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import (
    AIControllerAuthView,
    AIControllerService,
    AIHandoffRequest,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionStatus
from app.main import app
from app.mcp.dependencies import get_ai_tool_application_service
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.mcp.tools import call_tool, tool_catalog
from app.persistence.combat.tables import combat_actions, combat_entries, combats
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    sessions,
)
import tests.test_p4b_combat_lifecycle as support


def _auth(role: str, active: bool = True) -> AIControllerAuthView:
    return AIControllerAuthView(
        grant_id=uuid4(),
        room_id=uuid4(),
        campaign_id=uuid4(),
        seat_id=uuid4(),
        role=role,
        session_id=uuid4() if active else None,
        generation=1,
        is_current_dm=role == "dm" and active,
        temporary_instruction=None,
    )


def _body(method: str, *, params: dict | None = None, request_id: int | str = 1) -> dict:
    merged = dict(params or {})
    merged["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "p4e-test", "version": "1"},
    }
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": merged}


def _headers(method: str, *, name: str | None = None, token: str = "fake-token") -> dict[str, str]:
    result = {
        "Authorization": f"Bearer {token}",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        result["Mcp-Name"] = name
    return result


def _mcp_call(client: TestClient, token: str, name: str, arguments: dict) -> dict:
    resp = client.post(
        "/mcp",
        json=_body("tools/call", params={"name": name, "arguments": arguments}),
        headers=_headers("tools/call", name=name, token=token),
    )
    assert resp.status_code == 200
    return resp.json()["result"]


class _DispatchSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def combat_start(self, *args, **kwargs):
        self.calls.append("combat_start")

    def combat_create_quick_enemy(self, *args, **kwargs):
        self.calls.append("combat_create_quick_enemy")

    def combat_end(self, *args, **kwargs):
        self.calls.append("combat_end")


def test_mcp_combat_lifecycle_catalogs() -> None:
    dm_tools = {item["name"] for item in tool_catalog(_auth("dm", True))}
    player_tools = {item["name"] for item in tool_catalog(_auth("player", True))}
    pre_session_dm_tools = {item["name"] for item in tool_catalog(_auth("dm", False))}

    dm_only_lifecycle = {
        "combat_start",
        "combat_add_character",
        "combat_add_monster",
        "combat_create_monster",
        "combat_create_quick_enemy",
        "combat_list_monster_instances",
        "combat_request_initiative",
        "combat_finalize_initiative",
        "combat_advance_turn",
        "combat_end",
        "combat_remove_entry",
        "combat_withdraw_entry",
    }
    shared_lifecycle = {
        "combat_roll_initiative",
        "combat_use_action",
    }

    assert dm_only_lifecycle <= dm_tools
    assert shared_lifecycle <= dm_tools
    assert shared_lifecycle <= player_tools
    assert not (dm_only_lifecycle & player_tools)
    assert pre_session_dm_tools == dm_tools


def test_wire_ai_dm_combat_lifecycle_journey() -> None:
    table = support._setup()
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
        stage_service=object(),  # unused in combat lifecycle
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
        # Mint active AI DM grant
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

        ai_token = minted.plaintext

        # 1. combat_create_quick_enemy
        res_enemy = _mcp_call(
            client,
            ai_token,
            "combat_create_quick_enemy",
            {"name": "Goblin Scout", "armor_class": 13, "max_hp": 7, "idempotency_key": "enemy-1"},
        )
        assert res_enemy["isError"] is False
        enemy_data = res_enemy["structuredContent"]["data"]
        assert enemy_data["name"] == "Goblin Scout"
        monster_instance_id = enemy_data["id"]

        # 2. combat_start
        res_start = _mcp_call(
            client,
            ai_token,
            "combat_start",
            {"include_active_party": True, "idempotency_key": "start-1"},
        )
        assert res_start["isError"] is False
        start_data = res_start["structuredContent"]["data"]
        combat_id = start_data["id"]
        assert start_data["status"] == "initiative_pending"
        assert len(start_data["entries"]) == 1  # Party character

        # 3. combat_add_monster
        res_add = _mcp_call(
            client,
            ai_token,
            "combat_add_monster",
            {"monster_instance_id": monster_instance_id, "idempotency_key": "add-gob"},
        )
        assert res_add["isError"] is False
        add_data = res_add["structuredContent"]["data"]
        assert len(add_data["entries"]) == 2

        # 4. combat_request_initiative
        res_req_init = _mcp_call(
            client,
            ai_token,
            "combat_request_initiative",
            {"idempotency_key": "req-init-1"},
        )
        assert res_req_init["isError"] is False
        req_data = res_req_init["structuredContent"]["data"]
        requests = req_data["requests"]
        assert len(requests) == 2

        # 5. combat_roll_initiative
        for req in requests:
            res_roll = _mcp_call(
                client,
                ai_token,
                "combat_roll_initiative",
                {"roll_request_id": req["id"], "idempotency_key": f"roll-{req['id']}"},
            )
            assert res_roll["isError"] is False
            assert "total" in res_roll["structuredContent"]["data"]

        # 6. combat_finalize_initiative
        active_entries = [
            e for e in table.combat.repository.list_entries(UUID(combat_id)) if e.status == "active"
        ]
        ordered = sorted(active_entries, key=lambda e: (-int(e.initiative_total or 0), str(e.id)))
        ordered_ids = [str(e.id) for e in ordered]

        res_final = _mcp_call(
            client,
            ai_token,
            "combat_finalize_initiative",
            {"ordered_entry_ids": ordered_ids, "idempotency_key": "final-1"},
        )
        assert res_final["isError"] is False
        final_data = res_final["structuredContent"]["data"]
        assert final_data["status"] == "running"
        assert final_data["round_number"] == 1

        # REST GET verification: same CombatService state visible via REST endpoint (viewed by table player)
        rest_resp = client.get(
            f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}/sessions/{table.session_id}/combat",
            headers={"Authorization": f"Bearer {table.player_token}"},
        )
        assert rest_resp.status_code == 200
        rest_combat = rest_resp.json()
        assert rest_combat["id"] == combat_id
        assert rest_combat["status"] == "running"
        assert rest_combat["round_number"] == 1
        assert len(rest_combat["entries"]) == 2

        # 7. combat_advance_turn
        res_adv = _mcp_call(
            client,
            ai_token,
            "combat_advance_turn",
            {"idempotency_key": "adv-1"},
        )
        assert res_adv["isError"] is False
        adv_data = res_adv["structuredContent"]["data"]
        assert adv_data["status"] == "running"

        # 8. combat_end
        res_end = _mcp_call(
            client,
            ai_token,
            "combat_end",
            {"idempotency_key": "end-1"},
        )
        assert res_end["isError"] is False
        end_data = res_end["structuredContent"]["data"]
        assert end_data["status"] == "ended"

        # REST GET verification after combat end: returns None
        rest_resp_after = client.get(
            f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}/sessions/{table.session_id}/combat",
            headers={"Authorization": f"Bearer {table.player_token}"},
        )
        assert rest_resp_after.status_code == 200
        assert rest_resp_after.json() is None
    finally:
        app.dependency_overrides.clear()
        app.state.ai_tool_application_service = None
        table.engine.dispose()


def test_ai_player_role_permission_and_unowned_action_rejection() -> None:
    # 1. Spy test: Player calling DM-only tools gets permission_denied WITHOUT facade dispatch
    spy = _DispatchSpy()
    player_auth = _auth("player", active=True)
    for tool_name in ("combat_start", "combat_create_quick_enemy", "combat_end"):
        res = asyncio.run(
            call_tool(
                spy,  # type: ignore[arg-type]
                token="player-token",
                auth=player_auth,
                name=tool_name,
                arguments={"idempotency_key": "k"},
            )
        )
        assert res["isError"] is True
        assert res["structuredContent"]["error"]["code"] == "permission_denied"
    assert spy.calls == []

    # 2. Shared service rejection: combat_use_action on unowned entry rejected
    table = support._setup()
    registry = load_default_content_registry()
    grant_repo = AIControllerGrantRepository(table.engine)
    ai_controller_service = AIControllerService(grant_repo, table.events)
    monster_service = MonsterInstanceService(table.monsters, registry, table.events)

    # Start combat with monster
    table.combat.start_quick_combat(
        table.dm_actor,
        support.StartCombatInput(include_active_party=True, idempotency_key="start-p"),
    )
    monster = table.monsters.create_quick_enemy(
        campaign_id=table.campaign_id,
        name="Orc",
        armor_class=13,
        max_hp=15,
        speed={"walk": "30 ft."},
        attack=None,
    )
    add_view = table.combat.add_monster(
        table.dm_actor,
        support.AddMonsterInput(monster_instance_id=monster.id, idempotency_key="add-orc"),
    )
    monster_entry = next(e for e in add_view.entries if e.monster_instance_id == monster.id)

    # Player hands off to AI
    player_grant = ai_controller_service.let_ai_control_player(
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        session_id=table.session_id,
        seat_id=table.player_seat_id,
        context=RoomAccessContext(
            room_id=table.room_id,
            access_session_id=table.player_actor.access_session_id,
            authority=RoomAccessAuthority.MEMBER,
        ),
        request=AIHandoffRequest(),
    )

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
    app.dependency_overrides[get_ai_controller_service] = lambda: ai_controller_service
    app.dependency_overrides[get_ai_tool_application_service] = lambda: combat_ai_tool_service

    client = TestClient(app)
    try:
        # Player attempts to use action on Monster entry (unowned)
        res_action = _mcp_call(
            client,
            player_grant.token,
            "combat_use_action",
            {
                "entry_id": str(monster_entry.id),
                "action_kind": "dodge",
                "economy_cost": "action",
                "idempotency_key": "player-action-on-monster",
            },
        )
        assert res_action["isError"] is True
        assert res_action["structuredContent"]["error"]["code"] == "permission_denied"

        # Verify no combat_actions row created
        with table.engine.connect() as conn:
            action_count = conn.scalar(select(func.count()).select_from(combat_actions))
            assert action_count == 0
    finally:
        app.dependency_overrides.clear()
        app.state.ai_tool_application_service = None
        table.engine.dispose()


def test_take_back_and_session_end_invalidate_combat_mcp_tokens() -> None:
    table = support._setup()
    registry = load_default_content_registry()
    grant_repo = AIControllerGrantRepository(table.engine)
    ai_controller_service = AIControllerService(grant_repo, table.events)
    monster_service = MonsterInstanceService(table.monsters, registry, table.events)

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
    app.dependency_overrides[get_ai_controller_service] = lambda: ai_controller_service
    app.dependency_overrides[get_ai_tool_application_service] = lambda: combat_ai_tool_service

    client = TestClient(app)
    try:
        # 1. Player handoff -> Take Back -> old token rejected on combat_use_action
        player_grant = ai_controller_service.let_ai_control_player(
            room_id=table.room_id,
            campaign_id=table.campaign_id,
            session_id=table.session_id,
            seat_id=table.player_seat_id,
            context=RoomAccessContext(
                room_id=table.room_id,
                access_session_id=table.player_actor.access_session_id,
                authority=RoomAccessAuthority.MEMBER,
            ),
            request=AIHandoffRequest(),
        )

        # Human takes back
        ai_controller_service.take_back_player(
            room_id=table.room_id,
            campaign_id=table.campaign_id,
            session_id=table.session_id,
            seat_id=table.player_seat_id,
            context=RoomAccessContext(
                room_id=table.room_id,
                access_session_id=table.player_actor.access_session_id,
                authority=RoomAccessAuthority.MEMBER,
            ),
        )

        resp = client.post(
            "/mcp",
            json=_body(
                "tools/call",
                params={
                    "name": "combat_use_action",
                    "arguments": {
                        "entry_id": str(uuid4()),
                        "action_kind": "dodge",
                    },
                },
            ),
            headers=_headers("tools/call", name="combat_use_action", token=player_grant.token),
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == -32001
        assert resp.json()["error"]["data"]["code"] == "ai_token_unauthorized"

        # 2. AI DM grant -> End Session -> old token rejected on combat_advance_turn
        dm_seat_id = table.dm_actor.seat_id
        minted_dm = mint_ai_controller_token()
        now = datetime.now(timezone.utc)
        with table.engine.begin() as conn:
            conn.execute(
                insert(ai_controller_grants).values(
                    id=minted_dm.grant_id,
                    room_id=table.room_id,
                    campaign_id=table.campaign_id,
                    seat_id=dm_seat_id,
                    role="dm",
                    session_id=table.session_id,
                    secret_hash=minted_dm.secret_hash,
                    secret_prefix=minted_dm.display_hint,
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
            conn.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == dm_seat_id)
                .values(
                    controller_kind="ai",
                    ai_controller_grant_id=minted_dm.grant_id,
                    controller_epoch=1,
                    controller_access_session_id=None,
                    updated_at=now,
                )
            )
            conn.execute(
                update(sessions)
                .where(sessions.c.id == table.session_id)
                .values(
                    dm_controller_kind="ai",
                    dm_controller_ai_grant_id=minted_dm.grant_id,
                    dm_controller_generation=1,
                    dm_controller_access_session_id=None,
                )
            )

        # End session
        with table.engine.begin() as conn:
            table.session_service.repository.finalize_in_transaction(
                conn,
                session_id=table.session_id,
                status="ended",
                now=now,
            )

        resp_dm = client.post(
            "/mcp",
            json=_body(
                "tools/call",
                params={"name": "combat_advance_turn", "arguments": {}},
            ),
            headers=_headers("tools/call", name="combat_advance_turn", token=minted_dm.plaintext),
        )
        assert resp_dm.status_code == 401
        assert resp_dm.json()["error"]["code"] == -32001
        assert resp_dm.json()["error"]["data"]["code"] == "ai_token_unauthorized"
    finally:
        app.dependency_overrides.clear()
        app.state.ai_tool_application_service = None
        table.engine.dispose()


def test_dm_creates_monster_from_content_and_lists_instances() -> None:
    table = support._setup()
    registry = load_default_content_registry()
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
    app.dependency_overrides[get_ai_controller_service] = lambda: ai_controller_service
    app.dependency_overrides[get_ai_tool_application_service] = lambda: combat_ai_tool_service

    client = TestClient(app)
    try:
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

        ai_token = minted.plaintext

        # Create from content
        res = _mcp_call(
            client,
            ai_token,
            "combat_create_monster",
            {"content_key": "srd5.1:monster:mage", "idempotency_key": "mage-1"},
        )
        assert res["isError"] is False
        mage_data = res["structuredContent"]["data"]
        assert mage_data["template_key"] == "srd5.1:monster:mage"
        assert mage_data["name"] == "Mage"
        assert mage_data["resources"]["spell_slot:1"] == 4

        # List monster instances
        res_list = _mcp_call(
            client,
            ai_token,
            "combat_list_monster_instances",
            {},
        )
        assert res_list["isError"] is False
        instances = res_list["structuredContent"]["data"]["instances"]
        assert len(instances) == 1
        assert instances[0]["template_key"] == "srd5.1:monster:mage"
    finally:
        app.dependency_overrides.clear()
        app.state.ai_tool_application_service = None
        table.engine.dispose()
