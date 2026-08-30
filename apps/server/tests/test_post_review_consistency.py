from __future__ import annotations

from app.domain.character.schemas import AbilityScores, CharacterBuild, RoleplayProfile
from app.domain.character_builder.compiler import _with_derived_content_sources
from test_p1f_character_creation import _seed
from test_p1g_character_versions import (
    _complete_fighter_level_two,
    _confirm_level_one_fighter,
    _start_level_up,
)


def test_content_sources_ignore_stable_key_shaped_roleplay_text() -> None:
    build = CharacterBuild(
        content_sources=("client-supplied",),
        race_ref="srd5.1:race:human",
        background_ref="phb2014:background:soldier",
        character_level=1,
        class_progression=("srd5.1:class:fighter",),
        ability_scores=AbilityScores(
            strength=15,
            dexterity=14,
            constitution=13,
            intelligence=12,
            wisdom=10,
            charisma=8,
        ),
        hp_progression=(10,),
        roleplay_profile=RoleplayProfile(
            appearance="homebrew:note:origin",
            biography="custom:story:background",
            personality_traits=("thirdparty:trait:misleading",),
        ),
    )

    derived = _with_derived_content_sources(build)

    assert derived.content_sources == ("phb2014", "srd5.1")
    assert "homebrew" not in derived.content_sources
    assert "custom" not in derived.content_sources
    assert "thirdparty" not in derived.content_sources
    assert "client-supplied" not in derived.content_sources


def test_state_patch_rejects_stale_build_version_after_level_up() -> None:
    client, engine = _seed()
    created = _confirm_level_one_fighter(client)
    character_id = created["character_id"]
    v1_id = created["current_version_id"]

    initial_sheet = client.get(f"/api/characters/{character_id}/sheet")
    assert initial_sheet.status_code == 200, initial_sheet.text
    assert initial_sheet.json()["current_version_id"] == v1_id

    level_up = _complete_fighter_level_two(
        client,
        _start_level_up(client, character_id),
    )
    confirmed = client.post(
        f"/api/character-builder/drafts/{level_up['draft']['id']}/confirm"
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["version_no"] == 2

    before_stale_patch = client.get(f"/api/characters/{character_id}").json()
    assert before_stale_patch["current_version_id"] != v1_id

    stale = client.patch(
        f"/api/characters/{character_id}/state",
        json={
            "expected_current_version_id": v1_id,
            "current_hp": 1,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "stale_build_version"

    after_stale_patch = client.get(f"/api/characters/{character_id}").json()
    assert after_stale_patch["current_version_id"] == before_stale_patch["current_version_id"]
    assert after_stale_patch["state"] == before_stale_patch["state"]

    current_sheet = client.get(f"/api/characters/{character_id}/sheet").json()
    accepted = client.patch(
        f"/api/characters/{character_id}/state",
        json={
            "expected_current_version_id": current_sheet["current_version_id"],
            "temporary_hp": 4,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["temporary_hp"] == 4
    assert accepted.json()["current_version_id"] == current_sheet["current_version_id"]

    engine.dispose()


def test_confirm_replay_returns_original_confirmed_version_after_later_version() -> None:
    client, engine = _seed()
    created = _confirm_level_one_fighter(client)
    character_id = created["character_id"]

    level_up = _complete_fighter_level_two(
        client,
        _start_level_up(client, character_id),
    )
    level_up_draft_id = level_up["draft"]["id"]
    first_confirm = client.post(
        f"/api/character-builder/drafts/{level_up_draft_id}/confirm"
    )
    assert first_confirm.status_code == 200, first_confirm.text
    original_result = first_confirm.json()
    assert original_result["version_no"] == 2

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
                    "appearance": "Later v3 correction",
                    "biography": "",
                }
            },
        },
    )
    assert patched.status_code == 200, patched.text
    correction_view = patched.json()
    third = client.post(
        f"/api/character-builder/drafts/{correction_view['draft']['id']}/confirm"
    )
    assert third.status_code == 200, third.text
    assert third.json()["version_no"] == 3
    assert third.json()["current_version_id"] != original_result["current_version_id"]

    replay = client.post(
        f"/api/character-builder/drafts/{level_up_draft_id}/confirm"
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == original_result

    live = client.get(f"/api/characters/{character_id}").json()
    assert live["version_no"] == 3
    assert live["current_version_id"] == third.json()["current_version_id"]
    assert len(client.get(f"/api/characters/{character_id}/versions").json()) == 3

    engine.dispose()
