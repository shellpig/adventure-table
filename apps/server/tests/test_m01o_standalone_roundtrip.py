from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from m03c_support import post_document
from m03g_support import export_character, standalone_client


STANDARD_ARRAY = {
    "strength": 15,
    "dexterity": 14,
    "constitution": 13,
    "intelligence": 12,
    "wisdom": 10,
    "charisma": 8,
}


def _fighter_level(character_level: int) -> dict[str, Any]:
    return {
        "character_level": character_level,
        "class_ref": "srd5.1:class:fighter",
        "hp_method": "first_level" if character_level == 1 else "fixed_average",
        "hp_base_gain": 10 if character_level == 1 else 6,
    }


def _draft_payload() -> dict[str, Any]:
    return {
        "basic": {"name": "M01-O Standalone Gunner"},
        "target_level": 1,
        "race_selection": {"reference_id": "phb2014:race:variant-human"},
        "background_selection": {"reference_id": "srd5.1:background:acolyte"},
        "ability_generation": {
            "method": "standard_array",
            "scores": dict(STANDARD_ARRAY),
            "provenance": "test",
        },
        "level_choices": [_fighter_level(1)],
    }


def _create_draft(client) -> dict[str, Any]:
    response = client.post(
        "/api/character-builder/drafts",
        json={"draft_payload": _draft_payload()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _patch(client, view: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    response = client.patch(
        f"/api/character-builder/drafts/{view['draft']['id']}",
        json={"expected_revision": view["draft"]["revision"], "draft_payload": body},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _set_choice(client, view: dict[str, Any], choice: dict[str, Any], option_ids: list[str]) -> dict[str, Any]:
    selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
    selections[choice["choice_id"]] = {
        "choice_id": choice["choice_id"],
        "source_ref": choice.get("source_ref"),
        "selected_option_ids": option_ids,
    }
    return _patch(client, view, {"choice_selections": selections})


def _choice(view: dict[str, Any], option_source: str) -> dict[str, Any]:
    matches = [
        choice
        for choice in view["choices"]
        if choice["option_source"] == option_source and not choice.get("disabled_reason")
    ]
    assert matches, option_source
    return matches[0]


def _fill_required_choices(client, view: dict[str, Any]) -> dict[str, Any]:
    for _ in range(12):
        selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
        used_refs = {
            option.get("reference_id")
            for choice in view["choices"]
            for option in choice["options"]
            if option["option_id"]
            in selections.get(choice["choice_id"], {}).get("selected_option_ids", [])
            and option.get("reference_id")
        }
        changed = False
        for choice in view["choices"]:
            if (
                not choice["required"]
                or choice.get("disabled_reason")
                or choice["option_source"] in {"content:race-feat", "equipment"}
            ):
                continue
            current = selections.get(choice["choice_id"], {}).get("selected_option_ids", [])
            if len(current) == choice["choose_count"]:
                continue
            legal: list[str] = []
            for option in choice["options"]:
                if option.get("disabled_reason"):
                    continue
                reference_id = option.get("reference_id")
                if reference_id and reference_id in used_refs:
                    continue
                legal.append(option["option_id"])
                if reference_id:
                    used_refs.add(reference_id)
                if len(legal) == choice["choose_count"]:
                    break
            assert len(legal) == choice["choose_count"], choice["label"]
            selections[choice["choice_id"]] = {
                "choice_id": choice["choice_id"],
                "source_ref": choice.get("source_ref"),
                "selected_option_ids": legal,
            }
            changed = True
        if not changed:
            return view
        view = _patch(client, view, {"choice_selections": selections})
    raise AssertionError("required choices did not converge")


def _fill_equipment(client, view: dict[str, Any]) -> dict[str, Any]:
    for _ in range(12):
        selections = dict(view["draft"]["draft_payload"].get("starting_equipment_choices") or {})
        changed = False
        for choice in view["choices"]:
            if choice.get("option_source") != "equipment" or choice.get("disabled_reason"):
                continue
            current = selections.get(choice["choice_id"]) or []
            if isinstance(current, str):
                current = [current]
            if len(current) == choice["choose_count"]:
                continue
            legal = [
                option["option_id"]
                for option in choice["options"]
                if not option.get("disabled_reason")
            ][: choice["choose_count"]]
            assert len(legal) == choice["choose_count"], choice["label"]
            selections[choice["choice_id"]] = legal
            changed = True
        if not changed:
            return view
        view = _patch(client, view, {"starting_equipment_choices": selections})
    raise AssertionError("equipment choices did not converge")


def _confirm(client, view: dict[str, Any]) -> str:
    review = client.get(f"/api/character-builder/drafts/{view['draft']['id']}/review")
    assert review.status_code == 200, review.text
    assert review.json()["can_confirm"] is True, review.json()["issues"]
    response = client.post(
        f"/api/character-builder/drafts/{view['draft']['id']}/confirm",
        json={"expected_revision": view["draft"]["revision"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["character_id"]


def test_m01o_standalone_character_json_roundtrip_preserves_feat_static_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with standalone_client(monkeypatch, tmp_path / "source") as (source, _):
        view = _create_draft(source)
        view = _set_choice(source, view, _choice(view, "content:race-feat"), ["tce:feat:gunner"])
        view = _fill_required_choices(source, view)
        view = _fill_equipment(source, view)
        character_id = _confirm(source, view)
        exported = export_character(source, character_id)

    build = exported["payload"]["versions"][-1]["build_payload"]
    assert build["feat_refs"] == ["tce:feat:gunner"]
    assert build["feat_acquisitions"][0]["feat_ref"] == "tce:feat:gunner"
    assert build["feat_static_facts"] == [
        {
            "kind": "weapon_proficiency_category",
            "category": "firearms",
            "source_ref": "tce:feat:gunner",
        }
    ]

    with standalone_client(monkeypatch, tmp_path / "target") as (target, _):
        preview = post_document(target, exported, dry_run=True)
        assert preview.status_code == 200, preview.text
        assert preview.json()["landing_mode"] == "character"
        assert preview.json()["unresolved_ref_count"] == 0

        committed = post_document(target, exported)
        assert committed.status_code == 201, committed.text
        imported_id = committed.json()["character_id"]
        assert imported_id is not None

        reexported = export_character(target, imported_id)
        assert reexported["payload"] == exported["payload"]
