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
        # FastAPI 0.137+ preserves included routers instead of flattening every
        # child APIRoute into app.routes.  app.openapi() is the supported way to
        # inspect the effective path-operation surface across nested routers.
        api_paths = set(app.openapi()["paths"])

        assert "standalone" in app.title.lower()
        assert app.docs_url is None
        assert app.redoc_url is None
        assert app.openapi_url is None
        assert hasattr(app.state, "content_registry")
        assert all(path.startswith(ALLOWED_API_PREFIXES) for path in api_paths)

        # M03-B/C Character I/O remains reachable through the single composed
        # character router rather than becoming extra standalone-level routers.
        assert "/api/characters/import" in api_paths
        assert "/api/characters/{character_id}/export" in api_paths
        assert TestClient(app).get("/api/meta/capabilities").status_code == 200


def test_standalone_source_contains_no_startup_migration_hook() -> None:
    source = Path(__file__).resolve().parents[1] / "app" / "standalone.py"
    text = source.read_text(encoding="utf-8")

    assert "alembic" not in text
    assert "upgrade(" not in text
