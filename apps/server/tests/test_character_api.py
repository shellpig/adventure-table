from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.main import app
from app.persistence.characters import CharacterRepository


def _seed_api():
    registry = load_default_content_registry()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    repository = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    character = repository.create_character(
        character_id=uuid4(),
        name=P0_FIXTURE_NAME,
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    app.state.content_registry = registry
    app.state.character_repository = repository
    return TestClient(app), repository, character


def test_reference_api_known_and_unknown_content():
    client, _, _ = _seed_api()

    spells = client.get("/api/rules/content/spells")
    assert spells.status_code == 200
    assert any(item["key"] == "srd5.1:spell:fireball" for item in spells.json())

    fireball = client.get("/api/rules/content/spells/srd5.1:spell:fireball")
    assert fireball.status_code == 200
    assert fireball.json()["name"] == "Fireball"

    fighter = client.get("/api/rules/content/classes/fighter")
    assert fighter.status_code == 200
    assert fighter.json()["key"] == "srd5.1:class:fighter"

    missing = client.get("/api/rules/content/spells/not-a-spell")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "unknown_reference"


def test_character_and_sheet_api_expose_persisted_and_derived_models():
    client, _, character = _seed_api()

    raw = client.get(f"/api/characters/{character.id}")
    assert raw.status_code == 200
    assert raw.json()["build"]["character_level"] == 10

    sheet = client.get(f"/api/characters/{character.id}/sheet")
    assert sheet.status_code == 200
    payload = sheet.json()
    assert payload["name"] == P0_FIXTURE_NAME
    assert payload["total_level"] == 10
    assert payload["armor_class"] == 18
    assert payload["max_hp"] == 74
    assert {
        item["die"]: (item["available"], item["total"])
        for item in payload["hit_dice"]
    } == {
        "d10": (5, 5),
        "d6": (5, 5),
    }
    assert any(
        item["entry_id"] == "wizard:detect-magic" and not item["prepared"]
        for item in payload["spells"]
    )
    assert any(
        item["entry_id"] == "wizard:fireball" and item["prepared"]
        for item in payload["spells"]
    )
    assert any(item["entry_id"] == "inventory:shield" for item in payload["inventory"])


def test_state_patch_covers_p0_mutations_and_keeps_build_immutable():
    client, repository, character = _seed_api()
    before = repository.load_character(character.id)
    before_build = before.build.model_dump(mode="json")

    inventory = []
    for item in before.state.inventory_state:
        if item.entry_id == "inventory:longsword":
            continue
        payload = item.model_dump(mode="json")
        if item.entry_id == "inventory:shield":
            payload["equipped"] = False
        if item.entry_id == "inventory:healing-potion":
            payload["quantity"] = 1
        inventory.append(payload)
    inventory.append(
        {
            "entry_id": "inventory:dagger",
            "item_ref": "srd5.1:equipment:dagger",
            "quantity": 1,
            "equipped": False,
            "carried": True,
        }
    )

    patched = client.patch(
        f"/api/characters/{character.id}/state",
        json={
            "current_hp": 60,
            "temporary_hp": 3,
            "conditions": [
                {
                    "condition_ref": "srd5.1:condition:poisoned",
                    "note": "P0-D API regression",
                }
            ],
            "prepared_spell_entry_ids": [
                "wizard:magic-missile",
                "wizard:detect-magic",
            ],
            "spell_slots": {
                "1": {"used": 2, "remaining": 2},
                "2": {"used": 0, "remaining": 3},
                "3": {"used": 1, "remaining": 1},
            },
            "resources": {
                "wizard:arcane-recovery": {"used": 1, "remaining": 0}
            },
            "hit_dice_state": {"d10": 4, "d6": 5},
            "inventory_state": inventory,
        },
    )
    assert patched.status_code == 200
    payload = patched.json()
    assert payload["current_hp"] == 60
    assert payload["temporary_hp"] == 3
    assert payload["armor_class"] == 16
    assert payload["conditions"][0]["condition_ref"] == "srd5.1:condition:poisoned"
    assert payload["spell_slots"]["1"] == {"used": 2, "remaining": 2}
    assert payload["resources"]["wizard:arcane-recovery"] == {
        "used": 1,
        "remaining": 0,
    }
    assert next(
        item for item in payload["hit_dice"] if item["die"] == "d10"
    )["available"] == 4
    inventory_by_id = {item["entry_id"]: item for item in payload["inventory"]}
    assert "inventory:longsword" not in inventory_by_id
    assert inventory_by_id["inventory:shield"]["equipped"] is False
    assert inventory_by_id["inventory:healing-potion"]["quantity"] == 1
    assert inventory_by_id["inventory:dagger"]["item_ref"] == "srd5.1:equipment:dagger"

    after = repository.load_character(character.id)
    assert after.current_version_id == before.current_version_id
    assert after.version_no == before.version_no
    assert after.build.model_dump(mode="json") == before_build


def test_invalid_state_requests_are_atomic_and_machine_readable():
    client, repository, character = _seed_api()
    baseline = repository.load_character(character.id)
    baseline_state = baseline.state.model_dump(mode="json")
    baseline_version_id = baseline.current_version_id
    baseline_build = baseline.build.model_dump(mode="json")

    invalid_patches = [
        {
            "inventory_state": [
                {
                    "entry_id": "inventory:bad-quantity",
                    "item_ref": "srd5.1:equipment:dagger",
                    "quantity": -1,
                }
            ]
        },
        {"conditions": [{"condition_ref": "not-a-stable-key"}]},
        {"prepared_spell_entry_ids": ["wizard:not-in-build"]},
        {"hit_dice_state": {"d10": 6, "d6": 5}},
        {
            "inventory_state": [
                {
                    "entry_id": "inventory:bad-ref",
                    "item_ref": "not-a-stable-key",
                    "quantity": 1,
                }
            ]
        },
        {"current_hp": "many"},
        {"current_hp": 75},
    ]

    for patch in invalid_patches:
        response = client.patch(f"/api/characters/{character.id}/state", json=patch)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_failed"
        reloaded = repository.load_character(character.id)
        assert reloaded.state.model_dump(mode="json") == baseline_state
        assert reloaded.current_version_id == baseline_version_id
        assert reloaded.build.model_dump(mode="json") == baseline_build


def test_invalid_state_types_and_missing_character_use_machine_codes():
    client, _, character = _seed_api()

    bad_type = client.patch(
        f"/api/characters/{character.id}/state",
        json={"current_hp": "many"},
    )
    assert bad_type.status_code == 422
    assert bad_type.json()["error"]["code"] == "validation_failed"

    missing = client.get(f"/api/characters/{uuid4()}/sheet")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "character_not_found"
