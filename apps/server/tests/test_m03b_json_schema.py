from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.interop.json_schema import CharacterExport


BASE_EXPORT = {
    "envelope": {
        "schema_version": "unstable",
        "schema_status": "unstable",
        "ruleset": "dnd5e-2014",
        "content_requirements": [{"pack": "srd5.1", "version": "1.0.0"}],
        "stable_key_refs_summary": 3,
        "source_character_id": "11111111-1111-4111-8111-111111111111",
        "source_export_id": "22222222-2222-4222-8222-222222222222",
        "source_app": {"channel": "web", "commit": "abc123"},
        "exported_at": "2026-09-04T00:00:00Z",
    },
    "payload": {
        "character": {"name": "Schema Fighter", "ruleset": "dnd5e-2014"},
        "current_version_no": 1,
        "versions": [
            {
                "version_no": 1,
                "version_kind": "create",
                "parent_version_no": None,
                "superseded_by_version_no": None,
                "change_note": None,
                "build_payload": {"fixture": True},
                "builder_provenance": {"fixture": True},
                "created_at": "2026-09-04T00:00:00Z",
            }
        ],
        "current_state": {"state_payload": {"current_hp": 10}},
    },
}


def test_m03b_json_schema_accepts_current_unstable_envelope() -> None:
    document = CharacterExport.model_validate(BASE_EXPORT)
    assert document.envelope.schema_version == "unstable"
    assert document.envelope.schema_status == "unstable"
    assert document.envelope.source_character_id == UUID(BASE_EXPORT["envelope"]["source_character_id"])
    assert document.envelope.exported_at == datetime(2026, 9, 4, tzinfo=timezone.utc)
    assert document.payload.versions[0].version_kind == "create"


def test_m03b_json_schema_rejects_unknown_version_kind() -> None:
    payload = deepcopy(BASE_EXPORT)
    payload["payload"]["versions"][0]["version_kind"] = "future_kind"
    with pytest.raises(ValidationError):
        CharacterExport.model_validate(payload)


def test_m03b_json_schema_rejects_unknown_fields() -> None:
    payload = deepcopy(BASE_EXPORT)
    payload["envelope"]["surprise"] = True
    with pytest.raises(ValidationError):
        CharacterExport.model_validate(payload)
