from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient

from app.domain.character_builder.lineages import (
    ASI_PATTERN_2_1,
    LINEAGE_ASI_PATTERN_CHOICE_ID,
    LINEAGE_ASI_PLUS_ONE_CHOICE_ID,
    LINEAGE_ASI_PLUS_TWO_CHOICE_ID,
)
from test_m01f_dhampir_lineage import DHAMPIR
from test_p1f_character_creation import (
    _fill_equipment_choices,
    _fill_generic_choices,
    _seed,
)

HALF_ELF = "srd5.1:race:half-elf"
ACOLYTE = "srd5.1:background:acolyte"
FIGHTER = "srd5.1:class:fighter"
CANDIDATE_ILLEGAL_SKILLS = (
    "srd5.1:skill:arcana",
    "srd5.1:skill:athletics",
    "srd5.1:skill:perception",
    "srd5.1:skill:stealth",
    "srd5.1:skill:survival",
)


def _base_create_payload(name: str, *, lineage: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "basic": {"name": name},
        "target_level": 1,
        "race_selection": {"reference_id": HALF_ELF},
        "background_selection": {"reference_id": ACOLYTE},
        "ability_generation": {
            "method": "standard_array",
            "scores": {
                "strength": 15,
                "dexterity": 14,
                "constitution": 13,
                "intelligence": 12,
                "wisdom": 10,
                "charisma": 8,
            },
            "provenance": "m01-f-http-closeout",
        },
        "level_choices": [
            {
                "character_level": 1,
                "class_ref": FIGHTER,
                "hp_method": "first_level",
                "hp_base_gain": 10,
            }
        ],
    }
    if lineage:
        payload["lineage_selection"] = {"reference_id": DHAMPIR}
    return payload


def _patch_payload(
    client: TestClient,
    view: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = client.patch(
        f"/api/character-builder/drafts/{view['draft']['id']}",
        json={
            "expected_revision": view["draft"]["revision"],
            "draft_payload": payload,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _set_choice(
    client: TestClient,
    view: dict[str, Any],
    choice_id: str,
    option_ids: list[str],
) -> dict[str, Any]:
    choice = next(item for item in view["choices"] if item["choice_id"] == choice_id)
    selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
    selections[choice_id] = {
        "choice_id": choice_id,
        "source_ref": choice.get("source_ref"),
        "selected_option_ids": option_ids,
    }
    return _patch_payload(client, view, {"choice_selections": selections})


def _fill_dhampir_asi(client: TestClient, view: dict[str, Any]) -> dict[str, Any]:
    """Fill dependent +2/+1 choices across revisions so disabled options refresh."""
    pattern = next(
        choice
        for choice in view["choices"]
        if choice["choice_id"] == LINEAGE_ASI_PATTERN_CHOICE_ID
    )
    if pattern.get("selected_option_ids") != [ASI_PATTERN_2_1]:
        view = _set_choice(
            client,
            view,
            LINEAGE_ASI_PATTERN_CHOICE_ID,
            [ASI_PATTERN_2_1],
        )

    plus_two = next(
        choice
        for choice in view["choices"]
        if choice["choice_id"] == LINEAGE_ASI_PLUS_TWO_CHOICE_ID
    )
    plus_two_option = next(
        option for option in plus_two["options"] if not option.get("disabled_reason")
    )
    view = _set_choice(
        client,
        view,
        LINEAGE_ASI_PLUS_TWO_CHOICE_ID,
        [plus_two_option["option_id"]],
    )

    plus_one = next(
        choice
        for choice in view["choices"]
        if choice["choice_id"] == LINEAGE_ASI_PLUS_ONE_CHOICE_ID
    )
    plus_one_option = next(
        option for option in plus_one["options"] if not option.get("disabled_reason")
    )
    return _set_choice(
        client,
        view,
        LINEAGE_ASI_PLUS_ONE_CHOICE_ID,
        [plus_one_option["option_id"]],
    )


def _create_complete_draft(
    client: TestClient,
    name: str,
    *,
    lineage: bool,
) -> dict[str, Any]:
    response = client.post(
        "/api/character-builder/drafts",
        json={"draft_payload": _base_create_payload(name, lineage=lineage)},
    )
    assert response.status_code == 201, response.text
    view = response.json()
    if lineage:
        view = _fill_dhampir_asi(client, view)
    view = _fill_generic_choices(client, view)
    return _fill_equipment_choices(client, view)


def _confirm(client: TestClient, view: dict[str, Any]) -> dict[str, Any]:
    review = client.get(
        f"/api/character-builder/drafts/{view['draft']['id']}/review"
    )
    assert review.status_code == 200, review.text
    assert review.json()["can_confirm"] is True, review.json()["issues"]
    response = client.post(
        f"/api/character-builder/drafts/{view['draft']['id']}/confirm"
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_m01f_http_direct_dhampir_create_confirms_version_one() -> None:
    client, engine = _seed()
    try:
        view = _create_complete_draft(
            client,
            "M01-F Direct Dhampir",
            lineage=True,
        )
        review = client.get(
            f"/api/character-builder/drafts/{view['draft']['id']}/review"
        )
        assert review.status_code == 200, review.text
        payload = review.json()
        assert payload["can_confirm"] is True, payload["issues"]
        candidate = payload["build_candidate"]
        assert candidate["lineage_ref"] == DHAMPIR
        assert candidate["ancestral_origin_ref"] is None
        assert candidate["size"] in {"medium", "small"}
        assert candidate["walking_speed"] == 35
        assert candidate["climb_speed"] == 35

        created = client.post(
            f"/api/character-builder/drafts/{view['draft']['id']}/confirm"
        )
        assert created.status_code == 200, created.text
        result = created.json()
        assert result["version_no"] == 1

        character = client.get(
            f"/api/characters/{result['character_id']}"
        )
        assert character.status_code == 200, character.text
        assert character.json()["build"]["lineage_ref"] == DHAMPIR
        assert character.json()["version_no"] == 1
    finally:
        engine.dispose()


def test_m01f_http_existing_character_transforms_to_version_n_plus_one_with_reconciliation_and_blocking() -> None:
    client, engine = _seed()
    try:
        created = _confirm(
            client,
            _create_complete_draft(
                client,
                "M01-F Transform Hero",
                lineage=False,
            ),
        )
        character_id = created["character_id"]

        before = client.get(f"/api/characters/{character_id}")
        assert before.status_code == 200, before.text
        before_payload = before.json()
        v1_build_snapshot = deepcopy(before_payload["build"])
        live_inventory = deepcopy(before_payload["state"]["inventory_state"])
        live_inventory[0]["quantity"] += 1
        damaged_hp = max(0, before_payload["state"]["current_hp"] - 4)

        state_patch = client.patch(
            f"/api/characters/{character_id}/state",
            json={
                "current_hp": damaged_hp,
                "temporary_hp": 6,
                "conditions": [
                    {
                        "condition_ref": "srd5.1:condition:poisoned",
                        "note": "must survive M01-F Build Edit",
                    }
                ],
                "inventory_state": live_inventory,
            },
        )
        assert state_patch.status_code == 200, state_patch.text

        edit = client.post(
            f"/api/character-builder/characters/{character_id}/drafts",
            json={"mode": "build_edit"},
        )
        assert edit.status_code == 201, edit.text
        view = _patch_payload(
            client,
            edit.json(),
            {"lineage_selection": {"reference_id": DHAMPIR}},
        )
        view = _fill_dhampir_asi(client, view)
        view = _fill_generic_choices(client, view)

        legacy = next(
            choice
            for choice in view["choices"]
            if choice.get("option_source") == "content:lineage-legacy-skill"
        )
        allowed = [option["option_id"] for option in legacy["options"]]
        assert allowed
        illegal = next(
            skill for skill in CANDIDATE_ILLEGAL_SKILLS if skill not in set(allowed)
        )

        selections = dict(
            view["draft"]["draft_payload"].get("choice_selections") or {}
        )
        selections[legacy["choice_id"]] = {
            "choice_id": legacy["choice_id"],
            "source_ref": legacy.get("source_ref"),
            "selected_option_ids": [illegal],
        }
        blocked_view = _patch_payload(
            client,
            view,
            {"choice_selections": selections},
        )
        blocked_review = client.get(
            f"/api/character-builder/drafts/{blocked_view['draft']['id']}/review"
        )
        assert blocked_review.status_code == 200, blocked_review.text
        blocked_payload = blocked_review.json()
        assert blocked_payload["can_confirm"] is False
        assert any(
            issue["code"] == "illegal_ancestral_legacy_skill"
            for issue in blocked_payload["issues"]
        )

        selections = dict(
            blocked_view["draft"]["draft_payload"].get("choice_selections") or {}
        )
        selections[legacy["choice_id"]] = {
            "choice_id": legacy["choice_id"],
            "source_ref": legacy.get("source_ref"),
            "selected_option_ids": allowed,
        }
        view = _patch_payload(
            client,
            blocked_view,
            {"choice_selections": selections},
        )

        review = client.get(
            f"/api/character-builder/drafts/{view['draft']['id']}/review"
        )
        assert review.status_code == 200, review.text
        review_payload = review.json()
        assert review_payload["can_confirm"] is True, review_payload["issues"]
        candidate = review_payload["build_candidate"]
        assert candidate["lineage_ref"] == DHAMPIR
        assert candidate["ancestral_origin_ref"] == HALF_ELF
        assert candidate["starting_equipment"] == v1_build_snapshot["starting_equipment"]

        reconciled = review_payload["reconciliation"]["proposed_state"]
        assert reconciled["current_hp"] == damaged_hp
        assert reconciled["temporary_hp"] == 6
        assert reconciled["conditions"] == [
            {
                "condition_ref": "srd5.1:condition:poisoned",
                "note": "must survive M01-F Build Edit",
            }
        ]
        assert reconciled["inventory_state"] == live_inventory

        confirmed = client.post(
            f"/api/character-builder/drafts/{view['draft']['id']}/confirm"
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["version_no"] == 2

        after = client.get(f"/api/characters/{character_id}")
        assert after.status_code == 200, after.text
        after_payload = after.json()
        assert after_payload["version_no"] == 2
        assert after_payload["build"]["lineage_ref"] == DHAMPIR
        assert after_payload["state"]["current_hp"] == damaged_hp
        assert after_payload["state"]["temporary_hp"] == 6
        assert after_payload["state"]["conditions"] == reconciled["conditions"]
        assert after_payload["state"]["inventory_state"] == live_inventory

        v1 = client.get(f"/api/characters/{character_id}/versions/1")
        v2 = client.get(f"/api/characters/{character_id}/versions/2")
        assert v1.status_code == 200, v1.text
        assert v2.status_code == 200, v2.text
        assert v1.json()["build"] == v1_build_snapshot
        assert v1.json()["build"]["lineage_ref"] is None
        assert v2.json()["build"]["lineage_ref"] == DHAMPIR

        history = client.get(f"/api/characters/{character_id}/versions")
        assert history.status_code == 200, history.text
        rows = history.json()
        assert [row["version_no"] for row in rows] == [1, 2]
        assert [row["version_kind"] for row in rows] == ["create", "build_edit"]
        assert rows[0]["is_current"] is False
        assert rows[1]["is_current"] is True
        assert rows[1]["parent_version_id"] == rows[0]["id"]
    finally:
        engine.dispose()
