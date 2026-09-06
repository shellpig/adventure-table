from __future__ import annotations

from pathlib import Path

from app.api.character_import import _parse_document


FIXTURE = Path(__file__).parent / "fixtures" / "character_export_m03_unstable.json"


def test_p2a_freezes_real_m03_unstable_export_before_v1_lock() -> None:
    raw = FIXTURE.read_bytes()
    document = _parse_document(raw)

    assert document.envelope.schema_version == "unstable"
    assert document.envelope.schema_status == "unstable"
    assert document.envelope.content_requirements
    assert len(document.payload.versions) >= 2
    assert all(version.builder_provenance is not None for version in document.payload.versions)
    assert document.payload.current_state.state_payload["inventory_state"]
    assert document.payload.current_state.state_payload["spell_slots"]
    assert any(
        requirement.pack != "srd5.1"
        for requirement in document.envelope.content_requirements
    )
