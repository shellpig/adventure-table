from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.persistence.characters import (
    CharacterNotArchivedError,
    CharacterNotFoundError,
    CharacterRepository,
    character_states,
    character_versions,
)
from test_p1f_character_creation import _complete_fighter_draft
from test_p1f_character_creation import _seed as _seed_builder_client
from web_room_support import create_web_room_client


def _seed():
    registry = load_default_content_registry()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    repository = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    character_id = uuid4()
    repository.create_character(
        character_id=character_id,
        name=P0_FIXTURE_NAME,
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    client = create_web_room_client(
        engine,
        registry,
        character_repository=repository,
        character_ids=(character_id,),
    )
    return client, repository, str(character_id)


def test_archive_moves_a_character_between_the_two_lists() -> None:
    client, _repository, character_id = _seed()
    api = client.character_api

    assert [row["id"] for row in client.get(api).json()] == [character_id]
    assert client.get(f"{api}?archived=true").json() == []

    assert client.post(f"{api}/{character_id}/archive").status_code == 200

    assert client.get(api).json() == []
    archived = client.get(f"{api}?archived=true").json()
    assert [row["id"] for row in archived] == [character_id]
    assert archived[0]["name"] == P0_FIXTURE_NAME
    assert archived[0]["class_summary"] == "Fighter 5 / Wizard 5"

    assert client.post(f"{api}/{character_id}/unarchive").status_code == 200
    assert [row["id"] for row in client.get(api).json()] == [character_id]
    assert client.get(f"{api}?archived=true").json() == []


def test_archived_characters_stay_readable() -> None:
    client, _repository, character_id = _seed()
    api = client.character_api
    client.post(f"{api}/{character_id}/archive")

    assert client.get(f"{api}/{character_id}").status_code == 200
    assert client.get(f"{api}/{character_id}/sheet").status_code == 200
    assert client.get(f"{api}/{character_id}/versions").status_code == 200


def test_archived_characters_refuse_state_writes() -> None:
    client, _repository, character_id = _seed()
    api = client.character_api
    sheet = client.get(f"{api}/{character_id}/sheet").json()
    patch = {
        "expected_current_version_id": sheet["current_version_id"],
        "current_hp": 1,
    }

    assert client.patch(f"{api}/{character_id}/state", json=patch).status_code == 200

    client.post(f"{api}/{character_id}/archive")
    blocked = client.patch(f"{api}/{character_id}/state", json=patch)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "character_archived"

    client.post(f"{api}/{character_id}/unarchive")
    assert client.patch(f"{api}/{character_id}/state", json=patch).status_code == 200


def test_delete_requires_archiving_first() -> None:
    client, repository, character_id = _seed()

    refused = client.delete(f"{client.character_api}/{character_id}")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "character_not_archived"
    assert repository.load_character(UUID(character_id)).archived_at is None


def test_delete_removes_the_character_and_everything_it_owns() -> None:
    client, repository, character_id = _seed()
    api = client.character_api
    client.post(f"{api}/{character_id}/archive")

    assert client.delete(f"{api}/{character_id}").status_code == 204

    assert client.get(api).json() == []
    assert client.get(f"{api}?archived=true").json() == []
    assert client.get(f"{api}/{character_id}").status_code == 404

    with repository.engine.connect() as connection:
        versions = connection.execute(character_versions.select()).all()
        states = connection.execute(character_states.select()).all()
    assert versions == []
    assert states == []


def test_repository_refuses_to_delete_an_active_character() -> None:
    _client, repository, character_id = _seed()
    identifier = repository.list_characters()[0].id

    with pytest.raises(CharacterNotArchivedError):
        repository.delete_character(identifier)

    assert repository.load_character(identifier).archived_at is None
    assert str(identifier) == character_id


def test_repository_reports_a_missing_character_rather_than_silently_passing() -> None:
    _client, repository, _character_id = _seed()

    with pytest.raises(CharacterNotFoundError):
        repository.set_archived(uuid4(), True)
    with pytest.raises(CharacterNotFoundError):
        repository.delete_character(uuid4())


def test_archiving_blocks_confirm_but_keeps_the_draft() -> None:
    """Archiving does not cancel work in progress; it stops the write."""

    client, _engine = _seed_builder_client()
    created_character = client.post(
        f"{client.builder_api}/drafts/{_complete_fighter_draft(client)['draft']['id']}/confirm"
    )
    assert created_character.status_code == 200, created_character.text
    character_id = created_character.json()["character_id"]

    created = client.post(
        f"{client.builder_api}/characters/{character_id}/drafts",
        json={"mode": "build_edit"},
    )
    assert created.status_code == 201, created.text
    draft_id = created.json()["draft"]["id"]

    client.post(f"{client.character_api}/{character_id}/archive")

    blocked = client.post(f"{client.builder_api}/drafts/{draft_id}/confirm")
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "character_archived"

    assert client.get(f"{client.builder_api}/drafts/{draft_id}").status_code == 200

    client.post(f"{client.character_api}/{character_id}/unarchive")
    resumed = client.post(f"{client.builder_api}/drafts/{draft_id}/confirm")
    assert resumed.status_code == 200, resumed.text
