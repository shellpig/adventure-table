from __future__ import annotations

from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.persistence.characters import CharacterRepository
from web_room_support import create_web_room_client


def _seed_workshop_api():
    registry = load_default_content_registry()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    character_repository = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    character = character_repository.create_character(
        character_id=uuid4(),
        name=P0_FIXTURE_NAME,
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    return create_web_room_client(
        engine,
        registry,
        character_repository=character_repository,
        character_ids=(character.id,),
    )


def test_character_workshop_summary_and_create_draft_listing() -> None:
    client = _seed_workshop_api()

    characters = client.get(client.character_api)
    assert characters.status_code == 200
    payload = characters.json()
    assert payload == [
        {
            "id": payload[0]["id"],
            "name": P0_FIXTURE_NAME,
            "level": 10,
            "class_summary": "Fighter 5 / Wizard 5",
            "classes": [
                {"class_ref": "srd5.1:class:fighter", "name": "Fighter", "level": 5},
                {"class_ref": "srd5.1:class:wizard", "name": "Wizard", "level": 5},
            ],
            "version_no": 1,
        }
    ]

    created = client.post(
        f"{client.builder_api}/drafts",
        json={"mode": "create", "draft_payload": {"basic": {"name": "Resume Me"}}},
    )
    assert created.status_code == 201
    draft_id = created.json()["draft"]["id"]

    drafts = client.get(f"{client.builder_api}/drafts")
    assert drafts.status_code == 200
    assert [item["draft"]["id"] for item in drafts.json()] == [draft_id]
    assert drafts.json()[0]["resolved_summary"]["name"] == "Resume Me"


def test_ability_rules_api_is_backed_by_versioned_rules_data() -> None:
    client = _seed_workshop_api()
    response = client.get(f"{client.builder_api}/rules/ability-generation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["standard_array"] == [15, 14, 13, 12, 10, 8]
    assert payload["point_buy_budget"] == 27
    assert payload["point_buy_costs"]["15"] == 9
    assert payload["manual_standard_min"] == 3
    assert payload["manual_standard_max"] == 18
