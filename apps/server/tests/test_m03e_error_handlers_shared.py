from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.error_handlers import register_exception_handlers
from app.persistence.characters import CharacterNotFoundError


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_shared_error_handlers_preserve_character_not_found_contract() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/missing")
    def missing() -> None:
        raise CharacterNotFoundError("demo")

    response = TestClient(app).get("/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "character_not_found"


def test_web_and_standalone_use_shared_registration_without_importing_each_other() -> None:
    main_source = (REPO_ROOT / "apps/server/app/main.py").read_text(encoding="utf-8")
    standalone_source = (REPO_ROOT / "apps/server/app/standalone.py").read_text(encoding="utf-8")

    assert "register_exception_handlers(app)" in main_source
    assert "register_exception_handlers(app)" in standalone_source
    assert "from app.main" not in standalone_source
    assert "import app.main" not in standalone_source
