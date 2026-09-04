"""Generate the committed M03-B export fixtures from the real export endpoint.

The M03 test guide (§2.2) requires these files to be produced by
``GET /api/characters/{id}/export`` and committed, so M03-C can validate its
import pipeline against payloads the server actually emits rather than
hand-written approximations.

Everything except four volatile envelope/version fields is verbatim endpoint
output. ``source_character_id``, ``source_export_id``, ``exported_at`` and each
version's ``created_at`` are replaced with fixed placeholders so the committed
files are stable and their diffs are reviewable; they keep their real shape and
still satisfy the schema.

Usage:
    python tests/generate_m03b_fixtures.py           # write the fixtures
    python tests/generate_m03b_fixtures.py --check   # fail if committed drift
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any
from uuid import UUID

import m01k_support as S
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)


OUTPUT = Path(__file__).resolve().parent / "data" / "m03"

PLACEHOLDER_CHARACTER_ID = "00000000-0000-4000-8000-00000000c0de"
PLACEHOLDER_EXPORT_ID = "00000000-0000-4000-8000-0000000e6b07"
PLACEHOLDER_TIMESTAMP = "2026-09-04T00:00:00Z"

STANDARD_ARRAY = {
    "strength": 15,
    "dexterity": 14,
    "constitution": 13,
    "intelligence": 12,
    "wisdom": 10,
    "charisma": 8,
}

# Fighter needs STR/DEX 13+, Cleric needs WIS 13+ to multiclass into.
MULTICLASS_ARRAY = {
    "strength": 15,
    "dexterity": 12,
    "constitution": 14,
    "intelligence": 8,
    "wisdom": 13,
    "charisma": 10,
}


def _level(
    character_level: int,
    class_ref: str,
    *,
    hp: int,
    subclass_ref: str | None = None,
) -> dict[str, Any]:
    return {
        "character_level": character_level,
        "class_ref": class_ref,
        "hp_method": "first_level" if character_level == 1 else "fixed_average",
        "hp_base_gain": hp,
        "subclass_ref": subclass_ref,
    }


def _draft_payload(
    *,
    name: str,
    race: str,
    background: str,
    levels: list[dict[str, Any]],
    abilities: dict[str, int] | None = None,
    subrace: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "basic": {"name": name, "ruleset": "dnd5e-2014"},
        "target_level": len(levels),
        "race_selection": {"reference_id": race},
        "background_selection": {"reference_id": background},
        "ability_generation": {
            "method": "standard_array",
            "scores": dict(abilities or STANDARD_ARRAY),
            "provenance": "m03b-fixture",
        },
        "level_choices": levels,
    }
    if subrace is not None:
        payload["subrace_selection"] = {"reference_id": subrace}
    return payload


def _fill_spells(client, view: dict[str, Any]) -> dict[str, Any]:
    """Take the first legal cantrips/known spells each profile offers."""

    response = client.get(
        f"/api/character-builder/drafts/{view['draft']['id']}/review"
    )
    assert response.status_code == 200, response.text
    profiles = response.json()["resolved_summary"]["spellcasting_profiles"]
    if not profiles:
        return view

    plan: dict[str, Any] = {}
    for profile in profiles:
        cantrips = [
            option["spell_key"]
            for option in profile["available_spells"]
            if option["level"] == 0
        ][: profile["cantrip_count"]]
        leveled = [
            option["spell_key"]
            for option in profile["available_spells"]
            if option["level"] >= 1 and option["spell_key"] not in set(cantrips)
        ]
        plan[profile["profile_id"]] = {
            "cantrip_keys": cantrips,
            "known_spell_keys": leveled[: profile["known_spell_count"]],
            "spellbook_spell_keys": leveled[: profile["spellbook_count"]],
        }
    return S.http_patch(client, view, {"spell_choices": plan})


def _ready(client, view: dict[str, Any]) -> dict[str, Any]:
    view = S.http_fill_generic(client, view)
    view = _fill_spells(client, view)
    return S.http_fill_equipment(client, view)


def _confirm_create(client, payload: dict[str, Any]) -> str:
    view = _ready(client, S.http_create_draft(client, payload))
    return S.http_confirm(client, view)["character_id"]


def _export(client, character_id: str) -> dict[str, Any]:
    response = client.get(f"/api/characters/{character_id}/export")
    assert response.status_code == 200, response.text
    return response.json()


def _canonicalize(document: dict[str, Any]) -> dict[str, Any]:
    document = deepcopy(document)
    document["envelope"]["source_character_id"] = PLACEHOLDER_CHARACTER_ID
    document["envelope"]["source_export_id"] = PLACEHOLDER_EXPORT_ID
    document["envelope"]["exported_at"] = PLACEHOLDER_TIMESTAMP
    for version in document["payload"]["versions"]:
        version["created_at"] = PLACEHOLDER_TIMESTAMP
    return document


def _serialize(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def build_fixtures() -> dict[str, dict[str, Any]]:
    client, engine = S.seed_http()
    try:
        fixtures: dict[str, dict[str, Any]] = {}

        # Lv1 Fighter, srd5.1 only.
        low_level = _confirm_create(
            client,
            _draft_payload(
                name="M03-B Low Level SRD",
                race="srd5.1:race:human",
                background="srd5.1:background:acolyte",
                levels=[_level(1, "srd5.1:class:fighter", hp=10)],
            ),
        )
        fixtures["fixture_low_level_srd.json"] = _export(client, low_level)

        # Lv5 Fighter 3 / Cleric 2 with a phb2014 background, then one Level Up
        # so the chain carries parent_version_no and two provenance snapshots.
        multiclass = _confirm_create(
            client,
            _draft_payload(
                name="M03-B Multiclass Mixed",
                race="srd5.1:race:human",
                background="phb2014:background:soldier",
                abilities=MULTICLASS_ARRAY,
                levels=[
                    _level(1, "srd5.1:class:fighter", hp=10),
                    _level(2, "srd5.1:class:fighter", hp=6),
                    _level(
                        3,
                        "srd5.1:class:fighter",
                        hp=6,
                        subclass_ref="srd5.1:subclass:champion",
                    ),
                    _level(
                        4,
                        "srd5.1:class:cleric",
                        hp=5,
                        subclass_ref="srd5.1:subclass:life",
                    ),
                    _level(5, "srd5.1:class:cleric", hp=5),
                ],
            ),
        )
        started = client.post(
            f"/api/character-builder/characters/{multiclass}/drafts",
            json={"mode": "level_up"},
        )
        assert started.status_code == 201, started.text
        view = started.json()
        payload = dict(view["draft"]["draft_payload"])
        payload["target_level"] = 6
        payload["level_choices"] = [
            *payload["level_choices"],
            _level(6, "srd5.1:class:cleric", hp=5),
        ]
        view = S.http_patch(client, view, payload)
        S.http_confirm(client, _ready(client, view))
        fixtures["fixture_multiclass_mixed.json"] = _export(client, multiclass)

        # Lv3 Ranger taking the XGE Gloom Stalker subclass.
        xge = _confirm_create(
            client,
            _draft_payload(
                name="M03-B XGE Dependent",
                race="srd5.1:race:elf",
                subrace="srd5.1:subrace:high-elf",
                background="srd5.1:background:acolyte",
                levels=[
                    _level(1, "srd5.1:class:ranger", hp=10),
                    _level(2, "srd5.1:class:ranger", hp=6),
                    _level(
                        3,
                        "srd5.1:class:ranger",
                        hp=6,
                        subclass_ref="xge:subclass:gloom-stalker",
                    ),
                ],
            ),
        )
        fixtures["fixture_xge_dependent.json"] = _export(client, xge)

        # Legacy character: landed before M03-B, so provenance stays null.
        build = build_p0_fighter_wizard_fixture()
        legacy = client.app.state.character_repository.create_character(
            name="M03-B Legacy No Provenance",
            build=build,
            state=build_p0_fighter_wizard_state(build),
            version_kind="legacy",
        )
        fixtures["fixture_legacy_no_provenance.json"] = _export(client, str(legacy.id))

        # Rejection fixture for the strict version_kind enum (test guide B.2).
        bad_kind = deepcopy(fixtures["fixture_low_level_srd.json"])
        bad_kind["payload"]["versions"][-1]["version_kind"] = "future_kind"
        fixtures["fixture_bad_version_kind.json"] = bad_kind

        return {name: _canonicalize(doc) for name, doc in fixtures.items()}
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed fixtures differ from freshly generated ones",
    )
    args = parser.parse_args()

    fixtures = build_fixtures()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    drifted: list[str] = []
    for name, document in fixtures.items():
        target = OUTPUT / name
        text = _serialize(document)
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                drifted.append(name)
            continue
        target.write_text(text, encoding="utf-8")

    if args.check and drifted:
        print(
            "committed M03-B fixtures no longer match the export endpoint: "
            + ", ".join(sorted(drifted)),
            file=sys.stderr,
        )
        print("regenerate with: python tests/generate_m03b_fixtures.py", file=sys.stderr)
        return 1
    if not args.check:
        print(f"wrote {len(fixtures)} fixtures to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
