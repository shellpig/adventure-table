from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import insert, select, update

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
from app.domain.combat.ai_tools import CombatAIToolApplicationService
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    CombatNotFoundError,
    StartCombatInput,
)
from app.domain.combat.monster_instances import (
    MonsterInstancePatchInput,
    MonsterInstanceService,
    MonsterRevealPatch,
)
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import AIControllerService
from app.domain.rooms.service import RoomService
from app.domain.rooms.table_events import (
    TableEventActorUnauthorizedError,
)
from app.main import app
from app.mcp.dependencies import get_ai_tool_application_service
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.persistence.combat.lifecycle import CombatNotFoundPersistenceError
from app.persistence.combat.tables import (
    combat_entries,
    combats,
    monster_instances,
)
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.table_runtime import session_events
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    sessions,
)
from tests.test_p4b_combat_lifecycle import (
    _quick_enemy,
    _setup,
)


def _setup_bookkeeping():
    table = _setup()
    registry = load_default_content_registry()
    monster_service = MonsterInstanceService(
        monster_repository=table.monsters,
        content_registry=registry,
        table_event_service=table.events,
    )
    return table, monster_service, registry


def test_p4f_monster_name_propagation_and_idempotency() -> None:
    table, monster_service, _ = _setup_bookkeeping()
    try:
        # Start active combat
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="start-combat-1"),
        )
        active_combat = table.combat.get_active_combat(table.dm_actor)
        assert active_combat is not None
        initial_revision = active_combat.revision

        # Create quick enemy and add to combat
        enemy = _quick_enemy(table, "Goblin Scout")
        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=enemy.id, idempotency_key="add-enemy-1"),
        )

        entries = table.combat.repository.list_entries(active_combat.id)
        enemy_entry = next(e for e in entries if e.monster_instance_id == enemy.id)
        assert enemy_entry.display_name == "Goblin Scout"
        revision_after_add = table.combat.get_active_combat(table.dm_actor).revision

        # Patch monster instance name
        patch_input = MonsterInstancePatchInput(
            name="Goblin Chieftain",
            idempotency_key="patch-name-key",
        )
        updated_view = monster_service.update_instance(
            table.dm_actor,
            enemy.id,
            patch_input,
        )
        assert updated_view.name == "Goblin Chieftain"

        # Verify monster_instances row updated
        with table.engine.connect() as conn:
            inst_row = conn.execute(
                select(monster_instances).where(monster_instances.c.id == enemy.id)
            ).mappings().one()
            assert inst_row["name"] == "Goblin Chieftain"

            # Verify active combat_entries row display_name updated
            entry_row = conn.execute(
                select(combat_entries).where(combat_entries.c.id == enemy_entry.id)
            ).mappings().one()
            assert entry_row["display_name"] == "Goblin Chieftain"

            # Verify combats revision bumped
            combat_row = conn.execute(
                select(combats).where(combats.c.id == active_combat.id)
            ).mappings().one()
            assert combat_row["revision"] == revision_after_add + 1

            # Verify public event appended
            event_rows = conn.execute(
                select(session_events).where(
                    session_events.c.session_id == table.session_id,
                    session_events.c.kind == "combat.monster_instance_updated",
                )
            ).mappings().all()
            assert len(event_rows) == 1
            event = event_rows[0]
            assert event["visibility"] == "public"
            payload = event["payload"]
            assert payload["monster_instance_id"] == str(enemy.id)
            assert payload["combat_entry_id"] == str(enemy_entry.id)
            assert payload["name"] == "Goblin Chieftain"
            assert payload["visibility"] == "public"
            assert payload["changed"] == ["name"]
            assert payload["reveal"] == {
                "armor_class": False,
                "description": False,
                "position_note": False,
            }

        # Second patch with the SAME idempotency key appends no second event
        second_view = monster_service.update_instance(
            table.dm_actor,
            enemy.id,
            patch_input,
        )
        assert second_view.name == "Goblin Chieftain"
        with table.engine.connect() as conn:
            event_rows_after = conn.execute(
                select(session_events).where(
                    session_events.c.session_id == table.session_id,
                    session_events.c.kind == "combat.monster_instance_updated",
                )
            ).mappings().all()
            assert len(event_rows_after) == 1
    finally:
        table.engine.dispose()


def test_p4f_monster_hidden_to_public_projection() -> None:
    table, monster_service, _ = _setup_bookkeeping()
    try:
        # Start combat
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="start-combat-hidden"),
        )

        # Create hidden monster instance
        hidden_enemy = table.monsters.create_instance(
            campaign_id=table.campaign_id,
            name="Shadow Stalker",
            rules_snapshot={"armor_class": 16, "max_hp": 30, "speed": {"walk": 30}},
            visibility="hidden",
        )
        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=hidden_enemy.id, idempotency_key="add-hidden"),
        )

        # Before: Player's get_active_combat_detail omits the combatant
        player_detail = table.combat.get_active_combat_detail(table.player_actor)
        assert player_detail is not None
        combatant_ids = [c.projection["id"] for c in player_detail.combatants]
        assert str(hidden_enemy.id) not in combatant_ids

        # Patch visibility from hidden to public
        patch_input = MonsterInstancePatchInput(
            visibility="public",
            idempotency_key="make-public",
        )
        updated_view = monster_service.update_instance(
            table.dm_actor,
            hidden_enemy.id,
            patch_input,
        )
        assert updated_view.visibility == "public"

        # After: Player sees the combatant with allowlisted fields only
        player_detail_after = table.combat.get_active_combat_detail(table.player_actor)
        assert player_detail_after is not None
        enemy_combatant = next(
            (c for c in player_detail_after.combatants if c.projection["id"] == str(hidden_enemy.id)),
            None,
        )
        assert enemy_combatant is not None
        proj = enemy_combatant.projection
        assert proj["name"] == "Shadow Stalker"
        assert proj["combat_status"] == "active"
        assert proj["injury_level"] == "healthy"
        # Player cannot see armor_class or current_hp / max_hp on unrevealed enemy
        assert "armor_class" not in proj
        assert "current_hp" not in proj
        assert "max_hp" not in proj
    finally:
        table.engine.dispose()


def test_p4f_monster_reveal_toggles() -> None:
    table, monster_service, _ = _setup_bookkeeping()
    try:
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="start-combat-reveals"),
        )

        enemy = table.monsters.create_instance(
            campaign_id=table.campaign_id,
            name="Ancient Beast",
            rules_snapshot={
                "armor_class": 17,
                "max_hp": 110,
                "speed": {"walk": 40},
                "description": "A massive draconic monster.",
            },
            position_note="perched on the ledge",
            visibility="public",
        )
        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(monster_instance_id=enemy.id, idempotency_key="add-beast"),
        )

        # Before reveals: Player sees no AC, no description, no position_note
        p_detail = table.combat.get_active_combat_detail(table.player_actor)
        p_combatant = next(c for c in p_detail.combatants if c.projection["id"] == str(enemy.id))
        assert "armor_class" not in p_combatant.projection
        assert "description" not in p_combatant.projection
        assert "position_note" not in p_combatant.projection

        dm_detail = table.combat.get_active_combat_detail(table.dm_actor)
        dm_combatant = next(c for c in dm_detail.combatants if c.projection["id"] == str(enemy.id))
        assert dm_combatant.projection["armor_class"] == 17
        assert dm_combatant.projection["description"] == "A massive draconic monster."
        assert dm_combatant.projection["position_note"] == "perched on the ledge"

        # Patch 1: Reveal armor_class = True
        monster_service.update_instance(
            table.dm_actor,
            enemy.id,
            MonsterInstancePatchInput(
                reveal=MonsterRevealPatch(armor_class=True),
                idempotency_key="reveal-ac",
            ),
        )
        p_detail_1 = table.combat.get_active_combat_detail(table.player_actor)
        p_combatant_1 = next(c for c in p_detail_1.combatants if c.projection["id"] == str(enemy.id))
        assert p_combatant_1.projection["armor_class"] == 17
        assert "current_hp" not in p_combatant_1.projection
        assert "description" not in p_combatant_1.projection
        assert "position_note" not in p_combatant_1.projection

        # Patch 2: Reveal position_note = True and update note
        monster_service.update_instance(
            table.dm_actor,
            enemy.id,
            MonsterInstancePatchInput(
                position_note="hovering near the ceiling",
                reveal=MonsterRevealPatch(position_note=True),
                idempotency_key="reveal-pos",
            ),
        )
        p_detail_2 = table.combat.get_active_combat_detail(table.player_actor)
        p_combatant_2 = next(c for c in p_detail_2.combatants if c.projection["id"] == str(enemy.id))
        assert p_combatant_2.projection["armor_class"] == 17
        assert p_combatant_2.projection["position_note"] == "hovering near the ceiling"
        assert "current_hp" not in p_combatant_2.projection

        # DM projection remains unchanged and complete throughout
        dm_detail_final = table.combat.get_active_combat_detail(table.dm_actor)
        dm_combatant_final = next(c for c in dm_detail_final.combatants if c.projection["id"] == str(enemy.id))
        assert dm_combatant_final.projection["armor_class"] == 17
        assert dm_combatant_final.projection["description"] == "A massive draconic monster."
        assert dm_combatant_final.projection["position_note"] == "hovering near the ceiling"
        assert dm_combatant_final.projection["current_hp"] == 110
    finally:
        table.engine.dispose()


def test_p4f_monster_bookkeeping_authorization_and_validation() -> None:
    table, monster_service, _ = _setup_bookkeeping()
    try:
        enemy = _quick_enemy(table, "Target Goblin")

        # 1. Player actor -> TableEventActorUnauthorizedError, zero changes, no event
        with pytest.raises(TableEventActorUnauthorizedError):
            monster_service.update_instance(
                table.player_actor,
                enemy.id,
                MonsterInstancePatchInput(name="Player Renamed"),
            )
        # Verify no changes in DB
        with table.engine.connect() as conn:
            row = conn.execute(
                select(monster_instances).where(monster_instances.c.id == enemy.id)
            ).mappings().one()
            assert row["name"] == "Target Goblin"
            events = conn.execute(
                select(session_events).where(
                    session_events.c.kind == "combat.monster_instance_updated"
                )
            ).mappings().all()
            assert len(events) == 0

        # 2. Instance from another campaign -> CombatNotFoundError
        foreign_id = uuid4()
        with pytest.raises(CombatNotFoundError):
            monster_service.update_instance(
                table.dm_actor,
                foreign_id,
                MonsterInstancePatchInput(name="Foreign"),
            )

        # 3. Empty patch -> ValueError / ValidationError before any write
        with pytest.raises((ValueError, ValidationError)):
            MonsterInstancePatchInput()

        with pytest.raises((ValueError, ValidationError)):
            MonsterInstancePatchInput(idempotency_key="only-key")

        with pytest.raises((ValueError, ValidationError)):
            MonsterInstancePatchInput(reveal=MonsterRevealPatch())
    finally:
        table.engine.dispose()


def test_p4f_monster_bookkeeping_rest_and_mcp_parity() -> None:
    table, monster_service, registry = _setup_bookkeeping()
    room_service = RoomService(RoomRepository(table.engine))
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
        enemy = _quick_enemy(table, "Original Enemy")
        base_url = (
            f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
            f"/sessions/{table.session_id}/monster-instances/{enemy.id}"
        )

        # 1. REST DM PATCH 200 with updated view
        dm_resp = client.patch(
            base_url,
            json={"name": "REST Updated Enemy", "visibility": "public"},
            headers={"Authorization": f"Bearer {table.dm_token}"},
        )
        assert dm_resp.status_code == 200, dm_resp.text
        assert dm_resp.json()["name"] == "REST Updated Enemy"

        # 2. REST Player PATCH 403
        player_resp = client.patch(
            base_url,
            json={"name": "Hacked Name"},
            headers={"Authorization": f"Bearer {table.player_token}"},
        )
        assert player_resp.status_code == 403
        assert player_resp.json()["error"]["code"] == "table_actor_unauthorized"

        # 3. AI DM combat_update_monster_instance reaches the same state
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
                    "name": "combat_update_monster_instance",
                    "arguments": {
                        "instance_id": str(enemy.id),
                        "name": "MCP Updated Enemy",
                        "position_note": "top of the tower",
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
                "Mcp-Name": "combat_update_monster_instance",
            },
        )
        assert mcp_resp.status_code == 200, mcp_resp.text
        mcp_result = mcp_resp.json()["result"]
        assert mcp_result["content"][0]["text"]
        mcp_data = mcp_result["structuredContent"]["data"]
        assert mcp_data["name"] == "MCP Updated Enemy"
        assert mcp_data["position_note"] == "top of the tower"
    finally:
        app.dependency_overrides.clear()
        table.engine.dispose()


def test_p4f_monster_bookkeeping_event_secrecy() -> None:
    table, monster_service, _ = _setup_bookkeeping()
    try:
        enemy = _quick_enemy(table, "Secret Goblin")

        # Patch that sets ALL fields
        patch_input = MonsterInstancePatchInput(
            name="Overlord Goblin",
            visibility="public",
            position_note="hiding beneath trapdoor secret",
            reveal=MonsterRevealPatch(
                armor_class=True,
                description=True,
                position_note=True,
            ),
            idempotency_key="secrecy-assert-key",
        )
        monster_service.update_instance(
            table.dm_actor,
            enemy.id,
            patch_input,
        )

        with table.engine.connect() as conn:
            event = conn.execute(
                select(session_events).where(
                    session_events.c.kind == "combat.monster_instance_updated",
                    session_events.c.idempotency_key == "p4f-monster-update:secrecy-assert-key",
                )
            ).mappings().one()

        payload = event["payload"]

        # 1. Payload never contains position_note text
        assert "hiding beneath trapdoor secret" not in str(payload)
        assert "position_note" not in payload

        # 2. Payload never contains raw numeric armor_class, hp, current_hp, or max_hp
        assert "armor_class" not in payload
        assert "hp" not in payload
        assert "current_hp" not in payload
        assert "max_hp" not in payload
        assert "dm_notes" not in payload
        assert "rules_snapshot" not in payload

        # 3. Payload has exact expected key set
        assert set(payload.keys()) == {
            "monster_instance_id",
            "combat_entry_id",
            "name",
            "visibility",
            "changed",
            "reveal",
        }
        assert set(payload["reveal"].keys()) == {
            "armor_class",
            "description",
            "position_note",
        }
        # Reveal values are booleans
        assert payload["reveal"]["armor_class"] is True
        assert payload["reveal"]["description"] is True
        assert payload["reveal"]["position_note"] is True
    finally:
        table.engine.dispose()
