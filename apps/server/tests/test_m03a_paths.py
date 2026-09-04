from __future__ import annotations

from pathlib import Path

import pytest

from app import paths


def _clear_path_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ADVENTURE_TABLE_CONTENT_ROOT",
        "ADVENTURE_TABLE_DATABASE_PATH",
        "ADVENTURE_TABLE_SPA_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(paths.settings, "content_root", None)
    monkeypatch.setattr(paths.settings, "database_path", None)
    monkeypatch.setattr(paths.settings, "spa_root", None)
    monkeypatch.setattr(paths, "_launcher_mode", False)
    monkeypatch.delattr(paths.sys, "frozen", raising=False)
    monkeypatch.delattr(paths.sys, "_MEIPASS", raising=False)


def test_content_root_environment_override_has_highest_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_path_env(monkeypatch)
    configured = tmp_path / "custom-data"
    configured.mkdir()
    executable = tmp_path / "app" / "adventure-table.exe"
    (executable.parent / "data").mkdir(parents=True)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(executable))
    monkeypatch.setenv("ADVENTURE_TABLE_CONTENT_ROOT", str(configured))

    assert paths.resolve_content_root() == configured.resolve()


def test_invalid_configured_content_root_fails_with_stage_and_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_path_env(monkeypatch)
    missing = tmp_path / "missing-data"
    monkeypatch.setenv("ADVENTURE_TABLE_CONTENT_ROOT", str(missing))

    with pytest.raises(RuntimeError, match=r"\[env\].*missing-data"):
        paths.resolve_content_root()


def test_frozen_content_root_prefers_executable_sibling_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_path_env(monkeypatch)
    executable = tmp_path / "dist" / "adventure-table.exe"
    data = executable.parent / "data"
    data.mkdir(parents=True)
    meipass = tmp_path / "bundle"
    (meipass / "data").mkdir(parents=True)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(executable))
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(meipass), raising=False)

    assert paths.resolve_content_root() == data.resolve()


def test_frozen_content_root_falls_back_to_meipass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_path_env(monkeypatch)
    executable = tmp_path / "dist" / "adventure-table.exe"
    executable.parent.mkdir(parents=True)
    meipass = tmp_path / "bundle"
    fallback = meipass / "data"
    fallback.mkdir(parents=True)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(executable))
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(meipass), raising=False)

    assert paths.resolve_content_root() == fallback.resolve()


def test_frozen_missing_content_root_never_falls_back_to_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_path_env(monkeypatch)
    executable = tmp_path / "dist" / "adventure-table.exe"
    executable.parent.mkdir(parents=True)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(executable))

    with pytest.raises(RuntimeError, match=r"\[frozen\].*data"):
        paths.resolve_content_root()


def test_repository_content_root_and_child_resolvers_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_path_env(monkeypatch)

    content_root = paths.resolve_content_root()
    assert content_root.name == "data"
    assert content_root.is_dir()
    assert paths.resolve_srd_content_root() == content_root / "srd5.1"
    assert paths.resolve_rules_path() == (
        content_root / "rules" / "dnd5e-2014" / "character-builder.json"
    )
    assert paths.resolve_rules_root() == content_root / "rules" / "dnd5e-2014"
    assert paths.resolve_localization_root() == content_root / "localization"


def test_database_path_resolution_order_and_web_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_path_env(monkeypatch)
    configured = tmp_path / "db" / "custom.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(configured))
    assert paths.resolve_database_path() == configured.resolve()
    assert paths.resolve_database_url() == f"sqlite+pysqlite:///{configured.resolve().as_posix()}"

    monkeypatch.delenv("ADVENTURE_TABLE_DATABASE_PATH")
    executable = tmp_path / "dist" / "adventure-table.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(executable))
    assert paths.resolve_database_path() == (
        executable.parent / paths.STANDALONE_DB_FILENAME
    ).resolve()

    monkeypatch.delattr(paths.sys, "frozen", raising=False)
    monkeypatch.setattr(paths, "_launcher_mode", False)
    assert paths.resolve_database_path() is None
    assert paths.resolve_database_url() == paths.settings.database_url


def test_launcher_mode_uses_current_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_path_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    paths.mark_launcher_mode()

    assert paths.resolve_database_path() == (tmp_path / paths.STANDALONE_DB_FILENAME).resolve()


def test_spa_root_supports_environment_and_frozen_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_path_env(monkeypatch)
    configured = tmp_path / "configured-web"
    configured.mkdir()
    monkeypatch.setenv("ADVENTURE_TABLE_SPA_ROOT", str(configured))
    assert paths.resolve_spa_root() == configured.resolve()

    monkeypatch.delenv("ADVENTURE_TABLE_SPA_ROOT")
    executable = tmp_path / "dist" / "adventure-table.exe"
    web = executable.parent / "web"
    web.mkdir(parents=True)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "executable", str(executable))
    assert paths.resolve_spa_root() == web.resolve()
