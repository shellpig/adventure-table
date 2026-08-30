from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update

from app.domain.character.schemas import CharacterBuild, CharacterState, PersistedCharacter
from app.domain.character.validation import validate_state_against_build
from app.persistence.characters import (
    CharacterNotFoundError,
    CharacterRepository,
    StaleBuildVersionError,
    characters,
    character_states,
    character_versions,
)


def save_state_against_version(
    repository: CharacterRepository,
    character_id: UUID,
    state: CharacterState,
    *,
    expected_current_version_id: UUID,
) -> PersistedCharacter:
    """Validate and persist Current State against one locked Build version.

    State patches and versioned Builder Confirm both mutate the same live
    character. The version comparison, Build read, state validation and UPDATE
    therefore have to share one transaction/lock boundary; otherwise a Level Up
    can reconcile v3 and a late state patch validated against v2 can overwrite
    that reconciled state afterwards.
    """

    with repository.engine.begin() as connection:
        row = connection.execute(
            select(
                characters.c.current_version_id,
                character_versions.c.build_payload,
            )
            .join(
                character_versions,
                character_versions.c.id == characters.c.current_version_id,
            )
            .join(
                character_states,
                character_states.c.character_id == characters.c.id,
            )
            .where(characters.c.id == character_id)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None or row["current_version_id"] is None:
            raise CharacterNotFoundError(str(character_id))

        actual_version_id = row["current_version_id"]
        if actual_version_id != expected_current_version_id:
            raise StaleBuildVersionError(
                character_id,
                expected_current_version_id,
                actual_version_id,
            )

        build = CharacterBuild.model_validate(row["build_payload"])
        validate_state_against_build(state, build, repository.registry)

        result = connection.execute(
            update(character_states)
            .where(character_states.c.character_id == character_id)
            .values(
                state_payload=state.model_dump(mode="json"),
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:
            raise CharacterNotFoundError(str(character_id))
        connection.execute(
            update(characters)
            .where(characters.c.id == character_id)
            .values(updated_at=func.now())
        )

    return repository.load_character(character_id)
