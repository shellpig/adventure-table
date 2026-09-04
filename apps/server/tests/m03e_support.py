from __future__ import annotations

from contextlib import contextmanager
import importlib
from pathlib import Path
import sys
from types import ModuleType
from typing import Iterator

import pytest


@contextmanager
def loaded_standalone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[ModuleType]:
    """Import app.standalone only after its SQLite and SPA environment is ready."""

    db_path = tmp_path / "adventure-table.sqlite3"
    spa_root = tmp_path / "web"
    assets = spa_root / "assets"
    assets.mkdir(parents=True)
    (spa_root / "index.html").write_text("<html><body>M03-E SPA</body></html>", encoding="utf-8")
    (assets / "some.css").write_text("body { display: block; }", encoding="utf-8")

    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("ADVENTURE_TABLE_SPA_ROOT", str(spa_root))
    sys.modules.pop("app.standalone", None)
    module = importlib.import_module("app.standalone")
    try:
        yield module
    finally:
        sys.modules.pop("app.standalone", None)
