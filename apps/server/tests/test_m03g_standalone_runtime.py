from __future__ import annotations

from pathlib import Path

import pytest

from app import launcher
from m03g_support import standalone_client


def test_standalone_disables_api_documentation_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with standalone_client(monkeypatch, tmp_path) as (standalone, _):
        for path in ("/docs", "/redoc", "/openapi.json"):
            response = standalone.get(path)
            assert response.status_code == 404, (path, response.text)


def test_launcher_keyboard_interrupt_requests_shutdown_and_joins_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "interrupt.sqlite3"
    monkeypatch.setattr(launcher, "_prepare_database_path", lambda: database_path)
    monkeypatch.setattr(launcher, "_prepare_resource_roots", lambda: None)
    monkeypatch.setattr(launcher, "run_migrations", lambda: None)
    monkeypatch.setattr(launcher, "_find_free_port", lambda: 8123)
    monkeypatch.setattr(launcher, "_wait_for_server", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("ADVENTURE_TABLE_NO_BROWSER", "1")

    servers: list[FakeServer] = []
    threads: list[InterruptingThread] = []

    class FakeConfig:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    class FakeServer:
        def __init__(self, _config: FakeConfig) -> None:
            self.started = True
            self.should_exit = False
            servers.append(self)

        def run(self) -> None:
            pass

    class InterruptingThread:
        def __init__(self, *, target, daemon: bool) -> None:
            self.target = target
            self.daemon = daemon
            self._alive = True
            self._interrupted = False
            self.join_timeouts: list[float | None] = []
            threads.append(self)

        def start(self) -> None:
            pass

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout: float | None = None) -> None:
            self.join_timeouts.append(timeout)
            if timeout == 0.5 and not self._interrupted:
                self._interrupted = True
                raise KeyboardInterrupt
            self._alive = False

    monkeypatch.setattr(launcher.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(launcher.uvicorn, "Server", FakeServer)
    monkeypatch.setattr(launcher.threading, "Thread", InterruptingThread)

    assert launcher.main() == 0
    assert len(servers) == 1
    assert len(threads) == 1
    assert servers[0].should_exit is True
    assert threads[0].join_timeouts == [0.5, 10.0]
    assert threads[0].is_alive() is False
