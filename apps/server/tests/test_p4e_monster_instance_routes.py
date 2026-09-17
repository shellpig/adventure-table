from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, insert, select

from app.api.dependencies import get_content_registry, get_database_engine
from app.api.rooms.access import get_room_service
from app.api.rooms.dependencies import (
    get_combat_service,
    get_combat_spell_service,
    get_monster_instance_service,
    get_table_event_service,
)
from app.content import load_default_content_registry
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import StartCombatInput
from app.domain.combat.monster_instances import MonsterInstanceService
from app.domain.combat.resolution import DamageRollPart, DamageType
from app.domain.combat.spell_resolver import SpellCastMode
from app.domain.combat.spell_service import CombatSpellService
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.domain.rooms.service import RoomService
from app.main import app
from app.persistence.combat.spells import CombatSpellRepository
from app.persistence.combat.tables import combat_entries, monster_instances
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.tables import campaigns
import tests.test_p4b_combat_lifecycle as support


@pytest.fixture
def monster_routes_fixture():
    table = support._setup()
    registry = load_default_content_registry()
    room_service = RoomService(RoomRepository(table.engine))

    monster_service = MonsterInstanceService(
        monster_repository=table.monsters,
        content_registry=registry,
        table_event_service=table.events,
    )
    spell_repo = CombatSpellRepository(table.engine, table.events.repository)
    spell_service = CombatSpellService(
        repository=spell_repo,
        combat_repository=table.combat.repository,
        combat_service=table.combat,
        table_event_service=table.events,
        monster_repository=table.monsters,
        character_repository=table.combat.character_repository,
        roll_service=table.rolls,
        registry=registry,
    )

    app.dependency_overrides[get_database_engine] = lambda: table.engine
    app.dependency_overrides[get_content_registry] = lambda: registry
    app.dependency_overrides[get_room_service] = lambda: room_service
    app.dependency_overrides[get_combat_service] = lambda: table.combat
    app.dependency_overrides[get_table_event_service] = lambda: table.events
    app.dependency_overrides[get_monster_instance_service] = lambda: monster_service
    app.dependency_overrides[get_combat_spell_service] = lambda: spell_service

    try:
        yield table, monster_service
    finally:
        app.dependency_overrides.clear()
        table.engine.dispose()


def test_dm_creates_monster_from_content_and_casts_spell_in_combat(monster_routes_fixture) -> None:
    table, _ = monster_routes_fixture
    client = TestClient(app)

    base_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/monster-instances"
    )

    # 1. DM creates srd5.1:monster:mage from content
    resp = client.post(
        f"{base_url}/from-content",
        json={"content_key": "srd5.1:monster:mage"},
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["template_key"] == "srd5.1:monster:mage"
    assert data["name"] == "Mage"
    assert data["armor_class"] == 12
    assert data["max_hp"] == 40
    assert data["current_hp"] == 40
    assert data["combat_status"] == "active"
    assert data["resources"]["spell_slot:1"] == 4
    assert data["resources"]["spell_slot:2"] == 3
    assert data["resources"]["spell_slot:3"] == 3
    assert data["resources"]["spell_slot:4"] == 3
    assert data["resources"]["spell_slot:5"] == 1

    instance_id = UUID(data["id"])

    # 2. Add monster instance to a running combat
    combat_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat"
    )
    table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key="test-start-combat"),
    )

    add_resp = client.post(
        f"{combat_url}/entries/monsters",
        json={"monster_instance_id": str(instance_id)},
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert add_resp.status_code == 200

    # 3. Roll initiative and finalize to transition combat to running
    requested = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="test-init-req"),
    )
    for index, request in enumerate(requested.requests):
        actor = table.player_actor if request.target_seat_id is not None else table.dm_actor
        raw = 1 if request.target_seat_id is not None else 20
        table.initiative.complete_initiative(
            actor,
            FormalRollInput(
                roll_request_id=request.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(raw,),
                idempotency_key=f"test-init-roll-{index}",
            ),
        )

    with table.engine.connect() as conn:
        rows = conn.execute(
            select(
                combat_entries.c.id,
                combat_entries.c.character_id,
                combat_entries.c.monster_instance_id,
            ).where(
                combat_entries.c.combat_id
                == table.combat.get_active_combat(table.dm_actor).id
            )
        ).mappings().all()
    mage_entry = next(r for r in rows if r["monster_instance_id"] == instance_id)
    target_entry = next(r for r in rows if r["character_id"] == table.character_id)
    caster_entry_id = mage_entry["id"]

    running = table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=(caster_entry_id, target_entry["id"]),
            idempotency_key="test-finalize-init",
        ),
    )
    assert running.status == "running"

    # 4. Verify cast_monster_spell works for the created instance
    spell_repo = CombatSpellRepository(table.engine, table.events.repository)
    active_combat = table.combat.get_active_combat(table.dm_actor)
    assert active_combat is not None
    dm_binding = table.events._stored_binding(table.dm_actor)

    cast_result, _ = spell_repo.cast_monster_spell(
        binding=dm_binding,
        combat_id=active_combat.id,
        caster_entry_id=caster_entry_id,
        subject_seat_id=table.dm_actor.seat_id,
        execution_mode="dm_proxy",
        spell_ref="srd5.1:spell:magic-missile",
        spell_level=1,
        slot_level=1,
        cast_mode=SpellCastMode.UTILITY,
        damage_parts=(DamageRollPart(damage_type=DamageType.FORCE, dice=(3,)),),
        target_entry_id=None,
        roll_source="server",
        idempotency_key="mage-cast-mm-test",
    )
    assert cast_result.spell_ref == "srd5.1:spell:magic-missile"
    assert cast_result.status == "resolved"
    assert cast_result.cast_mode == SpellCastMode.UTILITY

    updated = table.monsters.get_instance(instance_id)
    assert updated is not None
    assert updated.resources["spell_slot:1"] == 3


def test_dm_creates_quick_enemy_with_and_without_attack(monster_routes_fixture) -> None:
    table, _ = monster_routes_fixture
    client = TestClient(app)

    base_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/monster-instances"
    )

    # With club attack
    club_resp = client.post(
        f"{base_url}/quick-enemy",
        json={
            "name": "Goblin Brawler",
            "armor_class": 13,
            "max_hp": 8,
            "speed": {"walk": "30 ft."},
            "attack": {
                "name": "Club",
                "attack_bonus": 3,
                "damage": "1d4+1",
            },
            "visibility": "public",
        },
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert club_resp.status_code == 200
    club_data = club_resp.json()
    assert club_data["name"] == "Goblin Brawler"
    assert club_data["armor_class"] == 13
    assert club_data["max_hp"] == 8
    assert len(club_data["rules_snapshot"]["actions"]) == 1
    action = club_data["rules_snapshot"]["actions"][0]
    assert action["name"] == "Club"
    assert action["attack_kind"] == "melee_weapon"
    assert action["attack_bonus"] == 3
    assert action["damage_parts"] == [{"dice": "1d4+1", "damage_type": None}]

    # Without attack
    no_attack_resp = client.post(
        f"{base_url}/quick-enemy",
        json={
            "name": "Peasant Observer",
            "armor_class": 10,
            "max_hp": 4,
            "speed": {"walk": "30 ft."},
        },
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert no_attack_resp.status_code == 200
    no_attack_data = no_attack_resp.json()
    assert no_attack_data["name"] == "Peasant Observer"
    assert no_attack_data["rules_snapshot"].get("actions") in (None, [])


def test_player_token_rejected_with_403_and_no_rows_created(monster_routes_fixture) -> None:
    table, _ = monster_routes_fixture
    client = TestClient(app)

    base_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/monster-instances"
    )

    with table.engine.connect() as conn:
        before_count = conn.scalar(select(func.count()).select_from(monster_instances))

    # GET is DM only
    get_resp = client.get(
        base_url,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert get_resp.status_code == 403

    # POST /from-content is DM only
    post_content_resp = client.post(
        f"{base_url}/from-content",
        json={"content_key": "srd5.1:monster:goblin"},
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert post_content_resp.status_code == 403

    # POST /quick-enemy is DM only
    post_quick_resp = client.post(
        f"{base_url}/quick-enemy",
        json={
            "name": "Player Enemy",
            "armor_class": 10,
            "max_hp": 10,
            "speed": {"walk": "30 ft."},
        },
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert post_quick_resp.status_code == 403

    # Zero rows created
    with table.engine.connect() as conn:
        after_count = conn.scalar(select(func.count()).select_from(monster_instances))
    assert after_count == before_count


def test_unknown_content_key_and_non_monster_key_rejections(monster_routes_fixture) -> None:
    table, _ = monster_routes_fixture
    client = TestClient(app)

    base_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/monster-instances"
    )

    with table.engine.connect() as conn:
        before_count = conn.scalar(select(func.count()).select_from(monster_instances))

    # Unknown content key -> 404 unknown_reference
    unknown_resp = client.post(
        f"{base_url}/from-content",
        json={"content_key": "srd5.1:monster:nonexistent-creature"},
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert unknown_resp.status_code == 404
    assert unknown_resp.json()["error"]["code"] == "unknown_reference"

    # Non-monster key (e.g. spell) -> 404 or 422
    non_monster_resp = client.post(
        f"{base_url}/from-content",
        json={"content_key": "srd5.1:spell:fireball"},
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert non_monster_resp.status_code in (404, 422)

    with table.engine.connect() as conn:
        after_count = conn.scalar(select(func.count()).select_from(monster_instances))
    assert after_count == before_count


def test_idempotency_key_deduplication(monster_routes_fixture) -> None:
    table, _ = monster_routes_fixture
    client = TestClient(app)

    base_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/monster-instances"
    )

    payload = {
        "content_key": "srd5.1:monster:goblin",
        "idempotency_key": "idem-goblin-key-1",
    }

    # First call creates instance
    resp1 = client.post(
        f"{base_url}/from-content",
        json=payload,
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert resp1.status_code == 200
    id1 = resp1.json()["id"]

    with table.engine.connect() as conn:
        count_after_first = conn.scalar(select(func.count()).select_from(monster_instances))

    # Second call returns the same instance
    resp2 = client.post(
        f"{base_url}/from-content",
        json=payload,
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert resp2.status_code == 200
    id2 = resp2.json()["id"]

    assert id1 == id2

    with table.engine.connect() as conn:
        count_after_second = conn.scalar(select(func.count()).select_from(monster_instances))
    assert count_after_second == count_after_first


def test_list_instances_filtered_by_campaign(monster_routes_fixture) -> None:
    table, _ = monster_routes_fixture
    client = TestClient(app)

    base_url = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/monster-instances"
    )

    # Create instance in current campaign
    resp1 = client.post(
        f"{base_url}/quick-enemy",
        json={
            "name": "Campaign 1 Goblin",
            "armor_class": 12,
            "max_hp": 7,
            "speed": {"walk": "30 ft."},
        },
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert resp1.status_code == 200
    c1_id = resp1.json()["id"]

    # Create second campaign in same room and add an instance there
    campaign2_id = uuid4()
    now = datetime.now(timezone.utc)
    with table.engine.begin() as conn:
        conn.execute(
            insert(campaigns).values(
                id=campaign2_id,
                room_id=table.room_id,
                name="Second Campaign",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
    c2_enemy = table.monsters.create_quick_enemy(
        campaign_id=campaign2_id,
        name="Campaign 2 Orc",
        armor_class=13,
        max_hp=15,
        speed={"walk": "30 ft."},
    )

    # DM lists instances in current campaign
    list_resp = client.get(
        base_url,
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert list_resp.status_code == 200
    items = list_resp.json()
    item_ids = [item["id"] for item in items]

    assert c1_id in item_ids
    assert str(c2_enemy.id) not in item_ids
