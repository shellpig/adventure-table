from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.api.dependencies as dependencies


def _request() -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


def test_database_dependency_uses_shared_engine_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    calls: list[None] = []
    engine = object()

    def fake_create_database_engine() -> object:
        calls.append(None)
        return engine

    monkeypatch.setattr(
        dependencies,
        "create_database_engine",
        fake_create_database_engine,
    )

    assert dependencies.get_database_engine(request) is engine
    assert dependencies.get_database_engine(request) is engine
    assert calls == [None]


def test_localization_dependency_uses_resolved_content_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    registry = object()
    catalog = object()
    calls: list[tuple[object, Path]] = []
    content_root = tmp_path / "data"
    content_root.mkdir()

    monkeypatch.setattr(dependencies, "resolve_content_root", lambda: content_root)
    monkeypatch.setattr(dependencies, "get_content_registry", lambda request: registry)

    def fake_load(current_registry: object, root: Path) -> object:
        calls.append((current_registry, root))
        return catalog

    monkeypatch.setattr(dependencies, "load_content_localization_catalog", fake_load)

    assert dependencies.get_content_localization(request) is catalog
    assert dependencies.get_content_localization(request) is catalog
    assert calls == [(registry, content_root)]
