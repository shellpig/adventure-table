from __future__ import annotations

import copy

import pytest

from m03c_support import document, post_document, seeded_import, table_counts


def _second_version(payload: dict) -> dict:
    second = copy.deepcopy(payload["payload"]["versions"][0])
    second["version_no"] = 2
    second["version_kind"] = "build_edit"
    second["parent_version_no"] = 1
    second["superseded_by_version_no"] = None
    return second


def _rejection_payload(case: str) -> tuple[dict, str | None]:
    payload = document()
    disabled_pack = None

    if case == "invalid_envelope_shape":
        del payload["envelope"]["ruleset"]
    elif case == "invalid_payload_shape":
        del payload["payload"]["character"]["name"]
    elif case == "unsupported_schema_status":
        payload["envelope"]["schema_status"] = "future_value"
    elif case == "unsupported_ruleset":
        payload["envelope"]["ruleset"] = "pathfinder2e"
    elif case == "ruleset_mismatch":
        payload = document("fixture_bad_ruleset_mismatch.json")
    elif case == "version_chain_gap":
        second = _second_version(payload)
        second["version_no"] = 3
        payload["payload"]["versions"].append(second)
        payload["payload"]["current_version_no"] = 3
    elif case == "version_chain_out_of_order":
        second = _second_version(payload)
        payload["payload"]["versions"] = [second, payload["payload"]["versions"][0]]
        payload["payload"]["current_version_no"] = 2
    elif case == "current_state_version_missing":
        payload["payload"]["current_version_no"] = 99
    elif case == "version_lineage_invalid":
        payload["payload"]["versions"][0]["parent_version_no"] = 99
    elif case == "version_lineage_self_reference":
        payload["payload"]["versions"][0]["parent_version_no"] = 1
    elif case == "version_lineage_direction_invalid":
        second = _second_version(payload)
        payload["payload"]["versions"][0]["parent_version_no"] = 2
        payload["payload"]["versions"] = [payload["payload"]["versions"][0], second]
        payload["payload"]["current_version_no"] = 2
        second["parent_version_no"] = None
    elif case == "version_lineage_cycle":
        payload = document("fixture_bad_lineage_cycle.json")
    elif case == "invalid_version_kind":
        payload = document("fixture_bad_version_kind.json")
    elif case == "invalid_build_shape":
        payload["payload"]["versions"][0]["build_payload"]["class_progression"] = [
            "srd5.1:race:human"
        ]
    elif case == "invalid_builder_provenance":
        payload = document("fixture_bad_builder_provenance.json")
    elif case == "state_shape_invalid":
        payload["payload"]["current_state"]["state_payload"]["conditions"] = [
            {"condition_ref": "srd5.1:spell:acid-arrow"}
        ]
    elif case == "build_references_invalid":
        payload["payload"]["versions"][0]["build_payload"]["numeric_overrides"] = [
            {"key": "not-a-supported-override", "value": 10}
        ]
    elif case == "state_inconsistent_with_build":
        payload["payload"]["current_state"]["state_payload"]["current_hp"] = 999
    elif case == "draft_reconstruction_unavailable":
        payload = document("fixture_legacy_no_provenance.json")
        payload["payload"]["versions"][0]["build_payload"]["race_ref"] = (
            "xge:race:portable-test-race"
        )
        disabled_pack = "xge"
    else:
        raise AssertionError(case)
    return payload, disabled_pack


@pytest.mark.parametrize(
    "code",
    [
        "invalid_envelope_shape",
        "invalid_payload_shape",
        "unsupported_schema_status",
        "unsupported_ruleset",
        "ruleset_mismatch",
        "version_chain_gap",
        "version_chain_out_of_order",
        "current_state_version_missing",
        "version_lineage_invalid",
        "version_lineage_self_reference",
        "version_lineage_direction_invalid",
        "version_lineage_cycle",
        "invalid_version_kind",
        "invalid_build_shape",
        "invalid_builder_provenance",
        "state_shape_invalid",
        "build_references_invalid",
        "state_inconsistent_with_build",
        "draft_reconstruction_unavailable",
    ],
)
def test_import_rejection_code_is_atomic(code: str) -> None:
    payload, disabled_pack = _rejection_payload(code)
    client, engine, _ = seeded_import(disabled_pack=disabled_pack)
    before = table_counts(engine)
    response = post_document(client, payload)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == code
    assert table_counts(engine) == before
    engine.dispose()


def test_malformed_json_is_invalid_envelope_and_atomic() -> None:
    client, engine, _ = seeded_import()
    before = table_counts(engine)
    response = client.post(
        "/api/characters/import",
        content=b'{"envelope":',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_envelope_shape"
    assert table_counts(engine) == before
    engine.dispose()


def test_payload_too_large_is_413_with_params_and_atomic() -> None:
    client, engine, _ = seeded_import()
    before = table_counts(engine)
    response = client.post(
        "/api/characters/import",
        content=b"x" * (5 * 1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.json()["error"]["params"]["max_bytes"] == 5 * 1024 * 1024
    assert table_counts(engine) == before
    engine.dispose()
