from __future__ import annotations

import json
from pathlib import Path

from app.api.character_import import _parse_document
from app.interop.json_schema import LegacyM03CharacterExport, parse_character_export


FIXTURE = Path(__file__).parent / "fixtures" / "character_export_m03_unstable.json"


def test_p2a_freezes_real_m03_unstable_export_before_v1_lock() -> None:
    raw = FIXTURE.read_bytes()
    source = json.loads(raw)
    legacy = parse_character_export(source)

    assert isinstance(legacy, LegacyM03CharacterExport)
    assert source["envelope"]["schema_version"] == "unstable"
    assert source["envelope"]["schema_status"] == "unstable"
    assert legacy.envelope.content_requirements
    assert len(legacy.payload.versions) >= 2
    assert all(version.builder_provenance is not None for version in legacy.payload.versions)
    assert legacy.payload.current_state.state_payload["inventory_state"]
    assert legacy.payload.current_state.state_payload["spell_slots"]
    assert any(
        requirement.pack != "srd5.1"
        for requirement in legacy.envelope.content_requirements
    )

    normalized = _parse_document(raw)
    assert normalized.envelope.schema_version == "1"
    assert normalized.envelope.schema_status == "locked"
    assert normalized.envelope.export_type == "character"
