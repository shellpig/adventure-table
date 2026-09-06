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
    character = repository.create_character(
        character_id=uuid4(),
        name=P0_FIXTURE_NAME,
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    client = create_web_room_client(
        engine,
        registry,
        character_repository=repository,
        character_ids=(character.id,),
    )

    response = client.get(client.character_api)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    character_payload = payload[0]
    assert character_payload["class_summary"] == "Fighter 5 / Wizard 5"
    assert character_payload["classes"] == [
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
