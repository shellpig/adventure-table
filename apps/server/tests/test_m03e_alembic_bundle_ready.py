from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest

from app import launcher, paths


def _character_head(config: Config) -> str:
    scripts = ScriptDirectory.from_config(config)
    candidates = []
    for head in scripts.get_heads():
        revision = scripts.get_revision(head)
        if revision is not None and "character" in revision.branch_labels:
            candidates.append(head)
    assert len(candidates) == 1, candidates
    return candidates[0]


def test_frozen_alembic_resources_run_from_meipass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_root = Path(__file__).resolve().parents[1]
    bundle_root = tmp_path / "_internal"
    bundled_alembic = bundle_root / "alembic"
    shutil.copytree(server_root / "alembic", bundled_alembic)
    shutil.copy2(server_root / "alembic.ini", bundled_alembic / "alembic.ini")

    database_path = tmp_path / "frozen.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(database_path))
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher.sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(bundle_root), raising=False)

    launcher.run_migrations()

    config = Config(str(bundled_alembic / "alembic.ini"))
    config.set_main_option("script_location", str(bundled_alembic))
    expected_head = _character_head(config)
    with sqlite3.connect(database_path) as connection:
        actual_head = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert actual_head == expected_head
    assert "rooms" not in tables
    assert "room_access_sessions" not in tables
