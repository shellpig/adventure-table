from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from tests.m03e_support import loaded_standalone


ALLOWED_API_PREFIXES = (
    "/api/rules/content",
    "/api/rules/presentation",
    "/api/characters",
    "/api/character-builder",
    "/api/meta",
)


def test_standalone_exposes_only_character_distribution_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        app = standalone.app
        paths = {
            route.path
            for route in app.routes
            if hasattr(route, "path")
        }

        assert "standalone" in app.title.lower()
        assert app.docs_url is None
        assert app.redoc_url is None
        assert app.openapi_url is None
        assert hasattr(app.state, "content_registry")
        assert "/docs" not in paths
        assert "/redoc" not in paths
        assert "/openapi.json" not in paths
        assert all(
            not path.startswith("/api/")
            or path.startswith(ALLOWED_API_PREFIXES)
            for path in paths
        )

        client = TestClient(app)
        # M03-B/C Character I/O remains reachable through the single composed
        # character router rather than becoming extra standalone-level routers.
        assert any(path == "/api/characters/import" for path in paths)
        assert any(path == "/api/characters/{character_id}/export" for path in paths)
        assert client.get("/api/meta/capabilities").status_code == 200


def test_standalone_source_contains_no_startup_migration_hook() -> None:
    source = Path(__file__).resolve().parents[1] / "app" / "standalone.py"
    text = source.read_text(encoding="utf-8")

    assert "alembic" not in text
    assert "upgrade(" not in text
