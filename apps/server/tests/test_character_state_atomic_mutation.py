from __future__ import annotations

from queue import Queue
from threading import Event, Lock, Thread, current_thread
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, insert, select, update
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import OperationalError

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
    StaleBuildVersionError,
    characters,
    character_states,
    character_versions,
)
from app.persistence.state_mutations import mutate_state_against_version


def _seed_repository(tmp_path):
    registry = load_default_content_registry()
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database=str(tmp_path / "character-state-cas.sqlite3"),
        ),
        connect_args={
            "check_same_thread": False,
            "timeout": 0.05,
        },
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.commit()
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


def _revision(engine: Engine, character_id: UUID) -> int:
    with engine.connect() as connection:
        value = connection.scalar(
            select(character_states.c.state_revision).where(
                character_states.c.character_id == character_id
            )
        )
    assert value is not None
    return int(value)


def _patch(
    repository: CharacterRepository,
    character_id: UUID,
    version_id: UUID,
    changes: dict[str, object],
):
    def apply(_build, state: CharacterState) -> CharacterState:
        return CharacterState.model_validate(
            {**state.model_dump(mode="python"), **changes}
        )

    return mutate_state_against_version(
        repository,
        character_id,
        apply,
        expected_current_version_id=version_id,
        retry_delay_seconds=0,
    )


def _pause_first_state_read(engine: Engine, *, thread_name: str):
    first_read = Event()
    release = Event()
    seen = False
    guard = Lock()

    def listener(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal seen
        if current_thread().name != thread_name:
            return
        normalized = statement.lstrip().upper()
        if not normalized.startswith("SELECT") or "STATE_REVISION" not in normalized:
            return
        with guard:
            if seen:
                return
            seen = True
        first_read.set()
        assert release.wait(timeout=5), "controlled interleaving was not released"

    event.listen(engine, "after_cursor_execute", listener)
    return first_read, release, listener


def _run_patch_in_thread(
    repository: CharacterRepository,
    *,
    character_id: UUID,
    version_id: UUID,
    changes: dict[str, object],
    thread_name: str,
):
    results: Queue[object] = Queue()

    def worker() -> None:
        try:
            results.put(
                _patch(
                    repository,
                    character_id,
                    version_id,
                    changes,
                )
            )
        except BaseException as exc:  # surfaced in the test thread below
            results.put(exc)

    thread = Thread(target=worker, name=thread_name, daemon=True)
    thread.start()
    return thread, results


def test_partial_mutation_remerges_latest_state_after_sqlite_busy_snapshot(
    tmp_path,
) -> None:
    engine, repository, character = _seed_repository(tmp_path)
    original_hp = character.state.current_hp
    first_read, release, listener = _pause_first_state_read(
        engine,
        thread_name="hp-patch",
    )
    thread, results = _run_patch_in_thread(
        repository,
        character_id=character.id,
        version_id=character.current_version_id,
        changes={"current_hp": original_hp - 5},
        thread_name="hp-patch",
    )

    try:
        assert first_read.wait(timeout=5), "worker never reached its first State read"
        main_update = _patch(
            repository,
            character.id,
            character.current_version_id,
            {"temporary_hp": 7},
        )
        assert main_update.state.temporary_hp == 7
    finally:
        release.set()
        thread.join(timeout=5)
        event.remove(engine, "after_cursor_execute", listener)

    assert not thread.is_alive()
    result = results.get_nowait()
    if isinstance(result, BaseException):
        raise result

    final = repository.load_character(character.id)
    assert final.state.current_hp == original_hp - 5
    assert final.state.temporary_hp == 7
    assert _revision(engine, character.id) == 3


def test_same_top_level_field_remains_whole_field_last_write_wins(
    tmp_path,
) -> None:
    engine, repository, character = _seed_repository(tmp_path)
    worker_value = {"d10": 4, "d6": 4}
    main_value = {"d10": 3, "d6": 5}
    first_read, release, listener = _pause_first_state_read(
        engine,
        thread_name="hit-dice-patch",
    )
    thread, results = _run_patch_in_thread(
        repository,
        character_id=character.id,
        version_id=character.current_version_id,
        changes={"hit_dice_state": worker_value},
        thread_name="hit-dice-patch",
    )

    try:
        assert first_read.wait(timeout=5)
        _patch(
            repository,
            character.id,
            character.current_version_id,
            {"hit_dice_state": main_value},
        )
    finally:
        release.set()
        thread.join(timeout=5)
        event.remove(engine, "after_cursor_execute", listener)

    assert not thread.is_alive()
    result = results.get_nowait()
    if isinstance(result, BaseException):
        raise result

    final = repository.load_character(character.id)
    assert final.state.hit_dice_state == worker_value
    assert final.state.hit_dice_state != {
        "d10": worker_value["d10"],
        "d6": main_value["d6"],
    }


def _append_equivalent_build_version(
    engine: Engine,
    *,
    character_id: UUID,
    current_version_id: UUID,
) -> UUID:
    next_version_id = uuid4()
    with engine.begin() as connection:
        current = connection.execute(
            select(character_versions).where(
                character_versions.c.id == current_version_id,
                character_versions.c.character_id == character_id,
            )
        ).mappings().one()
        connection.execute(
            insert(character_versions).values(
                id=next_version_id,
                character_id=character_id,
                version_no=int(current["version_no"]) + 1,
                build_payload=current["build_payload"],
                builder_provenance=current["builder_provenance"],
                version_kind="correction",
                parent_version_id=current_version_id,
                superseded_by_version_id=None,
                change_note="controlled stale-build interleaving",
            )
        )
        connection.execute(
            update(characters)
            .where(characters.c.id == character_id)
            .values(
                current_version_id=next_version_id,
                updated_at=func.now(),
            )
        )
        connection.execute(
            update(character_states)
            .where(character_states.c.character_id == character_id)
            .values(
                state_revision=character_states.c.state_revision + 1,
                updated_at=func.now(),
            )
        )
    return next_version_id


def test_retry_pins_build_version_and_rejects_build_change_without_partial_write(
    tmp_path,
) -> None:
    engine, repository, character = _seed_repository(tmp_path)
    original_hp = character.state.current_hp
    first_read, release, listener = _pause_first_state_read(
        engine,
        thread_name="stale-build-patch",
    )
    thread, results = _run_patch_in_thread(
        repository,
        character_id=character.id,
        version_id=character.current_version_id,
        changes={"current_hp": original_hp - 9},
        thread_name="stale-build-patch",
    )

    try:
        assert first_read.wait(timeout=5)
        next_version_id = _append_equivalent_build_version(
            engine,
            character_id=character.id,
            current_version_id=character.current_version_id,
        )
    finally:
        release.set()
        thread.join(timeout=5)
        event.remove(engine, "after_cursor_execute", listener)

    assert not thread.is_alive()
    result = results.get_nowait()
    assert isinstance(result, StaleBuildVersionError)
    assert result.expected_version_id == character.current_version_id
    assert result.actual_version_id == next_version_id

    final = repository.load_character(character.id)
    assert final.current_version_id == next_version_id
    assert final.state.current_hp == original_hp
    assert _revision(engine, character.id) == 2


def test_sqlite_busy_retry_is_finite(
    tmp_path,
) -> None:
    engine, repository, character = _seed_repository(tmp_path)
    state_reads = 0

    def count_state_reads(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal state_reads
        normalized = statement.lstrip().upper()
        if normalized.startswith("SELECT") and "STATE_REVISION" in normalized:
            state_reads += 1

    event.listen(engine, "after_cursor_execute", count_state_reads)
    blocker = engine.connect()
    try:
        blocker.exec_driver_sql("BEGIN IMMEDIATE")
        with pytest.raises(OperationalError):
            mutate_state_against_version(
                repository,
                character.id,
                lambda _build, state: CharacterState.model_validate(
                    {
                        **state.model_dump(mode="python"),
                        "temporary_hp": 11,
                    }
                ),
                expected_current_version_id=character.current_version_id,
                max_attempts=2,
                retry_delay_seconds=0,
            )
    finally:
        blocker.rollback()
        blocker.close()
        event.remove(engine, "after_cursor_execute", count_state_reads)

    assert state_reads == 2
    final = repository.load_character(character.id)
    assert final.state.temporary_hp == character.state.temporary_hp
    assert _revision(engine, character.id) == 1
