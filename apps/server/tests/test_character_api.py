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


def test_state_patch_is_atomic_and_does_not_change_build_version():
    client, repository, character = _seed_api()
    before = repository.load_character(character.id)
    before_build = before.build.model_dump(mode="json")

    patched = client.patch(
        f"/api/characters/{character.id}/state",
        json={
            "current_hp": 60,
            "temporary_hp": 3,
            "prepared_spell_entry_ids": [
                "wizard:magic-missile",
                "wizard:detect-magic",
            ],
            "hit_dice_state": {"d10": 4, "d6": 5},
            "inventory_state": [
                {
                    **item.model_dump(mode="json"),
                    "equipped": False
                    if item.entry_id == "inventory:shield"
                    else item.equipped,
                    "quantity": 1
                    if item.entry_id == "inventory:healing-potion"
                    else item.quantity,
                }
                for item in before.state.inventory_state
            ],
        },
    )
    assert patched.status_code == 200
    payload = patched.json()
    assert payload["current_hp"] == 60
    assert payload["temporary_hp"] == 3
    assert payload["armor_class"] == 16
    assert next(
        item for item in payload["hit_dice"] if item["die"] == "d10"
    )["available"] == 4

    after = repository.load_character(character.id)
    assert after.current_version_id == before.current_version_id
    assert after.version_no == before.version_no
    assert after.build.model_dump(mode="json") == before_build

    invalid = client.patch(
        f"/api/characters/{character.id}/state",
        json={"hit_dice_state": {"d10": 6, "d6": 5}},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_failed"
    unchanged = repository.load_character(character.id)
    assert unchanged.state.hit_dice_state == after.state.hit_dice_state


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
