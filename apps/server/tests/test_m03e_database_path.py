from __future__ import annotations

from pathlib import Path

import pytest

from app import db, paths
from app import launcher
from tests.m03e_support import loaded_standalone


def _reset_database_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADVENTURE_TABLE_DATABASE_PATH", raising=False)
    monkeypatch.setattr(paths.settings, "database_path", None)
    monkeypatch.setattr(paths, "_launcher_mode", False)
    monkeypatch.delattr(paths.sys, "frozen", raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)


def test_database_path_resolution_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_database_resolution(monkeypatch)
    settings_path = tmp_path / "settings.sqlite3"
    env_path = tmp_path / "env.sqlite3"
    monkeypatch.setattr(paths.settings, "database_path", str(settings_path))
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(env_path))
    assert paths.resolve_database_path() == env_path.resolve()
    assert paths.resolve_database_url().startswith("sqlite+pysqlite://")

    monkeypatch.delenv("ADVENTURE_TABLE_DATABASE_PATH")
    assert paths.resolve_database_path() == settings_path.resolve()

    monkeypatch.setattr(paths.settings, "database_path", None)
    executable = tmp_path / "dist" / "adventure-table.exe"
    executable.parent.mkdir(parents=True)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(executable))
    assert paths.resolve_database_path() == (
        executable.parent / paths.STANDALONE_DB_FILENAME
    ).resolve()

    monkeypatch.delattr(paths.sys, "frozen", raising=False)
    monkeypatch.chdir(tmp_path)
    paths.mark_launcher_mode()
    assert paths.resolve_database_path() == (
        tmp_path / paths.STANDALONE_DB_FILENAME
    ).resolve()
    assert paths.resolve_database_url().startswith("sqlite+pysqlite://")


def test_web_database_resolution_still_falls_back_to_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_database_resolution(monkeypatch)

    assert paths.resolve_database_path() is None
    assert paths.resolve_database_url() == paths.settings.database_url


def test_standalone_guard_rejects_postgres_before_connection_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        monkeypatch.setattr(
            standalone,
            "resolve_database_url",
            lambda: "postgresql+psycopg://example.invalid/adventure",
        )
        with pytest.raises(
            RuntimeError,
            match=r"postgresql\+psycopg.*ADVENTURE_TABLE_DATABASE_PATH",
        ):
            standalone.create_standalone_app()


def test_shared_engine_factory_defaults_to_database_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db, "resolve_database_url", lambda: "sqlite+pysqlite:///:memory:")

    engine = db.create_database_engine()
    try:
        assert str(engine.url) == "sqlite+pysqlite:///:memory:"
    finally:
        engine.dispose()


def test_launcher_banner_prints_real_absolute_database_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "adventure-table.sqlite3"
    content_root = tmp_path / "data"
    content_root.mkdir()

    launcher._print_banner(8042, database_path, content_root, None)
    output = capsys.readouterr().out

    assert str(database_path.resolve()) in output
    assert str(content_root.resolve()) in output
    assert "<settings>" not in output
    assert "127.0.0.1:8042" in output
