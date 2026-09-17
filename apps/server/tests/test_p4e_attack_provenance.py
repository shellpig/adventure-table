from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.api.dependencies import (
    get_content_registry,
    get_database_engine,
)
from app.api.rooms.access import get_room_service
from app.api.rooms.ai_controllers import get_ai_controller_service
from app.api.rooms.dependencies import (
    get_combat_adjudication_service,
    get_combat_attack_service,
    get_combat_service,
    get_table_event_service,
)
from app.content.p4a_combat_templates import monster_to_reusable_rules
from app.content.p4a_monsters import MonsterData
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.attacks import (
    AttackAdjudicationInput,
    AttackRequestInput,
    CombatAttackService,
)
from app.domain.combat.adjudication_service import CombatAdjudicationService
from app.domain.combat.ai_tools import CombatAIToolApplicationService
from app.domain.combat.event_projection import project_combat_event_payload
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.combat.monster_instances import MonsterInstanceService, initial_monster_resources
from app.domain.rooms.ai_controllers import AIControllerService, AIHandoffRequest
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.service import RoomService
from app.main import app
from app.mcp.dependencies import get_ai_tool_application_service
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.persistence.combat.adjudication import CombatAdjudicationRepository
from app.persistence.combat.attacks import CombatAttackRepository
from app.persistence.combat.tables import combat_entries
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.repository import RoomRepository
import tests.test_p4b_combat_lifecycle as support


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


@pytest.fixture
def combat_provenance_fixture():
    table = support._setup()
    registry = table.combat.registry
    room_service = RoomService(RoomRepository(table.engine))

    attack_repo = CombatAttackRepository(table.engine, table.events.repository)
    adjudication_repo = CombatAdjudicationRepository(table.engine, table.events.repository)
    definition_resolver = AttackDefinitionResolver(
        table.combat.character_repository,
        table.monsters,
        registry,
    )
    attack_service = CombatAttackService(
        repository=attack_repo,
        adjudication_repository=adjudication_repo,
        combat_repository=table.combat.repository,
        combat_service=table.combat,
        definition_resolver=definition_resolver,
        roll_service=table.rolls,
        table_event_service=table.events,
    )
    adjudication_service = CombatAdjudicationService(
        repository=adjudication_repo,
        combat_repository=table.combat.repository,
        combat_service=table.combat,
        table_event_service=table.events,
    )
    table.attacks = attack_service
    table.adjudication = adjudication_service

    # Start combat
    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key="prov-test-start"),
    )

    # 1. Character entry
    with table.engine.connect() as conn:
        char_entry_row = conn.execute(
            select(combat_entries).where(
                combat_entries.c.character_id == table.character_id,
                combat_entries.c.status == "active",
            )
        ).mappings().one()
    char_entry_id = UUID(str(char_entry_row["id"]))

    # 2. SRD Monster from template (Goblin)
    goblin_entry = registry.get("srd5.1:monster:goblin")
    rules = monster_to_reusable_rules(MonsterData.model_validate(goblin_entry.data))
    resources = initial_monster_resources(rules)
    goblin = table.monsters.create_instance(
        campaign_id=table.campaign_id,
        name=goblin_entry.name,
        rules_snapshot=rules,
        template_key="srd5.1:monster:goblin",
        resources=resources,
    )
    goblin_added = table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=goblin.id,
            idempotency_key="prov-add-goblin",
        ),
    )
    goblin_entry_id = next(entry.id for entry in goblin_added.entries if entry.monster_instance_id == goblin.id)

    # 3. Quick Enemy with custom attack
    quick_enemy = table.monsters.create_quick_enemy(
        campaign_id=table.campaign_id,
        name="Custom Bandit",
        armor_class=12,
        max_hp=10,
        speed={"walk": "30 ft."},
        attack={
            "name": "Rusty Cleaver",
            "attack_kind": "melee_weapon",
            "attack_bonus": 3,
            "damage_parts": [{"dice": "1d6+1", "damage_type": "slashing"}],
        },
    )
    quick_added = table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=quick_enemy.id,
            idempotency_key="prov-add-quick",
        ),
    )
    quick_entry_id = next(entry.id for entry in quick_added.entries if entry.monster_instance_id == quick_enemy.id)

    # 4. Customized Monster from template (Goblin with renamed action to verify custom name preservation)
    custom_rules = deepcopy(rules)
    custom_rules["actions"][0]["name"] = "Flaming Scimitar"
    custom_goblin = table.monsters.create_instance(
        campaign_id=table.campaign_id,
        name="Custom Goblin",
        rules_snapshot=custom_rules,
        template_key="srd5.1:monster:goblin",
        resources=resources,
    )
    custom_added = table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=custom_goblin.id,
            idempotency_key="prov-add-custom-goblin",
        ),
    )
    custom_goblin_entry_id = next(entry.id for entry in custom_added.entries if entry.monster_instance_id == custom_goblin.id)

    # Request, roll, and finalize initiative so combat is 'running' with character on turn
    requested = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="prov-req-init"),
    )
    for req in requested.requests:
        actor = table.player_actor if req.target_seat_id is not None else table.dm_actor
        raw = 20 if req.target_seat_id is not None else 1
        table.initiative.complete_initiative(
            actor,
            FormalRollInput(
                roll_request_id=req.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(raw,),
                idempotency_key=f"prov-init-roll-{req.id}",
            ),
        )
    order = table.initiative.suggested_order(table.dm_actor)
    table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=order,
            idempotency_key="prov-finalize-init",
        ),
    )

    # 5. Genuine scoped AI grant infrastructure for MCP parity test
    grant_repo = AIControllerGrantRepository(table.engine)
    ai_controller_service = AIControllerService(grant_repo, table.events)
    monster_service = MonsterInstanceService(
        monster_repository=table.monsters,
        content_registry=registry,
        table_event_service=table.events,
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
        combat_attack_service=attack_service,
        combat_resolution_service=object(),
        combat_core_roll_service=object(),
        combat_special_attack_service=object(),
        combat_initiative_service=table.initiative,
        monster_instance_service=monster_service,
        combat_spell_service=object(),
        combat_concentration_service=object(),
        combat_reaction_service=object(),
        combat_adjudication_service=adjudication_service,
    )

    app.state.ai_tool_application_service = combat_ai_tool_service
    app.dependency_overrides[get_database_engine] = lambda: table.engine
    app.dependency_overrides[get_content_registry] = lambda: registry
    app.dependency_overrides[get_table_event_service] = lambda: table.events
    app.dependency_overrides[get_room_service] = lambda: room_service
    app.dependency_overrides[get_combat_service] = lambda: table.combat
    app.dependency_overrides[get_combat_attack_service] = lambda: attack_service
    app.dependency_overrides[get_combat_adjudication_service] = lambda: adjudication_service
    app.dependency_overrides[get_ai_controller_service] = lambda: ai_controller_service
    app.dependency_overrides[get_ai_tool_application_service] = lambda: combat_ai_tool_service

    try:
        yield (
            table,
            char_entry_id,
            goblin_entry_id,
            quick_entry_id,
            custom_goblin_entry_id,
            ai_controller_service,
        )
    finally:
        app.dependency_overrides.clear()
        app.state.ai_tool_application_service = None


def test_available_attacks_provenance_and_custom_names(combat_provenance_fixture) -> None:
    table, char_entry_id, goblin_entry_id, quick_entry_id, custom_goblin_entry_id, _ = combat_provenance_fixture
    attack_service = table.attacks

    # 1. Character weapon attacks carry content_ref (inventory.item_ref) and presentation_field ("name")
    char_attacks = attack_service.available_attacks(table.player_actor, char_entry_id)
    assert len(char_attacks) > 0
    char_atk = char_attacks[0]
    assert char_atk.source_ref.startswith("inventory:")
    assert char_atk.content_ref is not None
    assert char_atk.content_ref.startswith("srd5.1:equipment:")
    assert char_atk.presentation_field == "name"

    # 2. SRD Monster attacks carry template_key content_ref and presentation_field ("data.actions.<idx>.name")
    goblin_attacks = attack_service.available_attacks(table.dm_actor, goblin_entry_id)
    assert len(goblin_attacks) >= 2
    scimitar = goblin_attacks[0]
    assert scimitar.source_ref == "monster-action:0"
    assert scimitar.name == "Scimitar"
    assert scimitar.content_ref == "srd5.1:monster:goblin"
    assert scimitar.presentation_field == "data.actions.0.name"

    shortbow = goblin_attacks[1]
    assert shortbow.source_ref == "monster-action:1"
    assert shortbow.name == "Shortbow"
    assert shortbow.content_ref == "srd5.1:monster:goblin"
    assert shortbow.presentation_field == "data.actions.1.name"

    # 3. Quick Enemy attacks have content_ref=None, presentation_field=None, and preserve custom name as entered
    quick_attacks = attack_service.available_attacks(table.dm_actor, quick_entry_id)
    assert len(quick_attacks) == 1
    cleaver = quick_attacks[0]
    assert cleaver.source_ref == "monster-action:0"
    assert cleaver.name == "Rusty Cleaver"
    assert cleaver.content_ref is None
    assert cleaver.presentation_field is None

    # 4. Customized Monster attacks: customized action has content_ref=None, uncustomized action retains canonical ref
    custom_attacks = attack_service.available_attacks(table.dm_actor, custom_goblin_entry_id)
    assert len(custom_attacks) >= 2
    flaming = custom_attacks[0]
    assert flaming.source_ref == "monster-action:0"
    assert flaming.name == "Flaming Scimitar"
    assert flaming.content_ref is None
    assert flaming.presentation_field is None

    custom_shortbow = custom_attacks[1]
    assert custom_shortbow.source_ref == "monster-action:1"
    assert custom_shortbow.name == "Shortbow"
    assert custom_shortbow.content_ref == "srd5.1:monster:goblin"
    assert custom_shortbow.presentation_field == "data.actions.1.name"


def test_http_and_mcp_parity_for_attack_definitions(combat_provenance_fixture) -> None:
    table, char_entry_id, goblin_entry_id, quick_entry_id, _, ai_controller_service = combat_provenance_fixture
    client = TestClient(app)

    # HTTP endpoint for character attacks (Human player)
    char_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/entries/{char_entry_id}/attacks"
    )
    http_resp = client.get(char_url, headers={"Authorization": f"Bearer {table.player_token}"})
    assert http_resp.status_code == 200
    http_attacks = http_resp.json()
    assert len(http_attacks) > 0
    assert "content_ref" in http_attacks[0]
    assert "presentation_field" in http_attacks[0]
    assert http_attacks[0]["presentation_field"] == "name"

    # HTTP endpoint for goblin attacks (Human DM)
    goblin_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/entries/{goblin_entry_id}/attacks"
    )
    goblin_resp = client.get(goblin_url, headers={"Authorization": f"Bearer {table.dm_token}"})
    assert goblin_resp.status_code == 200
    goblin_data = goblin_resp.json()
    assert goblin_data[0]["content_ref"] == "srd5.1:monster:goblin"
    assert goblin_data[0]["presentation_field"] == "data.actions.0.name"

    # HTTP endpoint for quick enemy attacks (Human DM)
    quick_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/entries/{quick_entry_id}/attacks"
    )
    quick_resp = client.get(quick_url, headers={"Authorization": f"Bearer {table.dm_token}"})
    assert quick_resp.status_code == 200
    quick_data = quick_resp.json()
    assert quick_data[0]["name"] == "Rusty Cleaver"
    assert quick_data[0]["content_ref"] is None
    assert quick_data[0]["presentation_field"] is None

    # Handoff player seat to AI for MCP parity test
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

    # MCP tool combat_list_attacks for character using genuine AI controller token
    mcp_res = _mcp_call(
        client,
        player_grant.token,
        "combat_list_attacks",
        {"entry_id": str(char_entry_id)},
    )
    assert mcp_res["isError"] is False
    mcp_attacks = mcp_res["structuredContent"]["data"]["attacks"]
    assert len(mcp_attacks) == len(http_attacks)
    assert mcp_attacks[0]["content_ref"] == http_attacks[0]["content_ref"]
    assert mcp_attacks[0]["presentation_field"] == http_attacks[0]["presentation_field"]


def test_attack_request_and_resolution_provenance_and_secrecy(combat_provenance_fixture) -> None:
    table, char_entry_id, goblin_entry_id, quick_entry_id, _, _ = combat_provenance_fixture
    attack_service = table.attacks

    # Character attacks Goblin
    char_attacks = attack_service.available_attacks(table.player_actor, char_entry_id)
    char_weapon = char_attacks[0]

    request_view = attack_service.request_attack(
        table.player_actor,
        AttackRequestInput(
            attacker_entry_id=char_entry_id,
            target_entry_id=goblin_entry_id,
            source_ref=char_weapon.source_ref,
            range_confirmed=True,
            idempotency_key="prov-req-char-1",
        ),
    )
    assert request_view.content_ref == char_weapon.content_ref
    assert request_view.presentation_field == "name"

    # DM adjudicates attack in-range, creating roll request
    adjudicated = attack_service.adjudicate_attack(
        table.dm_actor,
        AttackAdjudicationInput(
            action_id=request_view.action_id,
            in_range=True,
            idempotency_key="prov-adj-char-1",
        ),
    )
    assert adjudicated.content_ref == char_weapon.content_ref
    assert adjudicated.presentation_field == "name"
    assert adjudicated.roll_request_id is not None

    # Complete attack as DM to obtain authoritative unredacted resolution for projection check
    res_view = attack_service.complete_attack(
        table.dm_actor,
        FormalRollInput(
            roll_request_id=adjudicated.roll_request_id,
            source=FormalRollSource.PHYSICAL,
            raw_dice=(18,),
            idempotency_key="prov-complete-char-1",
        ),
    )
    attack_dict = res_view.resolution_result["attack"]
    assert attack_dict["content_ref"] == char_weapon.content_ref
    assert attack_dict["presentation_field"] == "name"
    assert "target_ac" in attack_dict

    # Check projection secrecy for player audience vs DM audience
    player_projected = project_combat_event_payload(
        "combat.attack_resolved",
        res_view.resolution_result,
        audience="player",
    )
    dm_projected = project_combat_event_payload(
        "combat.attack_resolved",
        res_view.resolution_result,
        audience="dm",
    )

    # Player audience: target_ac is redacted from attack dict, but content_ref and presentation_field are intact!
    assert "target_ac" not in player_projected["attack"]
    assert player_projected["attack"]["content_ref"] == char_weapon.content_ref
    assert player_projected["attack"]["presentation_field"] == "name"

    # DM audience: target_ac is present along with content_ref and presentation_field
    assert "target_ac" in dm_projected["attack"]
    assert dm_projected["attack"]["content_ref"] == char_weapon.content_ref
    assert dm_projected["attack"]["presentation_field"] == "name"
