from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from test_p1f_character_creation import (
    _fill_equipment_choices,
    _fill_generic_choices,
    _seed,
)


HALF_ELF = "srd5.1:race:half-elf"
WOOD = "scag:race-variant:half-elf-wood-descent"
AQUATIC = "scag:race-variant:half-elf-aquatic-descent"


def _create_half_elf_draft(client: TestClient, variant: str) -> dict[str, Any]:
    response = client.post(
        "/api/character-builder/drafts",
        json={
            "draft_payload": {
                "basic": {"name": "M01-E Lifecycle Hero"},
                "target_level": 1,
                "race_selection": {"reference_id": HALF_ELF},
                "race_variant_selection": {"reference_id": variant},
                "background_selection": {
                    "reference_id": "srd5.1:background:acolyte"
                },
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
                    "provenance": "m01-e-lifecycle-test",
                },
                "level_choices": [
                    {
                        "character_level": 1,
                        "class_ref": "srd5.1:class:fighter",
                        "hp_method": "first_level",
                        "hp_base_gain": 10,
                    }
                ],
            }
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _choose_variant_replacement(
    client: TestClient,
    view: dict[str, Any],
    option_id: str,
) -> dict[str, Any]:
    replacement = next(
        choice
        for choice in view["choices"]
        if choice.get("option_source") == "content:race-variant-replacement"
    )
    assert option_id in {option["option_id"] for option in replacement["options"]}
    selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
    selections[replacement["choice_id"]] = {
        "choice_id": replacement["choice_id"],
        "source_ref": replacement.get("source_ref"),
        "selected_option_ids": [option_id],
    }
    response = client.patch(
        f"/api/character-builder/drafts/{view['draft']['id']}",
        json={
            "expected_revision": view["draft"]["revision"],
            "draft_payload": {"choice_selections": selections},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _complete(view: dict[str, Any], client: TestClient) -> dict[str, Any]:
    view = _fill_generic_choices(client, view)
    return _fill_equipment_choices(client, view)


def test_m01e_draft_reload_build_edit_and_version_history_persist_ancestry() -> None:
    client, engine = _seed()
    try:
        view = _create_half_elf_draft(client, WOOD)
        view = _choose_variant_replacement(client, view, "fleet-of-foot")

        # This is a real repository/API reload, not a Pydantic round-trip.
        reloaded = client.get(
            f"/api/character-builder/drafts/{view['draft']['id']}"
        )
        assert reloaded.status_code == 200, reloaded.text
        view = reloaded.json()
        assert view["draft"]["draft_payload"]["race_variant_selection"] == {
            "reference_id": WOOD
        }
        wood_choice = next(
            choice
            for choice in view["choices"]
            if choice.get("option_source") == "content:race-variant-replacement"
        )
        assert view["draft"]["draft_payload"]["choice_selections"][
            wood_choice["choice_id"]
        ]["selected_option_ids"] == ["fleet-of-foot"]

        view = _complete(view, client)
        review = client.get(
            f"/api/character-builder/drafts/{view['draft']['id']}/review"
        )
        assert review.status_code == 200, review.text
        assert review.json()["can_confirm"] is True, review.json()["issues"]
        assert review.json()["build_candidate"]["race_variant_ref"] == WOOD
        assert review.json()["build_candidate"]["walking_speed"] == 35

        confirmed = client.post(
            f"/api/character-builder/drafts/{view['draft']['id']}/confirm"
        )
        assert confirmed.status_code == 200, confirmed.text
        created = confirmed.json()
        character_id = created["character_id"]
        assert created["version_no"] == 1

        character_v1 = client.get(f"/api/characters/{character_id}")
        assert character_v1.status_code == 200, character_v1.text
        assert character_v1.json()["build"]["race_variant_ref"] == WOOD
        assert character_v1.json()["build"]["walking_speed"] == 35

        edit = client.post(
            f"/api/character-builder/characters/{character_id}/drafts",
            json={"mode": "build_edit"},
        )
        assert edit.status_code == 201, edit.text
        edit_view = edit.json()
        assert edit_view["draft"]["draft_payload"]["race_variant_selection"] == {
            "reference_id": WOOD
        }
        assert any(
            selection.get("selected_option_ids") == ["fleet-of-foot"]
            for selection in edit_view["draft"]["draft_payload"][
                "choice_selections"
            ].values()
        )

        # Build Edit is the authorized flow for changing ancestry. Keep the old
        # Wood child selection in the payload on purpose: the compiler must
        # isolate stale branch state when Aquatic becomes active.
        changed_variant = client.patch(
            f"/api/character-builder/drafts/{edit_view['draft']['id']}",
            json={
                "expected_revision": edit_view["draft"]["revision"],
                "draft_payload": {
                    "race_variant_selection": {"reference_id": AQUATIC}
                },
            },
        )
        assert changed_variant.status_code == 200, changed_variant.text
        edit_view = changed_variant.json()
        edit_view = _choose_variant_replacement(
            client, edit_view, "swimming-speed"
        )

        reloaded_edit = client.get(
            f"/api/character-builder/drafts/{edit_view['draft']['id']}"
        )
        assert reloaded_edit.status_code == 200, reloaded_edit.text
        edit_view = reloaded_edit.json()
        assert edit_view["draft"]["draft_payload"]["race_variant_selection"] == {
            "reference_id": AQUATIC
        }

        edit_review = client.get(
            f"/api/character-builder/drafts/{edit_view['draft']['id']}/review"
        )
        assert edit_review.status_code == 200, edit_review.text
        assert edit_review.json()["can_confirm"] is True, edit_review.json()["issues"]
        candidate = edit_review.json()["build_candidate"]
        assert candidate["race_variant_ref"] == AQUATIC
        assert candidate["walking_speed"] == 30
        assert candidate["swim_speed"] == 30

        confirmed_edit = client.post(
            f"/api/character-builder/drafts/{edit_view['draft']['id']}/confirm"
        )
        assert confirmed_edit.status_code == 200, confirmed_edit.text
        assert confirmed_edit.json()["version_no"] == 2

        current = client.get(f"/api/characters/{character_id}")
        assert current.status_code == 200, current.text
        assert current.json()["version_no"] == 2
        assert current.json()["build"]["race_variant_ref"] == AQUATIC
        assert current.json()["build"]["walking_speed"] == 30
        assert current.json()["build"]["swim_speed"] == 30

        history = client.get(f"/api/characters/{character_id}/versions")
        assert history.status_code == 200, history.text
        rows = history.json()
        assert [row["version_no"] for row in rows] == [1, 2]
        assert [row["version_kind"] for row in rows] == ["create", "build_edit"]
        assert rows[0]["is_current"] is False
        assert rows[1]["is_current"] is True
        assert rows[1]["parent_version_id"] == rows[0]["id"]

        v1 = client.get(f"/api/characters/{character_id}/versions/1")
        v2 = client.get(f"/api/characters/{character_id}/versions/2")
        assert v1.status_code == 200, v1.text
        assert v2.status_code == 200, v2.text
        assert v1.json()["build"]["race_variant_ref"] == WOOD
        assert v1.json()["build"]["walking_speed"] == 35
        assert v1.json()["build"]["swim_speed"] is None
        assert v2.json()["build"]["race_variant_ref"] == AQUATIC
        assert v2.json()["build"]["walking_speed"] == 30
        assert v2.json()["build"]["swim_speed"] == 30
    finally:
        engine.dispose()
