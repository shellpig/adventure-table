from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character_builder.service import CharacterBuilderService
from app.main import app
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import (
    CharacterRepository,
    characters,
    character_states,
    character_versions,
)


def _seed_builder_api():
    registry = load_default_content_registry()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    app.state.content_registry = registry
    app.state.character_engine = engine
    app.state.character_repository = CharacterRepository(engine, registry)
    app.state.character_builder_service = CharacterBuilderService(
        BuilderDraftRepository(engine),
        registry,
    )
    return TestClient(app), engine


def _count(engine, table) -> int:
    with engine.connect() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    return int(value or 0)


def test_character_builder_draft_api_lifecycle_and_machine_errors() -> None:
    client, engine = _seed_builder_api()

    created = client.post(
        "/api/character-builder/drafts",
        json={
            "draft_payload": {
                "basic": {"name": "Draft Hero"},
                "target_level": 1,
            }
        },
    )
    assert created.status_code == 201
    view = created.json()
    draft_id = view["draft"]["id"]
    assert view["draft"]["revision"] == 1
    assert view["validation"]["can_confirm"] is False
    assert any(
        issue["code"] == "missing_race"
        and issue["severity"] == "blocking_error"
        for issue in view["validation"]["issues"]
    )

    assert _count(engine, characters) == 0
    assert _count(engine, character_versions) == 0
    assert _count(engine, character_states) == 0

    first_choice_ids = [choice["choice_id"] for choice in view["choices"]]
    reloaded = client.get(f"/api/character-builder/drafts/{draft_id}")
    assert reloaded.status_code == 200
    assert [choice["choice_id"] for choice in reloaded.json()["choices"]] == first_choice_ids

    patched = client.patch(
        f"/api/character-builder/drafts/{draft_id}",
        json={
            "expected_revision": 1,
            "draft_payload": {
                "basic": {"name": " Draft Hero "},
                "race_selection": {"reference_id": "srd5.1:race:human"},
                "numeric_overrides": [{"key": "armor_class", "value": 17}],
            },
        },
    )
    assert patched.status_code == 200
    payload = patched.json()
    assert payload["draft"]["revision"] == 2
    patched_ids = [choice["choice_id"] for choice in payload["choices"]]
    assert set(first_choice_ids).issubset(patched_ids)
    assert patched_ids[:4] == first_choice_ids[:4]
    severities = {issue["severity"] for issue in payload["validation"]["issues"]}
    assert {"blocking_error", "warning", "non_standard"}.issubset(severities)

    stale = client.patch(
        f"/api/character-builder/drafts/{draft_id}",
        json={
            "expected_revision": 1,
            "draft_payload": {"basic": {"name": "Stale overwrite"}},
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_draft_revision"

    validated = client.post(f"/api/character-builder/drafts/{draft_id}/validate")
    assert validated.status_code == 200
    assert validated.json()["can_confirm"] is False
    assert validated.json()["non_standard_count"] == 1

    cancelled = client.delete(f"/api/character-builder/drafts/{draft_id}")
    assert cancelled.status_code == 204
    missing = client.get(f"/api/character-builder/drafts/{draft_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "builder_draft_not_found"

    engine.dispose()


def test_character_builder_api_rejects_malformed_and_disabled_modes() -> None:
    client, engine = _seed_builder_api()

    malformed = client.post(
        "/api/character-builder/drafts",
        json={"draft_payload": {"target_level": 1, "unexpected": True}},
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "validation_failed"

    illegal_source = client.post(
        "/api/character-builder/drafts",
        json={
            "mode": "create",
            "character_id": str(uuid4()),
            "draft_payload": {},
        },
    )
    assert illegal_source.status_code == 422
    assert illegal_source.json()["error"]["code"] == "validation_failed"

    disabled = client.post(
        "/api/character-builder/drafts",
        json={
            "mode": "level_up",
            "character_id": str(uuid4()),
            "base_version_id": str(uuid4()),
            "draft_payload": {},
        },
    )
    assert disabled.status_code == 422
    assert disabled.json()["error"]["code"] == "builder_mode_not_enabled"

    engine.dispose()
