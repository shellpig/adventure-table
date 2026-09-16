"""P4-D closeout evidence the unit / repository suites do not cover.

D.4: every 2014 condition the combat rules layer knows has a content registry
entry and a zh-TW name.  D.0: the new shared Character State fields survive a
Web -> Standalone -> Web export / import roundtrip.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select, update

from app.content import load_default_content_registry
from app.domain.character.schemas import CharacterState
from app.persistence.characters import character_states
from app.content.localization_files import load_content_localization_catalog
from app.domain.combat.effect_resolver import Condition, condition_to_state
from app.paths import resolve_content_root
from m03c_support import post_document, seeded_import
from m03g_support import commit_fixture, export_character, standalone_client


def test_p4d_d4_every_condition_has_registry_entry_and_zh_tw_name() -> None:
    registry = load_default_content_registry()
    catalog = load_content_localization_catalog(registry, resolve_content_root())
    for condition in Condition:
        key = condition_to_state(condition).condition_ref
        assert registry.get_optional(key) is not None, key
        localized = catalog.resolve_name(key, "zh-TW")
        assert localized.fallback_used is False, key
        assert str(localized.value).strip(), key
    exhaustion = "srd5.1:condition:exhaustion"
    assert registry.get_optional(exhaustion) is not None
    assert catalog.resolve_name(exhaustion, "zh-TW").fallback_used is False


def test_p4d_d0_new_state_fields_survive_web_standalone_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_client, web_engine, _ = seeded_import()
    web_character_id = commit_fixture(web_client, "fixture_multiclass_mixed.json")
    new_state = {
        "concentration": {"source_ref": "srd5.1:spell:bless", "effect_ids": ["bless:1"]},
        "exhaustion_level": 2,
        "death_saves": {"successes": 1, "failures": 0, "stable": False, "dead": False},
        "temporary_effects": [
            {
                "effect_id": "bless:1",
                "source_ref": "srd5.1:spell:bless",
                "tag": "bless",
                "duration": "concentration",
                "modifiers": [{"scope": "save", "mode": "bonus", "value": 1, "target": None}],
                "note": None,
            }
        ],
        "conditions": [
            {"condition_ref": "srd5.1:condition:poisoned", "note": None, "effect_id": "poison:1"}
        ],
    }
    # The manual state PATCH DTO does not expose these fields (P4-E surface);
    # write them the way the combat repositories do, under the revision CAS.
    with web_engine.begin() as connection:
        row = connection.execute(
            select(character_states.c.state_payload, character_states.c.state_revision).where(
                character_states.c.character_id == UUID(web_character_id)
            )
        ).mappings().one()
        payload = {**row["state_payload"], **new_state}
        result = connection.execute(
            update(character_states)
            .where(
                character_states.c.character_id == UUID(web_character_id),
                character_states.c.state_revision == int(row["state_revision"]),
            )
            .values(
                state_payload=CharacterState.model_validate(payload).model_dump(mode="json"),
                state_revision=int(row["state_revision"]) + 1,
            )
        )
        assert result.rowcount == 1

    web_export = export_character(web_client, web_character_id)
    exported = web_export["payload"]["current_state"]["state_payload"]
    for field, value in new_state.items():
        assert exported[field] == value, field
    assert web_export["envelope"]["schema_version"] == "1"
    web_engine.dispose()

    with standalone_client(monkeypatch, tmp_path) as (standalone, _):
        committed = post_document(standalone, web_export)
        assert committed.status_code == 201, committed.text
        standalone_export = export_character(standalone, committed.json()["character_id"])
        assert standalone_export["payload"] == web_export["payload"]

    round_web_client, round_web_engine, _ = seeded_import()
    try:
        reimported = post_document(round_web_client, standalone_export)
        assert reimported.status_code == 201, reimported.text
        final = export_character(round_web_client, reimported.json()["character_id"])
        assert final["payload"]["current_state"]["state_payload"] == exported
    finally:
        round_web_engine.dispose()
