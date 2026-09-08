from __future__ import annotations

from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character.schemas import CharacterState
from app.persistence.characters import (
    CharacterRepository,
    StateWriteConflictError,
    character_states,
)
from app.persistence.state_mutations import (
    mutate_state_against_version,
    save_state_against_version,
)
from app.persistence.transaction_bound import TransactionBoundEngine


class _RollbackProbe(RuntimeError):
    pass


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
    return engine, registry, repository, character


def _revision(engine: Engine, character_id) -> int:
    with engine.connect() as connection:
        value = connection.scalar(
            select(character_states.c.state_revision).where(
                character_states.c.character_id == character_id
            )
        )
    assert value is not None
    return int(value)


def test_complete_state_candidate_can_pin_source_revision() -> None:
    engine, _, repository, character = _seed_repository()
    original = character.state
    first = original.model_copy(update={"temporary_hp": 3})

    save_state_against_version(
        repository,
        character.id,
        first,
        expected_current_version_id=character.current_version_id,
        expected_state_revision=1,
    )
    assert _revision(engine, character.id) == 2

    stale_candidate = original.model_copy(update={"current_hp": original.current_hp - 2})
    with pytest.raises(StateWriteConflictError) as caught:
        save_state_against_version(
            repository,
            character.id,
            stale_candidate,
            expected_current_version_id=character.current_version_id,
            expected_state_revision=1,
        )

    assert caught.value.expected_state_revision == 1
    final = repository.load_character(character.id)
    assert final.state.temporary_hp == 3
    assert final.state.current_hp == original.current_hp
    assert _revision(engine, character.id) == 2


def test_transaction_bound_mutation_participates_in_outer_rollback() -> None:
    engine, registry, repository, character = _seed_repository()
    original_hp = character.state.current_hp

    with pytest.raises(_RollbackProbe):
        with engine.begin() as connection:
            bound_engine = cast(Engine, TransactionBoundEngine(connection))
            bound_repository = CharacterRepository(bound_engine, registry)

            updated = mutate_state_against_version(
                bound_repository,
                character.id,
                lambda _build, state: CharacterState.model_validate(
                    {
                        **state.model_dump(mode="python"),
                        "current_hp": original_hp - 1,
                    }
                ),
                expected_current_version_id=character.current_version_id,
            )

            assert updated.state.current_hp == original_hp - 1
            inside_revision = connection.scalar(
                select(character_states.c.state_revision).where(
                    character_states.c.character_id == character.id
                )
            )
            assert inside_revision == 2
            raise _RollbackProbe("outer Room transaction decides commit/rollback")

    final = repository.load_character(character.id)
    assert final.state.current_hp == original_hp
    assert _revision(engine, character.id) == 1
