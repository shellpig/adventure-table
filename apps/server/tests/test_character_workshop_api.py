from __future__ import annotations

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
from app.domain.character_builder.service import CharacterBuilderService
from app.main import app
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import CharacterRepository


def _seed_workshop_api() -> TestClient:
    registry = load_default_content_registry()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    character_repository = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    character_repository.create_character(
        character_id=uuid4(),
        name=P0_FIXTURE_NAME,
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    app.state.content_registry = registry
    app.state.character_engine = engine
    app.state.character_repository = character_repository
    app.state.character_builder_service = CharacterBuilderService(
        BuilderDraftRepository(engine),
        registry,
    )
    return TestClient(app)


def test_character_workshop_summary_and_create_draft_listing() -> None:
    client = _seed_workshop_api()

    characters = client.get("/api/characters")
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
        "/api/character-builder/drafts",
        json={"mode": "create", "draft_payload": {"basic": {"name": "Resume Me"}}},
    )
    assert created.status_code == 201
    draft_id = created.json()["draft"]["id"]

    drafts = client.get("/api/character-builder/drafts")
    assert drafts.status_code == 200
    assert [item["draft"]["id"] for item in drafts.json()] == [draft_id]
    assert drafts.json()[0]["resolved_summary"]["name"] == "Resume Me"


def test_ability_rules_api_is_backed_by_versioned_rules_data() -> None:
    client = _seed_workshop_api()
    response = client.get("/api/character-builder/rules/ability-generation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["standard_array"] == [15, 14, 13, 12, 10, 8]
    assert payload["point_buy_budget"] == 27
    assert payload["point_buy_costs"]["15"] == 9
    assert payload["manual_standard_min"] == 3
    assert payload["manual_standard_max"] == 18
