from fastapi.testclient import TestClient

import app.main as main_module
from app.db import database_is_ready

client = TestClient(main_module.app)


def test_readiness_returns_ready_when_database_is_available(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "database_is_ready", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_returns_503_when_database_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "database_is_ready", lambda: False)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "database_unavailable"}}


def test_database_check_fails_closed_for_invalid_connection() -> None:
    assert database_is_ready("postgresql+not-a-real-driver://invalid") is False
