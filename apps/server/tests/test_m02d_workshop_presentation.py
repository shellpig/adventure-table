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
from app.main import app
from app.persistence.characters import CharacterRepository


def test_character_list_exposes_stable_class_identity_for_localized_workshop() -> None:
    registry = load_default_content_registry()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    repository = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    repository.create_character(
        character_id=uuid4(),
        name=P0_FIXTURE_NAME,
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    app.state.content_registry = registry
    app.state.character_repository = repository

    response = TestClient(app).get("/api/characters")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    character = payload[0]
    assert character["class_summary"] == "Fighter 5 / Wizard 5"
    assert character["classes"] == [
        {
            "class_ref": "srd5.1:class:fighter",
            "name": "Fighter",
            "level": 5,
        },
        {
            "class_ref": "srd5.1:class:wizard",
            "name": "Wizard",
            "level": 5,
        },
    ]
