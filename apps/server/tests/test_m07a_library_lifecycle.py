from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generator
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, insert
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import (
    get_content_localization,
    get_content_registry,
    get_database_engine,
)
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_monster_instance_service,
    get_monster_library_service,
)
from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import resolve_content_root
from app.db import metadata
from app.domain.combat.monster_instances import MonsterInstanceService
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.main import app
from app.persistence.combat.repository import MonsterRepository
from app.persistence.monster_library.repository import MonsterLibraryRepository
from app.persistence.rooms.tables import campaigns, rooms


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


@dataclass(frozen=True)
class LibraryFixture:
    client: TestClient
    engine: Engine
    room_id: UUID
    token_owner: str
    token_dm: str
    token_member: str
    campaign_id: UUID
    instance_service: MonsterInstanceService
    library_service: MonsterLibraryService


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def library_fixture() -> Generator[LibraryFixture, None, None]:
    engine = _engine()
    registry = load_default_content_registry()
    content_root = resolve_content_root()
    localization = load_content_localization_catalog(registry, content_root)

    room_id = uuid4()
    campaign_id = uuid4()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                id=room_id,
                code="LIBROOM",
                name="Library Room",
                password_salt=b"salt",
                password_hash=b"pw",
                owner_key_hash=b"owner",
                dm_key_hash=b"dm",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaigns).values(
                id=campaign_id,
                room_id=room_id,
                name="Campaign 1",
                ruleset="dnd-5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )

    token_owner = "tok-owner"
    token_dm = "tok-dm"
    token_member = "tok-member"

    token_to_context = {
        token_owner: RoomAccessContext(
            room_id=room_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner",
        ),
        token_dm: RoomAccessContext(
            room_id=room_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.DM,
            display_name="DM",
        ),
        token_member: RoomAccessContext(
            room_id=room_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.MEMBER,
            display_name="Member",
        ),
    }

    def _override_access(request: Request) -> RoomAccessContext:
        auth_hdr = request.headers.get("authorization", "")
        _, _, token = auth_hdr.partition(" ")
        clean = token.strip()
        if clean in token_to_context:
            return token_to_context[clean]
        raise APIError(401, "room_access_required", "Room access required")

    monster_repo = MonsterRepository(engine)
    library_repo = MonsterLibraryRepository(engine)

    from app.persistence.rooms.table_runtime import TableEventRepository
    from app.domain.rooms.table_events import TableEventService

    event_repo = TableEventRepository(engine)
    table_event_service = TableEventService(event_repo)

    library_service = MonsterLibraryService(
        engine=engine,
        repository=library_repo,
        monster_repository=monster_repo,
        content_registry=registry,
        localization=localization,
        table_event_service=table_event_service,
    )
    instance_service = MonsterInstanceService(
        monster_repository=monster_repo,
        content_registry=registry,
        table_event_service=table_event_service,
    )

    app.state.content_registry = registry
    app.state.content_localization = localization
    app.state.monster_library_service = library_service
    app.state.monster_instance_service = instance_service

    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_content_registry] = lambda: registry
    app.dependency_overrides[get_content_localization] = lambda: localization
    app.dependency_overrides[get_room_access_context] = _override_access
    app.dependency_overrides[get_monster_library_service] = lambda: library_service
    app.dependency_overrides[get_monster_instance_service] = lambda: instance_service

    client = TestClient(app)
    try:
        yield LibraryFixture(
            client=client,
            engine=engine,
            room_id=room_id,
            token_owner=token_owner,
            token_dm=token_dm,
            token_member=token_member,
            campaign_id=campaign_id,
            instance_service=instance_service,
            library_service=library_service,
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_monster_library_no_session_needed(library_fixture: LibraryFixture) -> None:
    fix = library_fixture
    resp = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library",
        headers=_auth(fix.token_owner),
    )
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list)
    assert len(items) > 0


def test_monster_library_builtin_read_only_and_desc_presentation(library_fixture: LibraryFixture) -> None:
    fix = library_fixture
    encoded_ref = quote("srd5.1:monster:goblin", safe="")
    resp = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library/{encoded_ref}",
        headers=_auth(fix.token_owner),
    )
    assert resp.status_code == 200
    detail = resp.json()

    assert detail["source_kind"] == "builtin"
    assert detail["ref"] == "srd5.1:monster:goblin"
    assert detail["name"] == "Goblin"
    assert detail["names"]["en"] == "Goblin"
    assert detail["names"].get("zh-TW") == "地精"
    assert detail["name_is_custom"] is False

    rules = detail["rules"]
    assert rules["armor_class"] == 15
    assert rules["max_hp"] == 7

    # Traits: Nimble Escape
    traits = rules["traits"]
    assert len(traits) > 0
    nimble = next((t for t in traits if t.get("name") == "Nimble Escape"), None)
    assert nimble is not None
    assert "Disengage" in nimble["desc"]

    # Pure rules: no presentation keys in rules dicts
    for group in ("traits", "actions", "bonus_actions", "reactions", "legendary_actions"):
        for item in rules.get(group, []):
            assert "desc_is_english" not in item
            assert "is_english_source" not in item
            assert "names" not in item

    # Presentation dict checks
    assert detail["presentation"]["desc_is_english"] is True
    assert detail["presentation"]["ability_names"]["traits"][0] == {
        "en": "Nimble Escape",
        "zh-TW": "迅捷逃逸",
    }

    # Read-only check: attempt to patch built-in template
    patch_resp = fix.client.patch(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{encoded_ref}",
        json={"expected_revision": 1, "armor_class": 18},
        headers=_auth(fix.token_owner),
    )
    assert patch_resp.status_code == 403
    assert patch_resp.json()["error"]["code"] == "monster_template_read_only"

    # Read-only check: attempt to archive built-in template
    arch_resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{encoded_ref}/archive",
        json={"expected_revision": 1},
        headers=_auth(fix.token_owner),
    )
    assert arch_resp.status_code == 403
    assert arch_resp.json()["error"]["code"] == "monster_template_read_only"

    # Read-only check: attempt to delete built-in template
    del_resp = fix.client.delete(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{encoded_ref}?expected_revision=1",
        headers=_auth(fix.token_owner),
    )
    assert del_resp.status_code == 403
    assert del_resp.json()["error"]["code"] == "monster_template_read_only"


def test_monster_library_search_and_desc_exclusion(library_fixture: LibraryFixture) -> None:
    fix = library_fixture

    # Match English name
    r_en = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library?query=goblin",
        headers=_auth(fix.token_owner),
    )
    assert r_en.status_code == 200
    refs_en = [item["ref"] for item in r_en.json()]
    assert "srd5.1:monster:goblin" in refs_en

    # Match zh-TW name
    r_zh = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library?query=地精",
        headers=_auth(fix.token_owner),
    )
    assert r_zh.status_code == 200
    refs_zh = [item["ref"] for item in r_zh.json()]
    assert "srd5.1:monster:goblin" in refs_zh

    # Match monster type
    r_type = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library?query=humanoid",
        headers=_auth(fix.token_owner),
    )
    assert r_type.status_code == 200
    refs_type = [item["ref"] for item in r_type.json()]
    assert "srd5.1:monster:goblin" in refs_type

    # Search word found ONLY in ability desc ("Disengage") must NOT match goblin
    r_desc = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library?query=Disengage",
        headers=_auth(fix.token_owner),
    )
    assert r_desc.status_code == 200
    refs_desc = [item["ref"] for item in r_desc.json()]
    assert "srd5.1:monster:goblin" not in refs_desc


def test_copy_builtin_to_custom_without_name(library_fixture: LibraryFixture) -> None:
    fix = library_fixture
    resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom/from-content",
        json={"content_key": "srd5.1:monster:goblin"},
        headers=_auth(fix.token_owner),
    )
    assert resp.status_code == 201
    custom = resp.json()

    assert custom["source_kind"] == "custom"
    assert custom["source_key"] == "srd5.1:monster:goblin"
    assert custom["ref"].startswith("custom:")
    assert custom["name"] == "Goblin"
    assert custom["names"] == {"en": "Goblin", "zh-TW": "地精"}
    assert custom["name_is_custom"] is False
    assert custom["rules"]["armor_class"] == 15
    assert custom["rules"]["max_hp"] == 7
    assert len(custom["rules"]["actions"]) > 0

    # Verify original built-in content remains unchanged
    encoded_ref = quote("srd5.1:monster:goblin", safe="")
    orig_resp = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library/{encoded_ref}",
        headers=_auth(fix.token_owner),
    )
    assert orig_resp.status_code == 200
    assert orig_resp.json()["source_kind"] == "builtin"


def test_copy_builtin_to_custom_with_custom_name(library_fixture: LibraryFixture) -> None:
    fix = library_fixture
    resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom/from-content",
        json={"content_key": "srd5.1:monster:goblin", "name": "Goblin Chieftain"},
        headers=_auth(fix.token_owner),
    )
    assert resp.status_code == 201
    custom = resp.json()

    assert custom["name"] == "Goblin Chieftain"
    assert custom["name_is_custom"] is True
    assert custom["rules"]["name"] == "Goblin Chieftain"


def test_create_custom_monster_from_zero(library_fixture: LibraryFixture) -> None:
    fix = library_fixture
    payload = {
        "name": "Shadow Drake",
        "armor_class": 16,
        "max_hp": 65,
        "speed": {"walk": "30 ft.", "fly": "60 ft."},
        "size": "large",
        "type": "dragon",
        "alignment": "neutral evil",
        "actions": [
            {
                "name": "Bite",
                "attack_bonus": 6,
                "damage_dice": "2d6+4",
                "damage_type": "piercing",
                "desc": "Melee weapon attack: +6 to hit, reach 10 ft., one target. Hit: 11 (2d6+4) piercing damage.",
            }
        ],
        "description": "A draconic creature formed from shadow.",
    }
    resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom",
        json=payload,
        headers=_auth(fix.token_owner),
    )
    assert resp.status_code == 201
    drake = resp.json()

    assert drake["source_kind"] == "custom"
    assert drake["name"] == "Shadow Drake"
    assert drake["name_is_custom"] is True
    assert drake["revision"] == 1
    assert drake["rules"]["armor_class"] == 16
    assert drake["rules"]["max_hp"] == 65
    assert drake["rules"]["description"] == "A draconic creature formed from shadow."
    actions = drake["rules"]["actions"]
    assert len(actions) == 1
    assert actions[0]["name"] == "Bite"
    assert actions[0]["attack_bonus"] == 6


def test_save_from_quick_enemy_instance_rules_only(library_fixture: LibraryFixture) -> None:
    fix = library_fixture

    # 1. Create a damaged quick enemy instance directly in monster_repository
    stored_inst = fix.instance_service.monster_repository.create_instance(
        campaign_id=fix.campaign_id,
        name="Wild Owlbear",
        rules_snapshot={
            "name": "Wild Owlbear",
            "armor_class": 13,
            "max_hp": 59,
            "speed": {"walk": "40 ft."},
            "actions": [
                {
                    "name": "Beak",
                    "attack_bonus": 7,
                    "damage_dice": "1d10+5",
                    "damage_type": "piercing",
                }
            ],
        },
        current_hp=25,  # Damaged!
        conditions=["poisoned", "blinded"],  # Live conditions!
        reaction_available=False,  # Live reaction consumed!
        initiative=12,  # Live initiative!
    )
    assert stored_inst.current_hp == 25
    assert "poisoned" in stored_inst.conditions
    assert stored_inst.reaction_available is False
    assert stored_inst.initiative == 12

    # 2. Save instance as custom template via POST /custom/from-instance
    resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom/from-instance",
        json={"instance_id": str(stored_inst.id), "name": "Saved Owlbear Template"},
        headers=_auth(fix.token_owner),
    )
    assert resp.status_code == 201
    saved = resp.json()

    assert saved["name"] == "Saved Owlbear Template"
    assert saved["source_kind"] == "custom"
    template_rules = saved["rules"]
    assert template_rules["armor_class"] == 13
    assert template_rules["max_hp"] == 59

    # Live combat state must NEVER be part of the template rules
    assert "current_hp" not in template_rules
    assert "conditions" not in template_rules
    assert "reaction_available" not in template_rules
    assert "reaction_used" not in template_rules
    assert "initiative" not in template_rules


def test_copy_custom_template(library_fixture: LibraryFixture) -> None:
    fix = library_fixture
    # Create custom template
    c_resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom",
        json={
            "name": "Cult Acolyte",
            "armor_class": 10,
            "max_hp": 9,
            "actions": [{"name": "Club", "attack_bonus": 2, "damage_dice": "1d4", "damage_type": "bludgeoning"}],
        },
        headers=_auth(fix.token_owner),
    )
    assert c_resp.status_code == 201
    source_id = c_resp.json()["ref"].removeprefix("custom:")

    # Copy custom template
    copy_resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{source_id}/copy",
        json={"expected_revision": 1, "name": "Cult Fanatic Variant"},
        headers=_auth(fix.token_owner),
    )
    assert copy_resp.status_code == 201
    copied = copy_resp.json()

    assert copied["name"] == "Cult Fanatic Variant"
    assert copied["ref"] != f"custom:{source_id}"
    assert copied["rules"]["armor_class"] == 10
    assert copied["rules"]["max_hp"] == 9
    assert len(copied["rules"]["actions"]) == 1


def test_patch_only_armor_class_preserves_everything_else(library_fixture: LibraryFixture) -> None:
    fix = library_fixture

    # Copy goblin to custom
    c_resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom/from-content",
        json={"content_key": "srd5.1:monster:goblin", "name": "Heavy Goblin"},
        headers=_auth(fix.token_owner),
    )
    assert c_resp.status_code == 201
    template_id = c_resp.json()["ref"].removeprefix("custom:")
    orig_rules = c_resp.json()["rules"]

    # PATCH only armor_class
    patch_resp = fix.client.patch(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{template_id}",
        json={"expected_revision": 1, "armor_class": 19},
        headers=_auth(fix.token_owner),
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()

    assert patched["revision"] == 2
    assert patched["rules"]["armor_class"] == 19
    # max_hp unchanged
    assert patched["rules"]["max_hp"] == orig_rules["max_hp"]
    # traits, actions, ability_scores preserved completely
    assert patched["rules"]["traits"] == orig_rules["traits"]
    assert patched["rules"]["actions"] == orig_rules["actions"]
    assert patched["rules"]["ability_scores"] == orig_rules["ability_scores"]
    assert patched["rules"]["speed"] == orig_rules["speed"]
    assert patched["rules"]["senses"] == orig_rules["senses"]


def test_get_entry_by_encoded_ref(library_fixture: LibraryFixture) -> None:
    fix = library_fixture
    encoded_ref = quote("srd5.1:monster:goblin", safe="")
    resp = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library/{encoded_ref}",
        headers=_auth(fix.token_owner),
    )
    assert resp.status_code == 200
    assert resp.json()["ref"] == "srd5.1:monster:goblin"


def test_builtin_reactions_and_legendary_presentation_and_patch_action_drop(
    library_fixture: LibraryFixture,
) -> None:
    fix = library_fixture

    # 1. Built-in with reactions: bandit-captain
    ref_bc = quote("srd5.1:monster:bandit-captain", safe="")
    resp_bc = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library/{ref_bc}",
        headers=_auth(fix.token_owner),
    )
    assert resp_bc.status_code == 200
    bc_detail = resp_bc.json()
    assert bc_detail["presentation"]["ability_names"]["reactions"][0] == {
        "en": "Parry",
        "zh-TW": "格擋",
    }
    # Rules contain no presentation keys
    for group in ("traits", "actions", "bonus_actions", "reactions", "legendary_actions"):
        for item in bc_detail["rules"].get(group, []):
            assert "desc_is_english" not in item
            assert "is_english_source" not in item
            assert "names" not in item

    # 2. Built-in with legendary actions: aboleth
    ref_ab = quote("srd5.1:monster:aboleth", safe="")
    resp_ab = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library/{ref_ab}",
        headers=_auth(fix.token_owner),
    )
    assert resp_ab.status_code == 200
    ab_detail = resp_ab.json()
    assert ab_detail["presentation"]["ability_names"]["legendary_actions"][0] == {
        "en": "Detect",
        "zh-TW": "偵查",
    }

    # 3. From-content copy keeps ability_names
    c_resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom/from-content",
        json={"content_key": "srd5.1:monster:bandit-captain"},
        headers=_auth(fix.token_owner),
    )
    assert c_resp.status_code == 201
    custom_bc = c_resp.json()
    assert custom_bc["presentation"]["ability_names"]["reactions"][0] == {
        "en": "Parry",
        "zh-TW": "格擋",
    }
    assert "actions" in custom_bc["presentation"]["ability_names"]
    template_id = custom_bc["ref"].removeprefix("custom:")

    # 4. Patching actions drops ONLY actions' ability_names
    patch_resp = fix.client.patch(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{template_id}",
        json={
            "expected_revision": 1,
            "actions": [
                {
                    "name": "Custom Strike",
                    "desc": "Strikes fiercely.",
                    "kind": "attack",
                }
            ],
        },
        headers=_auth(fix.token_owner),
    )
    assert patch_resp.status_code == 200
    patched_bc = patch_resp.json()
    # actions ability_names is dropped
    assert "actions" not in patched_bc["presentation"]["ability_names"]
    # reactions ability_names is still preserved
    assert patched_bc["presentation"]["ability_names"]["reactions"][0] == {
        "en": "Parry",
        "zh-TW": "格擋",
    }
