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


def _draft_payload(*, name: str, levels: list[dict[str, Any]]):
    return {
        "basic": {"name": name},
        "target_level": len(levels),
        "race_selection": {"reference_id": "phb2014:race:variant-human"},
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


def _create_with_race_feat(client, *, name: str, levels, feat_ref: str, nested: dict[str, list[str]]):
    view = S.http_create_draft(client, _draft_payload(name=name, levels=levels))
    view = _set_choice(client, view, _choice(view, "content:race-feat"), [feat_ref])
    for source, option_ids in nested.items():
        view = _set_choice(client, view, _choice(view, source, source_ref=feat_ref), option_ids)
    view = _finish(client, view)
    assert _review(client, view)["can_confirm"] is True, _review(client, view)["issues"]
    return S.http_confirm(client, view)["character_id"]


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
