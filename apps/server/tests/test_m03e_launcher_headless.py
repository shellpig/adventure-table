from __future__ import annotations

import importlib
import json
from pathlib import Path
import sqlite3
import sys
import threading
from urllib.request import urlopen

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
import uvicorn

from app import launcher, paths


def _clear_launcher_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ADVENTURE_TABLE_DATABASE_PATH",
        "ADVENTURE_TABLE_CONTENT_ROOT",
        "ADVENTURE_TABLE_SPA_ROOT",
        "ADVENTURE_TABLE_NO_BROWSER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(paths.settings, "database_path", None)
    monkeypatch.setattr(paths.settings, "content_root", None)
    monkeypatch.setattr(paths.settings, "spa_root", None)
    monkeypatch.setattr(paths, "_launcher_mode", False)
    monkeypatch.delattr(paths.sys, "frozen", raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)


def test_run_migrations_upgrades_tmp_sqlite_to_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_launcher_env(monkeypatch)
    database_path = tmp_path / "m03e.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(database_path))

    launcher.run_migrations()

    config_path = launcher._alembic_config_path()
    config = Config(str(config_path))
    config.set_main_option("script_location", str(config_path.parent))
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    with sqlite3.connect(database_path) as connection:
        actual_head = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
    assert actual_head == expected_head


def test_launcher_sets_default_database_path_before_migration_and_opens_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_launcher_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    observed: dict[str, str] = {}

    def fake_migrations() -> None:
        observed["database_url"] = paths.resolve_database_url()

    class FakeServer:
        def __init__(self, _config: uvicorn.Config) -> None:
            self.started = False
            self.should_exit = False

        def run(self) -> None:
            self.started = True

    def fake_browser(url: str) -> bool:
        observed["browser_url"] = url
        return True

    monkeypatch.setattr(launcher, "run_migrations", fake_migrations)
    monkeypatch.setattr(launcher.uvicorn, "Server", FakeServer)
    monkeypatch.setattr(launcher, "open_browser", fake_browser)

    assert launcher.main() == 0

    expected = (tmp_path / paths.STANDALONE_DB_FILENAME).resolve()
    assert expected.is_file()
    assert observed["database_url"] == f"sqlite+pysqlite:///{expected.as_posix()}"
    assert observed["database_url"].startswith("sqlite+pysqlite://")
    assert observed["browser_url"].startswith("http://127.0.0.1:")


def test_standalone_http_smoke_after_launcher_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_launcher_env(monkeypatch)
    database_path = tmp_path / "http-smoke.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(database_path))
    launcher.run_migrations()

    sys.modules.pop("app.standalone", None)
    importlib.invalidate_caches()
    port = launcher._find_free_port()
    config = uvicorn.Config(
        "app.standalone:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        launcher._wait_for_server(server, thread, timeout=10.0)
        with urlopen(f"http://127.0.0.1:{port}/api/meta/capabilities", timeout=3) as response:
            capabilities = json.loads(response.read())
        with urlopen(f"http://127.0.0.1:{port}/api/characters", timeout=3) as response:
            characters = json.loads(response.read())

        assert capabilities["channel"] == "standalone"
        assert capabilities["capabilities"]["room"] is False
        assert characters == []
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)
        sys.modules.pop("app.standalone", None)

    assert not thread.is_alive()
