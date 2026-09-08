from __future__ import annotations

from collections.abc import Callable
from time import sleep
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

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


StateMutation = Callable[[CharacterBuild, CharacterState], CharacterState]
DEFAULT_STATE_MUTATION_ATTEMPTS = 4
DEFAULT_STATE_RETRY_DELAY_SECONDS = 0.005


def _supports_transaction_retry(repository: CharacterRepository) -> bool:
    """Only a real Engine owns transactions that this primitive may restart."""

    return isinstance(repository.engine, Engine)


def _is_retryable_sqlite_busy(
    repository: CharacterRepository,
    exc: OperationalError,
) -> bool:
    if not _supports_transaction_retry(repository):
        return False
    if repository.engine.dialect.name != "sqlite":
        return False
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "database is locked",
            "database table is locked",
            "database is busy",
            "sqlite_busy",
        )
    )


def mutate_state_against_version(
    repository: CharacterRepository,
    character_id: UUID,
    mutation: StateMutation,
    *,
    expected_current_version_id: UUID | None = None,
    max_attempts: int = DEFAULT_STATE_MUTATION_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_STATE_RETRY_DELAY_SECONDS,
) -> PersistedCharacter:
    """Apply one Current State mutation without losing concurrent top-level writes.

    Each attempt re-reads the latest State, re-applies ``mutation`` and validates
    the resulting whole State before comparing-and-swapping ``state_revision``.
    The Build version is pinned on the first attempt (or by the caller) and never
    floats across retries. A concurrent Level Up / Build Edit therefore turns
    the retry into ``StaleBuildVersionError`` instead of applying an old semantic
    patch to a new Build.

    A normal SQLAlchemy Engine may restart a transaction after a CAS miss or a
    SQLite busy/snapshot conflict. ``TransactionBoundEngine`` deliberately is
    not an Engine, so Room/Web callers that already own a larger transaction get
    one attempt only; their outer Character lock is the serialization boundary.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds cannot be negative")

    pinned_version_id = expected_current_version_id
    attempts = max_attempts if _supports_transaction_retry(repository) else 1

    for attempt in range(attempts):
        try:
            with repository.engine.begin() as connection:
                row = connection.execute(
                    select(
                        characters.c.current_version_id,
                        characters.c.archived_at,
                        character_versions.c.build_payload,
                        character_states.c.state_payload,
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
                ).mappings().one_or_none()
                if row is None or row["current_version_id"] is None:
                    raise CharacterNotFoundError(str(character_id))
                if row["archived_at"] is not None:
                    raise CharacterArchivedError(str(character_id))

                actual_version_id = row["current_version_id"]
                if pinned_version_id is None:
                    pinned_version_id = actual_version_id
                elif actual_version_id != pinned_version_id:
                    raise StaleBuildVersionError(
                        character_id,
                        pinned_version_id,
                        actual_version_id,
                    )

                build = CharacterBuild.model_validate(row["build_payload"])
                current_state = CharacterState.model_validate(row["state_payload"])
                candidate = mutation(build, current_state)
                validate_state_against_build(candidate, build, repository.registry)
                state_revision = int(row["state_revision"])

                # Do not lock/update the Character row here. Builder reconciliation
                # owns Character -> State lock order; a partial State writer touching
                # State -> Character would introduce a deadlock cycle. The revision
                # advances in every Build reconciliation, so either concurrent order
                # is safe: we win first and Builder reconciles our committed State,
                # or Builder wins and this CAS retries into stale_build_version.
                character_guard = (
                    select(characters.c.id)
                    .where(
                        characters.c.id == character_id,
                        characters.c.current_version_id == pinned_version_id,
                        characters.c.archived_at.is_(None),
                    )
                    .exists()
                )
                result = connection.execute(
                    update(character_states)
                    .where(
                        character_states.c.character_id == character_id,
                        character_states.c.state_revision == state_revision,
                        character_guard,
                    )
                    .values(
                        state_payload=candidate.model_dump(mode="json"),
                        state_revision=state_revision + 1,
                        updated_at=func.now(),
                    )
                )
                if result.rowcount != 1:
                    raise StateWriteConflictError(character_id, state_revision)

        except StateWriteConflictError:
            if attempt + 1 >= attempts:
                raise
        except OperationalError as exc:
            if (
                not _is_retryable_sqlite_busy(repository, exc)
                or attempt + 1 >= attempts
            ):
                raise
        else:
            return repository.load_character(character_id)

        if retry_delay_seconds:
            sleep(retry_delay_seconds * (attempt + 1))

    raise RuntimeError("state mutation retry loop exhausted without a result")


def save_state_against_version(
    repository: CharacterRepository,
    character_id: UUID,
    state: CharacterState,
    *,
    expected_current_version_id: UUID,
    expected_state_revision: int | None = None,
) -> PersistedCharacter:
    """Validate and persist a complete Current State against one Build version.

    Complete-state callers may also pin ``expected_state_revision`` when the
    candidate was computed from an earlier snapshot. Passing it prevents an old
    whole-State candidate from overwriting a newer committed State. Existing
    callers that already serialize externally may omit it.
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
        if (
            expected_state_revision is not None
            and state_revision != expected_state_revision
        ):
            raise StateWriteConflictError(character_id, expected_state_revision)

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

    return repository.load_character(character_id)
