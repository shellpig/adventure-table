from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update

from app.persistence.rooms.table_runtime import session_events

from app.api.dependencies import get_content_registry, get_database_engine
from app.api.rooms.access import get_room_service
from app.api.rooms.ai_controllers import get_ai_controller_service
from app.api.rooms.dependencies import (
    get_combat_attack_service,
    get_combat_initiative_service,
    get_combat_service,
    get_monster_instance_service,
    get_table_event_service,
)
from app.content.registry import load_default_content_registry
from app.domain.combat.ai_tools import CombatAIToolApplicationService
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.attacks import AttackDefinitionView, CombatAttackService
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.combat.monster_instances import (
    CreateQuickEnemyInput,
    MonsterInstanceService,
    QuickEnemyAttackInput,
)
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import (
    AIControllerService,
    AIHandoffRequest,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.service import RoomService
from app.main import app
from app.mcp.dependencies import get_ai_tool_application_service
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.persistence.characters import CharacterRepository
from app.persistence.combat.adjudication import CombatAdjudicationRepository
from app.persistence.combat.attacks import CombatAttackRepository
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    sessions,
)
from app.persistence.rooms.exploration import ExplorationRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_pending import PendingActionRepository
from app.persistence.rooms.p3c_rolls import RollRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    sessions,
)
import tests.test_p4b_combat_lifecycle as support


def _body(method: str, *, params: dict | None = None, request_id: int | str = 1) -> dict:
    merged = dict(params or {})
    merged["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "p4f-test", "version": "1"},
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


def test_quick_enemy_attack_input_model_validation() -> None:
    # 1. attack_kind alias mapping
    melee = QuickEnemyAttackInput(name="Scimitar", damage="1d6+2", attack_kind="melee")
    assert melee.attack_kind == "melee_weapon"

    ranged = QuickEnemyAttackInput(name="Shortbow", damage="1d6+2", attack_kind="ranged")
    assert ranged.attack_kind == "ranged_weapon"

    # Canonical values pass through
    for kind in ("melee_weapon", "ranged_weapon", "melee_spell", "ranged_spell", None):
        item = QuickEnemyAttackInput(name="Test", damage="1d6+2", attack_kind=kind)
        assert item.attack_kind == kind

    # Invalid attack_kind raises ValidationError
    with pytest.raises(ValidationError):
        QuickEnemyAttackInput(name="Sword", damage="1d6+2", attack_kind="sword")

    # 2. damage parsing and validation
    pass_1 = QuickEnemyAttackInput(name="A", damage="1d6+2")
    assert pass_1.damage == "1d6+2"

    pass_2 = QuickEnemyAttackInput(name="B", damage="1d6+2 slashing")
    assert pass_2.damage == "1d6+2 slashing"

    pass_3 = QuickEnemyAttackInput(name="C", damage="2d8 fire")
    assert pass_3.damage == "2d8 fire"

    # Invalid damage values raise ValidationError
    for bad_damage in ("1d6+2 sharp", "slashing", "d6", "1d6+2 untyped"):
        with pytest.raises(ValidationError) as exc_info:
            QuickEnemyAttackInput(name="Bad", damage=bad_damage)
        assert "damage must be a dice formula like 1d6+2, optionally followed by a damage type" in str(
            exc_info.value
        )


def test_quick_enemy_available_attacks_returns_resolved_definition() -> None:
    table = support._setup()
    registry = load_default_content_registry()
    character_repo = CharacterRepository(table.engine, registry)
    monster_service = MonsterInstanceService(
        monster_repository=table.monsters,
        content_registry=registry,
        table_event_service=table.events,
    )

    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key="p4f-quick-combat-start"),
    )

    created_view = monster_service.create_quick_enemy(
        table.dm_actor,
        CreateQuickEnemyInput(
            name="Scimitar Bandit",
            armor_class=12,
            max_hp=11,
            speed={"walk": "30 ft."},
            attack=QuickEnemyAttackInput(
                name="Scimitar",
                attack_bonus=4,
                damage="1d6+2 slashing",
                attack_kind="melee",
            ),
        ),
    )

    added = table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=created_view.id,
            idempotency_key="p4f-add-scimitar-bandit",
        ),
    )
    enemy_entry = next(entry for entry in added.entries if entry.monster_instance_id == created_view.id)

    attacks_service = CombatAttackService(
        repository=CombatAttackRepository(table.engine, table.events.repository),
        adjudication_repository=CombatAdjudicationRepository(table.engine, table.events.repository),
        combat_repository=table.combat.repository,
        combat_service=table.combat,
        definition_resolver=AttackDefinitionResolver(character_repo, table.monsters, registry),
        roll_service=table.rolls,
        table_event_service=table.events,
    )

    available = attacks_service.available_attacks(table.dm_actor, enemy_entry.id)
    assert len(available) == 1
    attack = available[0]
    assert isinstance(attack, AttackDefinitionView)
    assert attack.name == "Scimitar"
    assert attack.attack_kind == "melee"
    assert attack.attack_bonus == 4
    assert len(attack.damage_parts) == 1
    assert attack.damage_parts[0] == {
        "damage_type": "slashing",
        "dice_count": 1,
        "die_size": 6,
        "flat_modifier": 2,
    }


def test_quick_enemy_mcp_attack_lifecycle_and_player_secrecy() -> None:
    table = support._setup()
    registry = load_default_content_registry()
    character_repo = CharacterRepository(table.engine, registry)
    room_service = RoomService(RoomRepository(table.engine))
    attack_repo = CombatAttackRepository(table.engine, table.events.repository)
    adjudication_repo = CombatAdjudicationRepository(table.engine, table.events.repository)

    definition_resolver = AttackDefinitionResolver(character_repo, table.monsters, registry)
    attack_service = CombatAttackService(
        repository=attack_repo,
        adjudication_repository=adjudication_repo,
        combat_repository=table.combat.repository,
        combat_service=table.combat,
        definition_resolver=definition_resolver,
        roll_service=table.rolls,
        table_event_service=table.events,
    )
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
        combat_attack_service=attack_service,
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
    app.dependency_overrides[get_combat_attack_service] = lambda: attack_service
    app.dependency_overrides[get_ai_tool_application_service] = lambda: combat_ai_tool_service

    # Setup player grant and DM grant
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
    player_token = player_grant.token

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
    dm_token = minted.plaintext

    client = TestClient(app)
    try:
        # Start combat
        start_res = _mcp_call(
            client,
            dm_token,
            "combat_start",
            {"idempotency_key": "p4f-mcp-combat-start"},
        )
        assert start_res["isError"] is False

        # DM creates quick enemy via MCP
        create_res = _mcp_call(
            client,
            dm_token,
            "combat_create_quick_enemy",
            {
                "name": "Scimitar Bandit",
                "armor_class": 12,
                "max_hp": 11,
                "speed": {"walk": "30 ft."},
                "attack": {
                    "name": "Scimitar",
                    "attack_bonus": 4,
                    "damage": "1d6+2 slashing",
                    "attack_kind": "melee",
                },
            },
        )
        assert create_res["isError"] is False
        monster_id = create_res["structuredContent"]["data"]["id"]

        # DM adds quick enemy to combat
        add_res = _mcp_call(
            client,
            dm_token,
            "combat_add_monster",
            {"monster_instance_id": monster_id},
        )
        assert add_res["isError"] is False
        entries = add_res["structuredContent"]["data"]["entries"]
        enemy_entry = next(e for e in entries if e["monster_instance_id"] == monster_id)
        enemy_entry_id = enemy_entry["id"]

        # DM calls combat_list_attacks -> exactly 1 attack
        list_res = _mcp_call(
            client,
            dm_token,
            "combat_list_attacks",
            {"entry_id": enemy_entry_id},
        )
        assert list_res["isError"] is False
        attacks = list_res["structuredContent"]["data"]["attacks"]
        assert len(attacks) == 1
        assert attacks[0]["name"] == "Scimitar"
        assert attacks[0]["attack_kind"] == "melee"
        assert attacks[0]["attack_bonus"] == 4

        # Player calls combat_list_attacks on monster entry -> permission_denied with zero events written
        with table.engine.connect() as connection:
            events_before = connection.scalar(
                select(func.count())
                .select_from(session_events)
                .where(session_events.c.session_id == table.session_id)
            )

        player_res = _mcp_call(
            client,
            player_token,
            "combat_list_attacks",
            {"entry_id": enemy_entry_id},
        )
        assert player_res["isError"] is True
        assert player_res["structuredContent"]["error"]["code"] == "permission_denied"

        with table.engine.connect() as connection:
            events_after = connection.scalar(
                select(func.count())
                .select_from(session_events)
                .where(session_events.c.session_id == table.session_id)
            )
        assert events_after == events_before
    finally:
        app.dependency_overrides.clear()
        app.state.ai_tool_application_service = None
        table.engine.dispose()


def test_quick_enemy_rest_validation_and_creation() -> None:
    table = support._setup()
    registry = load_default_content_registry()
    room_service = RoomService(RoomRepository(table.engine))
    monster_service = MonsterInstanceService(
        monster_repository=table.monsters,
        content_registry=registry,
        table_event_service=table.events,
    )

    app.dependency_overrides[get_database_engine] = lambda: table.engine
    app.dependency_overrides[get_content_registry] = lambda: registry
    app.dependency_overrides[get_room_service] = lambda: room_service
    app.dependency_overrides[get_combat_service] = lambda: table.combat
    app.dependency_overrides[get_table_event_service] = lambda: table.events
    app.dependency_overrides[get_monster_instance_service] = lambda: monster_service

    client = TestClient(app)
    base_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/monster-instances"
    )

    try:
        # Invalid attack_kind "sword" returns 422
        resp_bad = client.post(
            f"{base_url}/quick-enemy",
            json={
                "name": "Invalid Bandit",
                "armor_class": 12,
                "max_hp": 11,
                "speed": {"walk": "30 ft."},
                "attack": {
                    "name": "Sword",
                    "attack_bonus": 3,
                    "damage": "1d6+2",
                    "attack_kind": "sword",
                },
            },
            headers={"Authorization": f"Bearer {table.dm_token}"},
        )
        assert resp_bad.status_code == 422

        # Valid attack with damage "1d6+2 slashing" succeeds and actions show the split
        resp_good = client.post(
            f"{base_url}/quick-enemy",
            json={
                "name": "Slashing Bandit",
                "armor_class": 12,
                "max_hp": 11,
                "speed": {"walk": "30 ft."},
                "attack": {
                    "name": "Scimitar",
                    "attack_bonus": 4,
                    "damage": "1d6+2 slashing",
                    "attack_kind": "melee",
                },
            },
            headers={"Authorization": f"Bearer {table.dm_token}"},
        )
        assert resp_good.status_code in (200, 201)
        data = resp_good.json()
        assert len(data["rules_snapshot"]["actions"]) == 1
        action = data["rules_snapshot"]["actions"][0]
        assert action["name"] == "Scimitar"
        assert action["attack_kind"] == "melee_weapon"
        assert action["attack_bonus"] == 4
        assert action["damage_parts"] == [{"dice": "1d6+2", "damage_type": "slashing"}]
    finally:
        app.dependency_overrides.clear()
        table.engine.dispose()
