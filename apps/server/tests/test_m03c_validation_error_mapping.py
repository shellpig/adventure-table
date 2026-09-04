from __future__ import annotations

from app.api.character_import import map_validation_error
from app.interop.json_schema import CharacterExport
from pydantic import ValidationError
from m03c_support import document


def _error_for(mutator) -> ValidationError:
    payload = document()
    mutator(payload)
    try:
        CharacterExport.model_validate(payload)
    except ValidationError as exc:
        return exc
    raise AssertionError("fixture mutation did not produce ValidationError")


def test_schema_status_maps_to_unsupported_schema_status() -> None:
    exc = _error_for(lambda p: p["envelope"].__setitem__("schema_status", "future"))
    assert map_validation_error(exc) == "unsupported_schema_status"


def test_version_kind_maps_to_invalid_version_kind() -> None:
    exc = _error_for(
        lambda p: p["payload"]["versions"][0].__setitem__("version_kind", "future")
    )
    assert map_validation_error(exc) == "invalid_version_kind"


def test_schema_version_maps_to_invalid_envelope_shape() -> None:
    exc = _error_for(lambda p: p["envelope"].__setitem__("schema_version", "future"))
    assert map_validation_error(exc) == "invalid_envelope_shape"


def test_other_envelope_error_maps_to_invalid_envelope_shape() -> None:
    exc = _error_for(lambda p: p["envelope"].pop("ruleset"))
    assert map_validation_error(exc) == "invalid_envelope_shape"


def test_other_payload_error_maps_to_invalid_payload_shape() -> None:
    exc = _error_for(lambda p: p["payload"]["character"].pop("name"))
    assert map_validation_error(exc) == "invalid_payload_shape"


def test_special_case_wins_over_generic_payload_error() -> None:
    def mutate(payload):
        payload["payload"]["versions"][0]["version_kind"] = "future"
        payload["payload"]["character"].pop("name")

    assert map_validation_error(_error_for(mutate)) == "invalid_version_kind"


def test_multiple_special_cases_are_deterministic_by_location() -> None:
    def mutate(payload):
        payload["envelope"]["schema_status"] = "future"
        payload["payload"]["versions"][0]["version_kind"] = "future"

    exc = _error_for(mutate)
    expected = "unsupported_schema_status"
    assert map_validation_error(exc) == expected
    assert map_validation_error(exc) == expected
