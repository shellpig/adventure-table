from __future__ import annotations

from copy import deepcopy

from app.content import load_default_content_registry
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character.schemas import (
    CharacterBuild,
    SpellResourcePool,
    SpellSlotCapacity,
)
from app.domain.character_builder.reconciliation import reconcile_character_state
from app.domain.rules.hit_points import calculate_max_hp
from test_p1f_character_creation import _complete_fighter_draft, _seed


def _confirm_level_one_fighter(client):
    view = _complete_fighter_draft(client)
    response = client.post(
        f"/api/character-builder/drafts/{view['draft']['id']}/confirm"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _start_level_up(client, character_id: str):
    response = client.post(
        f"/api/character-builder/characters/{character_id}/drafts",
        json={"mode": "level_up"},
    )
    assert response.status_code == 201, response.text
    view = response.json()
    assert view["draft"]["mode"] == "level_up"
    return view


def _complete_fighter_level_two(client, view):
    levels = list(view["draft"]["draft_payload"]["level_choices"])
    assert len(levels) == 1
    levels.append(
        {
            "character_level": 2,
            "class_ref": "srd5.1:class:fighter",
            "hp_method": "fixed_average",
            "hp_base_gain": 6,
            "subclass_ref": None,
        }
    )
    response = client.patch(
        f"/api/character-builder/drafts/{view['draft']['id']}",
        json={
            "expected_revision": view["draft"]["revision"],
            "draft_payload": {"level_choices": levels},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_p1g_level_up_preserves_damage_live_state_and_immutable_history() -> None:
    client, engine = _seed()
    created = _confirm_level_one_fighter(client)
    character_id = created["character_id"]

    before = client.get(f"/api/characters/{character_id}").json()
    old_build = CharacterBuild.model_validate(before["build"])
    old_max = calculate_max_hp(old_build)
    live_inventory = deepcopy(before["state"]["inventory_state"])
    damaged_hp = old_max - 5
    state_patch = client.patch(
        f"/api/characters/{character_id}/state",
        json={
            "current_hp": damaged_hp,
            "temporary_hp": 3,
            "hit_dice_state": {"d10": 0},
            "inventory_state": live_inventory,
        },
    )
    assert state_patch.status_code == 200, state_patch.text

    v1 = client.get(f"/api/characters/{character_id}/versions/1")
    assert v1.status_code == 200, v1.text
    v1_build_snapshot = deepcopy(v1.json()["build"])

    draft = _start_level_up(client, character_id)
    assert draft["draft"]["base_version_id"] == created["current_version_id"]
    assert draft["draft"]["draft_payload"]["target_level"] == 2
    assert len(draft["draft"]["draft_payload"]["level_choices"]) == 1

    during = client.get(f"/api/characters/{character_id}").json()
    assert during["current_version_id"] == created["current_version_id"]
    assert during["state"]["current_hp"] == damaged_hp

    draft = _complete_fighter_level_two(client, draft)
    review = client.get(
        f"/api/character-builder/drafts/{draft['draft']['id']}/review"
    )
    assert review.status_code == 200, review.text
    payload = review.json()
    assert payload["can_confirm"] is True, payload["issues"]
    assert payload["initial_state"] is None
    assert payload["reconciliation"] is not None

    new_build = CharacterBuild.model_validate(payload["build_candidate"])
    new_max = calculate_max_hp(new_build)
    reconciled = payload["reconciliation"]["proposed_state"]
    assert reconciled["current_hp"] == new_max - 5
    assert reconciled["temporary_hp"] == 3
    assert reconciled["hit_dice_state"]["d10"] == 1
    assert reconciled["inventory_state"] == live_inventory

    confirmed = client.post(
        f"/api/character-builder/drafts/{draft['draft']['id']}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    assert result["version_no"] == 2
    assert result["current_version_id"] != created["current_version_id"]

    after = client.get(f"/api/characters/{character_id}").json()
    assert after["version_no"] == 2
    assert after["state"]["current_hp"] == new_max - 5
    assert after["state"]["temporary_hp"] == 3
    assert after["state"]["hit_dice_state"]["d10"] == 1
    assert after["state"]["inventory_state"] == live_inventory

    old_after = client.get(f"/api/characters/{character_id}/versions/1").json()
    assert old_after["build"] == v1_build_snapshot
    history = client.get(f"/api/characters/{character_id}/versions")
    assert history.status_code == 200, history.text
    versions = history.json()
    assert [version["version_no"] for version in versions] == [1, 2]
    assert versions[0]["version_kind"] == "create"
    assert versions[0]["is_current"] is False
    assert versions[1]["version_kind"] == "level_up"
    assert versions[1]["parent_version_id"] == versions[0]["id"]
    assert versions[1]["is_current"] is True

    engine.dispose()


def test_p1g_stale_level_up_is_409_and_does_not_create_another_version() -> None:
    client, engine = _seed()
    created = _confirm_level_one_fighter(client)
    character_id = created["character_id"]

    first = _complete_fighter_level_two(client, _start_level_up(client, character_id))
    second = _complete_fighter_level_two(client, _start_level_up(client, character_id))

    accepted = client.post(
        f"/api/character-builder/drafts/{first['draft']['id']}/confirm"
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["version_no"] == 2

    stale = client.post(
        f"/api/character-builder/drafts/{second['draft']['id']}/confirm"
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "stale_build_version"

    history = client.get(f"/api/characters/{character_id}/versions").json()
    assert len(history) == 2
    assert history[-1]["version_no"] == 2

    engine.dispose()


def test_p1g_correction_lineage_and_cancel_do_not_mutate_live_character() -> None:
    client, engine = _seed()
    created = _confirm_level_one_fighter(client)
    character_id = created["character_id"]
    level_up = _complete_fighter_level_two(client, _start_level_up(client, character_id))
    confirmed_level_up = client.post(
        f"/api/character-builder/drafts/{level_up['draft']['id']}/confirm"
    )
    assert confirmed_level_up.status_code == 200, confirmed_level_up.text

    correction = client.post(
        f"/api/character-builder/characters/{character_id}/drafts",
        json={"mode": "correction"},
    )
    assert correction.status_code == 201, correction.text
    correction_view = correction.json()
    patched = client.patch(
        f"/api/character-builder/drafts/{correction_view['draft']['id']}",
        json={
            "expected_revision": correction_view["draft"]["revision"],
            "draft_payload": {
                "roleplay_profile": {
                    "appearance": "Corrected historical note",
                    "biography": "",
                }
            },
        },
    )
    assert patched.status_code == 200, patched.text
    correction_view = patched.json()
    review = client.get(
        f"/api/character-builder/drafts/{correction_view['draft']['id']}/review"
    )
    assert review.status_code == 200, review.text
    assert review.json()["can_confirm"] is True, review.json()["issues"]

    confirmed = client.post(
        f"/api/character-builder/drafts/{correction_view['draft']['id']}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["version_no"] == 3

    history = client.get(f"/api/characters/{character_id}/versions").json()
    assert [row["version_kind"] for row in history] == ["create", "level_up", "correction"]
    assert history[1]["superseded_by_version_id"] == history[2]["id"]
    assert history[2]["parent_version_id"] == history[1]["id"]
    assert history[2]["is_current"] is True

    before_cancel = client.get(f"/api/characters/{character_id}").json()
    edit = client.post(
        f"/api/character-builder/characters/{character_id}/drafts",
        json={"mode": "build_edit"},
    )
    assert edit.status_code == 201, edit.text
    cancelled = client.delete(
        f"/api/character-builder/drafts/{edit.json()['draft']['id']}"
    )
    assert cancelled.status_code == 204, cancelled.text
    after_cancel = client.get(f"/api/characters/{character_id}").json()
    assert after_cancel == before_cancel
    assert len(client.get(f"/api/characters/{character_id}/versions").json()) == 3

    engine.dispose()


def test_p1g_reconciliation_preserves_resource_usage_hit_dice_and_blocks_illegal_prepared() -> None:
    registry = load_default_content_registry()
    base = build_p0_fighter_wizard_fixture()
    normal_pool = SpellResourcePool(
        pool_id="normal:test",
        pool_type="normal_multiclass_slots",
        slots=(
            SpellSlotCapacity(level=1, capacity=4),
            SpellSlotCapacity(level=2, capacity=3),
            SpellSlotCapacity(level=3, capacity=2),
        ),
    )
    old_build = base.model_copy(update={"spell_resource_pools": (normal_pool,)})
    old_state = build_p0_fighter_wizard_state(old_build).model_copy(
        update={
            "current_hp": calculate_max_hp(old_build) - 10,
            "temporary_hp": 7,
            "hit_dice_state": {"d10": 3, "d6": 4},
        }
    )

    bigger_pool = normal_pool.model_copy(
        update={
            "slots": (
                SpellSlotCapacity(level=1, capacity=5),
                SpellSlotCapacity(level=2, capacity=3),
                SpellSlotCapacity(level=3, capacity=2),
            )
        }
    )
    fighter = "srd5.1:class:fighter"
    new_build = old_build.model_copy(
        update={
            "character_level": 11,
            "class_progression": (*old_build.class_progression, fighter),
            "hp_progression": (*old_build.hp_progression, 6),
            "spell_resource_pools": (bigger_pool,),
        }
    )
    preview = reconcile_character_state(old_build, old_state, new_build, registry)
    assert preview.can_apply is True, preview.blocking_issues
    assert preview.proposed_state.current_hp == calculate_max_hp(new_build) - 10
    assert preview.proposed_state.temporary_hp == 7
    assert preview.proposed_state.spell_slots[1].used == 1
    assert preview.proposed_state.spell_slots[1].remaining == 4
    assert preview.proposed_state.hit_dice_state["d10"] == 4
    assert preview.proposed_state.hit_dice_state["d6"] == 4
    assert preview.proposed_state.inventory_state == old_state.inventory_state

    removed_fireball = tuple(
        entry
        for entry in new_build.spell_access_entries
        if entry.entry_id != "wizard:fireball"
    )
    illegal_build = new_build.model_copy(
        update={"spell_access_entries": removed_fireball}
    )
    blocked = reconcile_character_state(old_build, old_state, illegal_build, registry)
    assert blocked.can_apply is False
    assert any(
        issue.code == "prepared_spell_reconciliation_required"
        for issue in blocked.blocking_issues
    )
