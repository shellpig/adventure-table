from __future__ import annotations

from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.persistence.characters import CharacterRepository, character_states


def _seed_repository():
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
    return engine, repository, character


def _revision(engine, character_id) -> int:
    with engine.connect() as connection:
        value = connection.scalar(
            select(character_states.c.state_revision).where(
                character_states.c.character_id == character_id
            )
        )
    assert value is not None
    return int(value)


def test_new_character_state_starts_at_revision_one() -> None:
    engine, _, character = _seed_repository()

    assert _revision(engine, character.id) == 1


def test_complete_state_writer_advances_revision() -> None:
    engine, repository, character = _seed_repository()
    next_hp = character.state.current_hp - 1
    updated_state = character.state.model_copy(update={"current_hp": next_hp})

    updated = repository.save_state(
        character.id,
        updated_state,
        expected_current_version_id=character.current_version_id,
    )

    assert updated.state.current_hp == next_hp
    assert _revision(engine, character.id) == 2
