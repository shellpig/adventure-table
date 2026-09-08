from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update

from app.domain.character.schemas import CharacterBuild, CharacterState, PersistedCharacter
from app.domain.character.validation import validate_state_against_build
from app.persistence.characters import (
    CharacterArchivedError,
    CharacterNotFoundError,
    CharacterRepository,
    StateWriteConflictError,
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
    """Validate and persist a complete Current State against one Build version.

    Full-state writers are protected by the same monotonic ``state_revision``
    used by partial patches. A caller that computed a complete State from an old
    snapshot must receive a conflict instead of silently overwriting a newer
    committed State. Partial PATCH retry/remerge behavior lives in the atomic
    patch mutation; this complete-state primitive deliberately never retries an
    old candidate.
    """

    with repository.engine.begin() as connection:
        row = connection.execute(
            select(
                characters.c.current_version_id,
                characters.c.archived_at,
                character_versions.c.build_payload,
                character_states.c.state_revision,
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

        # Checked inside the same lock as the version comparison: an archive
        # landing between check and write would otherwise let a state patch
        # through against a character that is no longer in play.
        if row["archived_at"] is not None:
            raise CharacterArchivedError(str(character_id))

        actual_version_id = row["current_version_id"]
        if actual_version_id != expected_current_version_id:
            raise StaleBuildVersionError(
                character_id,
                expected_current_version_id,
                actual_version_id,
            )

        build = CharacterBuild.model_validate(row["build_payload"])
        validate_state_against_build(state, build, repository.registry)
        state_revision = int(row["state_revision"])

        result = connection.execute(
            update(character_states)
            .where(
                character_states.c.character_id == character_id,
                character_states.c.state_revision == state_revision,
            )
            .values(
                state_payload=state.model_dump(mode="json"),
                state_revision=state_revision + 1,
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:
            raise StateWriteConflictError(character_id, state_revision)
        connection.execute(
            update(characters)
            .where(characters.c.id == character_id)
            .values(updated_at=func.now())
        )

    return repository.load_character(character_id)
