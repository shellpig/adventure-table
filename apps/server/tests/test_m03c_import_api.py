from __future__ import annotations

import json

from m03c_support import document, seeded_import, table_counts


def test_dry_run_returns_200_and_not_committed() -> None:
    client, engine, _ = seeded_import()
    response = client.post(
        "/api/characters/import?dry_run=true",
        content=json.dumps(document()),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["dry_run"] is True
    assert response.json()["committed"] is False
    engine.dispose()


def test_commit_returns_201_and_committed() -> None:
    client, engine, _ = seeded_import()
    response = client.post(
        "/api/characters/import",
        content=json.dumps(document()),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["dry_run"] is False
    assert response.json()["committed"] is True
    engine.dispose()


def test_multipart_is_rejected_before_import_pipeline() -> None:
    client, engine, _ = seeded_import()
    before = table_counts(engine)
    response = client.post(
        "/api/characters/import",
        files={"file": ("character.json", json.dumps(document()), "application/json")},
    )
    assert response.status_code in {400, 415}
    assert table_counts(engine) == before
    engine.dispose()


def test_raw_body_validation_stays_in_import_machine_code_contract() -> None:
    client, engine, _ = seeded_import()
    payload = document()
    payload["envelope"]["schema_status"] = "future"
    response = client.post(
        "/api/characters/import",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_schema_status"
    assert response.json()["error"]["code"] != "validation_failed"
    engine.dispose()


def test_malformed_json_is_400_not_global_422() -> None:
    client, engine, _ = seeded_import()
    response = client.post(
        "/api/characters/import",
        content=b"{bad",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_envelope_shape"
    engine.dispose()


def test_oversized_body_is_413() -> None:
    client, engine, _ = seeded_import()
    response = client.post(
        "/api/characters/import",
        content=b"x" * (5 * 1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    engine.dispose()
