from __future__ import annotations

import json
from pathlib import Path

from app.interop.json_schema import (
    CharacterExportV1,
    LegacyM03CharacterExport,
    normalize_character_export,
    parse_character_export,
)


LEGACY_FIXTURE = Path(__file__).parent / "fixtures" / "character_export_m03_unstable.json"
MULTIPLAYER_FIELDS = {
    "room_id",
    "room_code",
    "campaign_id",
    "session_id",
    "seat_id",
    "room_password",
    "owner_key",
    "dm_key",
    "access_token",
}


def _legacy_payload() -> dict:
    return json.loads(LEGACY_FIXTURE.read_text(encoding="utf-8"))


def test_p2a_legacy_unstable_normalizes_to_locked_v1_without_payload_loss() -> None:
    parsed = parse_character_export(_legacy_payload())
    assert isinstance(parsed, LegacyM03CharacterExport)

    normalized = normalize_character_export(parsed)
    assert isinstance(normalized, CharacterExportV1)
    assert normalized.envelope.schema_version == "1"
    assert normalized.envelope.schema_status == "locked"
    assert normalized.envelope.export_type == "character"
    assert normalized.payload == parsed.payload


def test_p2a_locked_v1_parse_and_normalize_are_idempotent() -> None:
    legacy = parse_character_export(_legacy_payload())
    first = normalize_character_export(legacy)
    serialized = first.model_dump(mode="json")

    parsed = parse_character_export(serialized)
    assert isinstance(parsed, CharacterExportV1)
    second = normalize_character_export(parsed)
    assert second.model_dump(mode="json") == serialized


def test_p2a_character_json_v1_is_room_neutral() -> None:
    document = normalize_character_export(parse_character_export(_legacy_payload()))
    serialized = json.dumps(document.model_dump(mode="json"), sort_keys=True)

    for field in MULTIPLAYER_FIELDS:
        assert f'"{field}"' not in serialized
