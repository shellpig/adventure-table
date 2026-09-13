"""M01-O §10.6 — feat-linked retraining through real-backend Level Up flows."""

from __future__ import annotations

from typing import Any

import m01k_support as S


ELDRITCH_ADEPT = "tce:feat:eldritch-adept"
FIGHTING_INITIATE = "tce:feat:fighting-initiate"
METAMAGIC_ADEPT = "tce:feat:metamagic-adept"

DEVILS_SIGHT = "srd5.1:feature:eldritch-invocation-devils-sight"
ARMOR_OF_SHADOWS = "srd5.1:feature:eldritch-invocation-armor-of-shadows"
STYLE_DEFENSE = "srd5.1:feature:fighter-fighting-style-defense"
STYLE_DUELING = "srd5.1:feature:fighter-fighting-style-dueling"
CAREFUL = "srd5.1:feature:metamagic-careful-spell"
SUBTLE = "srd5.1:feature:metamagic-subtle-spell"
DISTANT = "srd5.1:feature:metamagic-distant-spell"
EXTENDED = "srd5.1:feature:metamagic-extended-spell"

STANDARD_ARRAY = {
    "strength": 15,
    "dexterity": 14,
    "constitution": 13,
    "intelligence": 12,
    "wisdom": 10,
    "charisma": 8,
}


def _level(character_level: int, class_index: str, *, hp: int, subclass_ref: str | None = None):
    return {
        "character_level": character_level,
        "class_ref": f"srd5.1:class:{class_index}",
        "hp_method": "first_level" if character_level == 1 else "fixed_average",
        "hp_base_gain": hp,
        "subclass_ref": subclass_ref,
    }


FIGHTER_RAIL = [
    _level(1, "fighter", hp=10),
    _level(2, "fighter", hp=6),
    _level(3, "fighter", hp=6, subclass_ref="srd5.1:subclass:champion"),
    _level(4, "fighter", hp=6),
]
WIZARD_RAIL = [
    _level(1, "wizard", hp=6),
    _level(2, "wizard", hp=4, subclass_ref="srd5.1:subclass:evocation"),
    _level(3, "wizard", hp=4),
    _level(4, "wizard", hp=4),
]


def _draft_payload(
    *,
    name: str,
    levels: list[dict[str, Any]],
    race: str = "phb2014:race:variant-human",
):
    return {
        "basic": {"name": name},
        "target_level": len(levels),
        "race_selection": {"reference_id": race},
        "background_selection": {"reference_id": "srd5.1:background:acolyte"},
        "ability_generation": {
            "method": "standard_array",
            "scores": dict(STANDARD_ARRAY),
            "provenance": "test",
        },
        "level_choices": levels,
    }


def _choice(view, option_source: str, *, source_ref: str | None = None):
    matches = [
        item
        for item in view["choices"]
        if item["option_source"] == option_source
        and (source_ref is None or item.get("source_ref") == source_ref)
    ]
    assert matches, f"missing {option_source}"
    return matches[0]


def _selections_with(view, choice, option_ids: list[str]) -> dict[str, Any]:
    selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
    selections[choice["choice_id"]] = {
        "choice_id": choice["choice_id"],
        "source_ref": choice.get("source_ref"),
        "selected_option_ids": option_ids,
    }
    return selections


def _set_choice(client, view, choice, option_ids: list[str], *, expect: int = 200):
    return S.http_patch(
        client,
        view,
        {"choice_selections": _selections_with(view, choice, option_ids)},
        expect=expect,
    )


def _fill_spells(client, view):
    """Take the first legal cantrips / known / spellbook spells each profile offers."""

    profiles = _review(client, view)["resolved_summary"]["spellcasting_profiles"]
    if not profiles:
        return view
    plan: dict[str, Any] = {}
    for profile in profiles:
        cantrips = [
            option["spell_key"] for option in profile["available_spells"] if option["level"] == 0
        ][: profile["cantrip_count"]]
        leveled = [
            option["spell_key"] for option in profile["available_spells"] if option["level"] >= 1
        ]
        plan[profile["profile_id"]] = {
            "cantrip_keys": cantrips,
            "known_spell_keys": leveled[: profile["known_spell_count"]],
            "spellbook_spell_keys": leveled[: profile["spellbook_count"]],
        }
    return S.http_patch(client, view, {"spell_choices": plan})


def _finish(client, view):
    view = S.http_fill_generic(client, view, skip_sources=S.FEAT_OPPORTUNITY_SOURCES)
    view = S.http_fill_generic(client, view)
    view = _fill_spells(client, view)
    return S.http_fill_equipment(client, view)


def _review(client, view):
    response = client.get(f"/api/character-builder/drafts/{view['draft']['id']}/review")
    assert response.status_code == 200, response.text
    return response.json()


def _issue_codes(client, view) -> set[str]:
    return {issue["code"] for issue in _review(client, view)["issues"]}


def _build(client, character_id: str, version_no: int) -> dict[str, Any]:
    response = client.get(f"/api/characters/{character_id}/versions/{version_no}")
    assert response.status_code == 200, response.text
    return response.json()["build"]


def _acquisition(build: dict[str, Any], feat_ref: str) -> dict[str, Any]:
    return next(item for item in build["feat_acquisitions"] if item["feat_ref"] == feat_ref)


def _create_with_feat(
    client,
    *,
    name: str,
    levels,
    feat_ref: str,
    nested: dict[str, list[str]],
    race: str = "phb2014:race:variant-human",
    opportunity_source: str = "content:race-feat",
):
    view = S.http_create_draft(client, _draft_payload(name=name, levels=levels, race=race))
    view = _set_choice(client, view, _choice(view, opportunity_source), [feat_ref])
    for source, option_ids in nested.items():
        view = _set_choice(client, view, _choice(view, source, source_ref=feat_ref), option_ids)
    view = _finish(client, view)
    assert _review(client, view)["can_confirm"] is True, _review(client, view)["issues"]
    return S.http_confirm(client, view)["character_id"]


def _create_with_race_feat(client, *, name: str, levels, feat_ref: str, nested: dict[str, list[str]]):
    return _create_with_feat(
        client,
        name=name,
        levels=levels,
        feat_ref=feat_ref,
        nested=nested,
    )


def _level_up(client, character_id: str, levels: list[dict[str, Any]]):
    response = client.post(
        f"/api/character-builder/characters/{character_id}/drafts",
        json={"mode": "level_up"},
    )
    assert response.status_code == 201, response.text
    return S.http_patch(client, response.json(), {"level_choices": levels})


def _version_draft(client, character_id: str, mode: str):
    response = client.post(
        f"/api/character-builder/characters/{character_id}/drafts",
        json={"mode": mode},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_eldritch_adept_invocation_can_be_replaced_at_any_level_up() -> None:
    client, _ = S.seed_http()
    character_id = _create_with_race_feat(
        client,
        name="M01-O Eldritch Adept",
        levels=WIZARD_RAIL[:1],
        feat_ref=ELDRITCH_ADEPT,
        nested={"content:feat:invocation": [DEVILS_SIGHT]},
    )

    view = _level_up(client, character_id, WIZARD_RAIL[:2])
    invocation = _choice(view, "content:feat:invocation", source_ref=ELDRITCH_ADEPT)
    view = _set_choice(client, view, invocation, [ARMOR_OF_SHADOWS])
    view = _finish(client, view)
    assert _review(client, view)["can_confirm"] is True, _review(client, view)["issues"]
    S.http_confirm(client, view)

    version_one = _build(client, character_id, 1)
    version_two = _build(client, character_id, 2)
    assert _acquisition(version_one, ELDRITCH_ADEPT)["selections"]["invocation"] == [DEVILS_SIGHT]
    assert _acquisition(version_two, ELDRITCH_ADEPT)["selections"]["invocation"] == [ARMOR_OF_SHADOWS]
    assert DEVILS_SIGHT in version_one["feature_refs"]
    assert DEVILS_SIGHT not in version_two["feature_refs"]
    assert ARMOR_OF_SHADOWS in version_two["feature_refs"]
    assert version_one["content_sources"] == version_two["content_sources"]


def test_fighting_initiate_style_replacement_waits_for_an_asi_level() -> None:
    client, _ = S.seed_http()
    character_id = _create_with_race_feat(
        client,
        name="M01-O Fighting Initiate",
        levels=FIGHTER_RAIL[:1],
        feat_ref=FIGHTING_INITIATE,
        nested={"content:feat:fighting_style": [STYLE_DEFENSE]},
    )

    # Level 2 grants no ASI: the historical style stays locked.
    view = _level_up(client, character_id, FIGHTER_RAIL[:2])
    style = _choice(view, "content:feat:fighting_style", source_ref=FIGHTING_INITIATE)
    _set_choice(client, view, style, [STYLE_DUELING], expect=422)
    view = _finish(client, view)
    S.http_confirm(client, view)
    view = _finish(client, _level_up(client, character_id, FIGHTER_RAIL[:3]))
    S.http_confirm(client, view)

    # Level 4 grants an ASI: one replacement is allowed and versioned.
    view = _level_up(client, character_id, FIGHTER_RAIL[:4])
    style = _choice(view, "content:feat:fighting_style", source_ref=FIGHTING_INITIATE)
    view = _set_choice(client, view, style, [STYLE_DUELING])
    view = _finish(client, view)
    assert _review(client, view)["can_confirm"] is True, _review(client, view)["issues"]
    S.http_confirm(client, view)

    assert _acquisition(_build(client, character_id, 3), FIGHTING_INITIATE)["selections"]["style"] == [STYLE_DEFENSE]
    assert _acquisition(_build(client, character_id, 4), FIGHTING_INITIATE)["selections"]["style"] == [STYLE_DUELING]


def test_metamagic_adept_replaces_one_option_per_asi_level_up() -> None:
    client, _ = S.seed_http()
    character_id = _create_with_race_feat(
        client,
        name="M01-O Metamagic Adept",
        levels=WIZARD_RAIL[:1],
        feat_ref=METAMAGIC_ADEPT,
        nested={"content:feat:metamagic": [CAREFUL, SUBTLE]},
    )
    for target in (2, 3):
        S.http_confirm(client, _finish(client, _level_up(client, character_id, WIZARD_RAIL[:target])))

    view = _level_up(client, character_id, WIZARD_RAIL[:4])
    metamagic = _choice(view, "content:feat:metamagic", source_ref=METAMAGIC_ADEPT)

    # Replacing both options exceeds the policy; the review reports it structurally.
    view = _set_choice(client, view, metamagic, [DISTANT, EXTENDED])
    assert "feat_retraining_limit_exceeded" in _issue_codes(client, view)

    view = _set_choice(client, view, metamagic, [CAREFUL, DISTANT])
    view = _finish(client, view)
    assert _review(client, view)["can_confirm"] is True, _review(client, view)["issues"]
    S.http_confirm(client, view)

    version_three = _build(client, character_id, 3)
    version_four = _build(client, character_id, 4)
    assert set(_acquisition(version_three, METAMAGIC_ADEPT)["selections"]["metamagic"]) == {CAREFUL, SUBTLE}
    assert set(_acquisition(version_four, METAMAGIC_ADEPT)["selections"]["metamagic"]) == {CAREFUL, DISTANT}
    grant = next(
        item for item in version_four["feat_resource_grants"] if item["resource_id"] == "metamagic-adept-sorcery-points"
    )
    assert grant["capacity"] == 2 and grant["allowed_spend_tags"] == ["metamagic"]


def test_build_edit_is_not_a_free_retraining_path() -> None:
    client, _ = S.seed_http()
    character_id = _create_with_race_feat(
        client,
        name="M01-O Build Edit",
        levels=WIZARD_RAIL[:1],
        feat_ref=ELDRITCH_ADEPT,
        nested={"content:feat:invocation": [DEVILS_SIGHT]},
    )

    view = _version_draft(client, character_id, "build_edit")
    invocation = _choice(view, "content:feat:invocation", source_ref=ELDRITCH_ADEPT)
    view = _set_choice(client, view, invocation, [ARMOR_OF_SHADOWS])
    review = _review(client, view)
    assert review["can_confirm"] is False
    assert "feat_retraining_requires_level_up" in {issue["code"] for issue in review["issues"]}
    assert _acquisition(_build(client, character_id, 1), ELDRITCH_ADEPT)["selections"]["invocation"] == [DEVILS_SIGHT]


def _version_history(client, character_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/characters/{character_id}/versions")
    assert response.status_code == 200, response.text
    return response.json()


def _character_snapshot(client, character_id: str) -> dict[str, Any]:
    character = client.get(f"/api/characters/{character_id}")
    assert character.status_code == 200, character.text
    build = character.json()["build"]
    return {
        "version_history": _version_history(client, character_id),
        "feat_refs": build["feat_refs"],
        "feat_acquisitions": build["feat_acquisitions"],
        "feat_resource_grants": build["feat_resource_grants"],
        "feat_static_facts": build["feat_static_facts"],
        "spell_access_entries": [
            entry for entry in build["spell_access_entries"] if entry["source_type"] == "feat"
        ],
        "feature_refs": build["feature_refs"],
        "skill_choices": build["skill_choices"],
        "skill_expertise_refs": build["skill_expertise_refs"],
        "language_refs": build["language_refs"],
        "content_sources": build["content_sources"],
    }


def test_m01o_representative_builds_survive_reload_restart_and_history() -> None:
    client, engine = S.seed_http()

    representatives = {
        "dragon-hide": _create_with_feat(
            client,
            name="M01-O Restart Dragon Hide",
            race="srd5.1:race:dragonborn",
            levels=FIGHTER_RAIL,
            opportunity_source="content:asi-feat",
            feat_ref="xge:feat:dragon-hide",
            nested={"content:feat:ability": ["ability:strength"]},
        ),
        "prodigy": _create_with_feat(
            client,
            name="M01-O Restart Prodigy",
            levels=FIGHTER_RAIL[:1],
            feat_ref="xge:feat:prodigy",
            nested={
                "content:feat:skill": ["srd5.1:proficiency:skill-investigation"],
                "content:feat:tool": ["srd5.1:proficiency:thieves-tools"],
                "content:feat:language": ["srd5.1:language:elvish"],
                "content:feat:expertise": ["srd5.1:skill:investigation"],
            },
        ),
        "fey-touched": _create_with_feat(
            client,
            name="M01-O Restart Fey Touched",
            levels=WIZARD_RAIL[:1],
            feat_ref="tce:feat:fey-touched",
            nested={
                "content:feat:ability": ["ability:wisdom"],
                "content:feat:spell": ["srd5.1:spell:charm-person"],
            },
        ),
        "fighting-initiate": _create_with_feat(
            client,
            name="M01-O Restart Fighting Initiate",
            levels=FIGHTER_RAIL[:1],
            feat_ref=FIGHTING_INITIATE,
            nested={"content:feat:fighting_style": [STYLE_DEFENSE]},
        ),
        "eldritch-adept": _create_with_feat(
            client,
            name="M01-O Restart Eldritch Adept",
            levels=WIZARD_RAIL[:1],
            feat_ref=ELDRITCH_ADEPT,
            nested={"content:feat:invocation": [DEVILS_SIGHT]},
        ),
        "metamagic-adept": _create_with_feat(
            client,
            name="M01-O Restart Metamagic Adept",
            levels=WIZARD_RAIL[:1],
            feat_ref=METAMAGIC_ADEPT,
            nested={"content:feat:metamagic": [CAREFUL, SUBTLE]},
        ),
        "artificer-initiate": _create_with_feat(
            client,
            name="M01-O Restart Artificer Initiate",
            levels=WIZARD_RAIL[:1],
            feat_ref="tce:feat:artificer-initiate",
            nested={
                "content:feat:artisan_tool": ["srd5.1:proficiency:tinkers-tools"],
                "content:feat:spell": ["srd5.1:spell:mending", "srd5.1:spell:cure-wounds"],
            },
        ),
        "gunner": _create_with_feat(
            client,
            name="M01-O Restart Gunner",
            levels=FIGHTER_RAIL[:1],
            feat_ref="tce:feat:gunner",
            nested={},
        ),
    }
    before = {
        label: _character_snapshot(client, character_id)
        for label, character_id in representatives.items()
    }

    restarted = S.rebind_http(engine)
    after = {
        label: _character_snapshot(restarted, character_id)
        for label, character_id in representatives.items()
    }

    assert after == before
    assert before["dragon-hide"]["feat_acquisitions"][0]["selections"]["ability"] == ["ability:strength"]
    assert before["prodigy"]["skill_expertise_refs"] == ["srd5.1:skill:investigation"]
    assert {
        entry["spell_key"]: entry["casting_ability"]
        for entry in before["fey-touched"]["spell_access_entries"]
    } == {
        "srd5.1:spell:misty-step": "wisdom",
        "srd5.1:spell:charm-person": "wisdom",
    }
    assert STYLE_DEFENSE in before["fighting-initiate"]["feature_refs"]
    assert DEVILS_SIGHT in before["eldritch-adept"]["feature_refs"]
    metamagic_grant = before["metamagic-adept"]["feat_resource_grants"][0]
    assert metamagic_grant["resource_id"] == "metamagic-adept-sorcery-points"
    assert metamagic_grant["allowed_spend_tags"] == ["metamagic"]
    assert before["artificer-initiate"]["feat_static_facts"] == [
        {
            "kind": "spellcasting_focus",
            "tool_ref": "srd5.1:proficiency:tinkers-tools",
            "casting_ability": "intelligence",
            "source_ref": "tce:feat:artificer-initiate",
        }
    ]
    assert before["gunner"]["feat_static_facts"] == [
        {
            "kind": "weapon_proficiency_category",
            "category": "firearms",
            "source_ref": "tce:feat:gunner",
        }
    ]
    assert all(snapshot["version_history"][0]["version_no"] == 1 for snapshot in before.values())
