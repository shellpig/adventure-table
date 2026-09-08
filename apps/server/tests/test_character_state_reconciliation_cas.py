from __future__ import annotations

from queue import Queue
from threading import Event, Lock, Thread
from uuid import UUID

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine, URL

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character_builder.service import CharacterBuilderService
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import (
    CharacterRepository,
    character_states,
)
from test_p1f_character_creation import _seed as _unused_seed  # noqa: F401
from test_p1g_character_versions import (
    _complete_fighter_level_two,
    _confirm_level_one_fighter,
    _start_level_up,
)
from web_room_support import create_web_room_client


def _seed_clients(tmp_path):
    registry = load_default_content_registry()
    engine = create_engine(
        URL.create(
            "sqlite+pysqlite",
            database=str(tmp_path / "reconciliation-cas.sqlite3"),
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

    character_repository = CharacterRepository(engine, registry)
    builder_service = CharacterBuilderService(
        BuilderDraftRepository(engine),
        registry,
        character_repository,
    )
    confirm_client = create_web_room_client(
        engine,
        registry,
        character_repository=character_repository,
        builder_service=builder_service,
    )
    patch_client = create_web_room_client(
        engine,
        registry,
        character_repository=character_repository,
        builder_service=builder_service,
    )
    return confirm_client, patch_client, engine


def _revision(engine: Engine, character_id: str) -> int:
    with engine.connect() as connection:
        value = connection.scalar(
            select(character_states.c.state_revision).where(
                character_states.c.character_id == UUID(character_id)
            )
        )
    assert value is not None
    return int(value)


def _pause_first_reconciliation_state_read(engine: Engine):
    first_read = Event()
    release = Event()
    guard = Lock()
    seen = False

    def listener(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        nonlocal seen
        normalized = statement.lstrip().upper()
        if not normalized.startswith("SELECT") or "STATE_REVISION" not in normalized:
            return
        with guard:
            if seen:
                return
            seen = True
        first_read.set()
        assert release.wait(timeout=5), "controlled reconciliation read was not released"

    event.listen(engine, "after_cursor_execute", listener)
    return first_read, release, listener


def _run_confirm_in_thread(client, draft_id: str):
    results: Queue[object] = Queue()

    def worker() -> None:
        try:
            results.put(
                client.post(
                    f"/api/character-builder/drafts/{draft_id}/confirm"
                )
            )
        except BaseException as exc:  # surfaced in the test thread below
            results.put(exc)

    thread = Thread(target=worker, name="builder-confirm", daemon=True)
    thread.start()
    return thread, results


def _complete_build_edit(client, character_id: str):
    started = client.post(
        f"/api/character-builder/characters/{character_id}/drafts",
        json={"mode": "build_edit"},
    )
    assert started.status_code == 201, started.text
    view = started.json()
    patched = client.patch(
        f"/api/character-builder/drafts/{view['draft']['id']}",
        json={
            "expected_revision": view["draft"]["revision"],
            "draft_payload": {
                "roleplay_profile": {
                    "appearance": "Concurrent build edit",
                    "biography": "",
                }
            },
        },
    )
    assert patched.status_code == 200, patched.text
    return patched.json()


def _assert_confirm_retries_after_concurrent_state_patch(
    tmp_path,
    *,
    prepare_draft,
) -> None:
    confirm_client, patch_client, engine = _seed_clients(tmp_path)
    created = _confirm_level_one_fighter(confirm_client)
    character_id = created["character_id"]
    draft = prepare_draft(confirm_client, character_id)
    before_revision = _revision(engine, character_id)

    first_read, release, listener = _pause_first_reconciliation_state_read(engine)
    thread, results = _run_confirm_in_thread(
        confirm_client,
        draft["draft"]["id"],
    )

    try:
        assert first_read.wait(timeout=5), "Confirm never read State revision"
        patched = patch_client.patch(
            f"/api/characters/{character_id}/state",
            json={"temporary_hp": 7},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["hp"]["temporary"] == 7
        assert _revision(engine, character_id) == before_revision + 1
    finally:
        release.set()
        thread.join(timeout=10)
        event.remove(engine, "after_cursor_execute", listener)

    assert not thread.is_alive()
    result = results.get_nowait()
    if isinstance(result, BaseException):
        raise result
    assert result.status_code == 200, result.text
    assert result.json()["version_no"] == 2

    final = confirm_client.get(f"/api/characters/{character_id}")
    assert final.status_code == 200, final.text
    final_payload = final.json()
    assert final_payload["version_no"] == 2
    assert final_payload["state"]["temporary_hp"] == 7
    assert _revision(engine, character_id) == before_revision + 2

    history = confirm_client.get(f"/api/characters/{character_id}/versions")
    assert history.status_code == 200, history.text
    assert [row["version_no"] for row in history.json()] == [1, 2]

    replay = confirm_client.post(
        f"/api/character-builder/drafts/{draft['draft']['id']}/confirm"
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["version_no"] == 2
    assert _revision(engine, character_id) == before_revision + 2

    engine.dispose()


def test_level_up_reconciliation_retries_after_concurrent_state_patch(tmp_path) -> None:
    def prepare(client, character_id: str):
        return _complete_fighter_level_two(
            client,
            _start_level_up(client, character_id),
        )

    _assert_confirm_retries_after_concurrent_state_patch(
        tmp_path,
        prepare_draft=prepare,
    )


def test_build_edit_reconciliation_retries_after_concurrent_state_patch(tmp_path) -> None:
    _assert_confirm_retries_after_concurrent_state_patch(
        tmp_path,
        prepare_draft=_complete_build_edit,
    )
