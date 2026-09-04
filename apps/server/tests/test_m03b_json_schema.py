"""M03-B B.2 — the export document model, exercised against committed fixtures."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.interop.json_schema import CharacterExport


FIXTURES = Path(__file__).resolve().parent / "data" / "m03"
VALID_FIXTURES = sorted(
    path for path in FIXTURES.glob("fixture_*.json") if "_bad_" not in path.name
)
BAD_VERSION_KIND = FIXTURES / "fixture_bad_version_kind.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_m03b_fixture_corpus_is_present() -> None:
    """The M03-C import pipeline is built against these committed payloads."""

    assert {path.name for path in VALID_FIXTURES} == {
        "fixture_low_level_srd.json",
        "fixture_multiclass_mixed.json",
        "fixture_xge_dependent.json",
        "fixture_legacy_no_provenance.json",
    }
    assert BAD_VERSION_KIND.exists()


@pytest.mark.parametrize("path", VALID_FIXTURES, ids=lambda path: path.stem)
def test_m03b_fixture_round_trip_is_idempotent(path: Path) -> None:
    first = CharacterExport.model_validate(_load(path))
    serialized = first.model_dump(mode="json")
    second = CharacterExport.model_validate(serialized)
    assert second.model_dump(mode="json") == serialized
    assert serialized == _load(path)


@pytest.mark.parametrize("path", VALID_FIXTURES, ids=lambda path: path.stem)
def test_m03b_fixture_declares_the_unstable_schema_contract(path: Path) -> None:
    document = CharacterExport.model_validate(_load(path))
    assert document.envelope.schema_version == "unstable"
    assert document.envelope.schema_status == "unstable"
    assert isinstance(document.envelope.source_character_id, UUID)
    assert isinstance(document.envelope.source_export_id, UUID)
    assert document.envelope.exported_at.tzinfo is not None

    versions = document.payload.versions
    assert [version.version_no for version in versions] == list(
        range(1, len(versions) + 1)
    )
    assert document.payload.current_version_no in {
        version.version_no for version in versions
    }
    for version in versions:
        # Present on every version; null only for legacy rows.
        assert version.builder_provenance is None or isinstance(
            version.builder_provenance, dict
        )
        assert isinstance(version.created_at, datetime)


def test_m03b_legacy_fixture_keeps_null_provenance() -> None:
    document = CharacterExport.model_validate(_load(FIXTURES / "fixture_legacy_no_provenance.json"))
    assert all(version.builder_provenance is None for version in document.payload.versions)


def test_m03b_builder_fixtures_carry_provenance_on_every_version() -> None:
    for name in (
        "fixture_low_level_srd.json",
        "fixture_multiclass_mixed.json",
        "fixture_xge_dependent.json",
    ):
        document = CharacterExport.model_validate(_load(FIXTURES / name))
        assert all(
            version.builder_provenance is not None
            for version in document.payload.versions
        ), name


def test_m03b_multiversion_fixture_exposes_chain_relations() -> None:
    document = CharacterExport.model_validate(_load(FIXTURES / "fixture_multiclass_mixed.json"))
    versions = document.payload.versions
    assert len(versions) >= 2
    assert versions[0].parent_version_no is None
    assert versions[1].parent_version_no == 1
    assert all(version.superseded_by_version_no is None for version in versions)


def test_m03b_json_schema_rejects_unknown_version_kind() -> None:
    with pytest.raises(ValidationError):
        CharacterExport.model_validate(_load(BAD_VERSION_KIND))


def test_m03b_json_schema_rejects_a_future_schema_status() -> None:
    payload = _load(FIXTURES / "fixture_low_level_srd.json")
    payload["envelope"]["schema_status"] = "v1"
    with pytest.raises(ValidationError):
        CharacterExport.model_validate(payload)


def test_m03b_json_schema_accepts_the_reserved_locked_status() -> None:
    payload = _load(FIXTURES / "fixture_low_level_srd.json")
    payload["envelope"]["schema_status"] = "locked"
    assert CharacterExport.model_validate(payload).envelope.schema_status == "locked"


def test_m03b_json_schema_rejects_unknown_fields() -> None:
    payload = deepcopy(_load(FIXTURES / "fixture_low_level_srd.json"))
    payload["envelope"]["surprise"] = True
    with pytest.raises(ValidationError):
        CharacterExport.model_validate(payload)


def test_m03b_exported_payload_omits_server_only_columns() -> None:
    for path in VALID_FIXTURES:
        text = json.dumps(_load(path))
        for column in (
            "archived_at",
            "current_version_id",
            "parent_version_id",
            "superseded_by_version_id",
            "updated_at",
        ):
            assert column not in text, f"{path.name} leaks {column}"


def test_m03b_exported_timestamps_are_utc() -> None:
    document = CharacterExport.model_validate(_load(FIXTURES / "fixture_low_level_srd.json"))
    assert document.envelope.exported_at.utcoffset() == timezone.utc.utcoffset(None)
