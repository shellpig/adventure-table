from __future__ import annotations

from queue import Queue
from threading import Event, Lock, Thread
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Engine

from app.persistence.characters import character_states
from m03g_support import standalone_client
from test_p1g_character_versions import (
    _complete_fighter_level_two,
    _confirm_level_one_fighter,
    _start_level_up,
)


def _revision(engine: Engine, character_id: str) -> int:
    with engine.connect() as connection:
        value = connection.scalar(
            select(character_states.c.state_revision).where(
                character_states.c.character_id == UUID(character_id)
            )
        )
    assert value is not None
    return int(value)


def _enable_wal(engine: Engine) -> None:
    """Let the concurrent PATCH commit while Confirm holds a read snapshot."""

    with engine.connect() as connection:
        mode = connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one()
        connection.commit()
    assert str(mode).lower() == "wal"


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


def _run_confirm_in_thread(client: TestClient, draft_id: str):
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


def _complete_build_edit(client: TestClient, character_id: str):
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
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    prepare_draft,
) -> None:
    with standalone_client(monkeypatch, tmp_path) as (confirm_client, module):
        # Reuse the existing P1-F/P1-G fixture builders against the raw
        # Standalone routes rather than the Web Room adapter.
        confirm_client.builder_api = "/api/character-builder"  # type: ignore[attr-defined]
        confirm_client.character_api = "/api/characters"  # type: ignore[attr-defined]

        created = _confirm_level_one_fighter(confirm_client)
        character_id = created["character_id"]
        draft = prepare_draft(confirm_client, character_id)
        engine = module.app.state.character_engine
        _enable_wal(engine)
        before_revision = _revision(engine, character_id)

        # A second TestClient talks to the exact same Standalone app, engine and
        # SQLite file. It has no Room identity/ACL surface at all.
        with TestClient(module.app) as patch_client:
            first_read, release, listener = _pause_first_reconciliation_state_read(
                engine
            )
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
                assert patched.json()["temporary_hp"] == 7
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


def test_level_up_reconciliation_retries_after_concurrent_state_patch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    def prepare(client: TestClient, character_id: str):
        return _complete_fighter_level_two(
            client,
            _start_level_up(client, character_id),
        )

    _assert_confirm_retries_after_concurrent_state_patch(
        monkeypatch,
        tmp_path,
        prepare_draft=prepare,
    )


def test_build_edit_reconciliation_retries_after_concurrent_state_patch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _assert_confirm_retries_after_concurrent_state_patch(
        monkeypatch,
        tmp_path,
        prepare_draft=_complete_build_edit,
    )
