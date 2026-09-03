"""M01-K K.12 / K.13 — real-backend feat and spell flows, restart and equivalence."""

from __future__ import annotations

from typing import Any

import m01k_support as S


OBSERVANT = "phb2014:feat:observant"
TOUGH = "phb2014:feat:tough"
ELEMENTAL_ADEPT = "phb2014:feat:elemental-adept"
MARTIAL_ADEPT = "phb2014:feat:martial-adept"
CHROMATIC_ORB = "phb2014:spell:chromatic-orb"

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


def _draft_payload(*, name: str, race: str, levels: list[dict[str, Any]], abilities=None):
    return {
        "basic": {"name": name},
        "target_level": len(levels),
        "race_selection": {"reference_id": race},
        "background_selection": {"reference_id": "srd5.1:background:acolyte"},
        "ability_generation": {
            "method": "standard_array",
            "scores": dict(abilities or STANDARD_ARRAY),
            "provenance": "test",
        },
        "level_choices": levels,
    }


def _choice(view, option_source: str):
    matches = [item for item in view["choices"] if item["option_source"] == option_source]
    assert matches, f"missing {option_source}"
    return matches[0]


def _set_choice(client, view, choice: dict[str, Any], option_ids: list[str]):
    selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
    selections[choice["choice_id"]] = {
        "choice_id": choice["choice_id"],
        "source_ref": choice.get("source_ref"),
        "selected_option_ids": option_ids,
    }
    return S.http_patch(client, view, {"choice_selections": selections})


def _finish(client, view, *, fill_remaining_feats: bool = True):
    """Fill everything the test did not pin by hand.

    The first pass leaves feat opportunities alone so the caller's own feat
    selection survives; the second fills any opportunity still left open.
    """

    view = S.http_fill_generic(client, view, skip_sources=S.FEAT_OPPORTUNITY_SOURCES)
    if fill_remaining_feats:
        view = S.http_fill_generic(client, view)
    return S.http_fill_equipment(client, view)


def _review(client, view):
    response = client.get(
        f"/api/character-builder/drafts/{view['draft']['id']}/review"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_ready(client, view) -> dict[str, Any]:
    review = _review(client, view)
    assert review["can_confirm"] is True, review["issues"]
    return review


def _take_feat(client, view, option_source: str, feat_ref: str, nested: dict[str, list[str]] | None = None):
    view = _set_choice(client, view, _choice(view, option_source), [feat_ref])
    for source, option_ids in (nested or {}).items():
        view = _set_choice(client, view, _choice(view, source), option_ids)
    return view


def _build(client, character_id: str, version_no: int) -> dict[str, Any]:
    response = client.get(f"/api/characters/{character_id}/versions/{version_no}")
    assert response.status_code == 200, response.text
    return response.json()["build"]


# --- K-E2E-01 — Variant Human + a structural PHB feat -------------------------


def test_variant_human_phb_feat_confirms_and_survives_reload() -> None:
    client, _ = S.seed_http()
    view = S.http_create_draft(
        client,
        _draft_payload(
            name="M01-K Variant Human",
            race="phb2014:race:variant-human",
            levels=[_level(1, "fighter", hp=10)],
        ),
    )
    view = _take_feat(
        client,
        view,
        "content:race-feat",
        OBSERVANT,
        nested={"content:feat:ability": ["ability:wisdom"]},
    )
    view = _finish(client, view)
    _assert_ready(client, view)

    confirmed = S.http_confirm(client, view)
    character_id = confirmed["character_id"]

    sheet = client.get(f"/api/characters/{character_id}/sheet").json()
    assert OBSERVANT in {entry["key"] for entry in sheet["features"]}
    passive_perception = sheet["passive_perception"]
    passive_investigation = sheet["passive_investigation"]

    build = _build(client, character_id, 1)
    assert build["feat_refs"] == [OBSERVANT]
    assert build["feat_acquisitions"][0]["selections"]["ability"] == ["ability:wisdom"]
    assert {
        (modifier["target"], modifier["value"]) for modifier in build["static_derived_modifiers"]
    } == {("passive_perception", 5), ("passive_investigation", 5)}

    reloaded = client.get(f"/api/characters/{character_id}/sheet").json()
    assert reloaded["passive_perception"] == passive_perception
    assert reloaded["passive_investigation"] == passive_investigation


# --- K-E2E-02 — ASI → PHB feat through Level Up -------------------------------


def _level_up(client, character_id: str, levels: list[dict[str, Any]]):
    response = client.post(
        f"/api/character-builder/characters/{character_id}/drafts",
        json={"mode": "level_up"},
    )
    assert response.status_code == 201, response.text
    view = response.json()
    return S.http_patch(client, view, {"level_choices": levels})


def _fighter_at_level_one(client, *, name="M01-K Fighter"):
    view = S.http_create_draft(
        client,
        _draft_payload(name=name, race="srd5.1:race:human", levels=[_level(1, "fighter", hp=10)]),
    )
    view = _finish(client, view)
    return S.http_confirm(client, view)["character_id"]


FIGHTER_RAIL = [
    _level(1, "fighter", hp=10),
    _level(2, "fighter", hp=6),
    _level(3, "fighter", hp=6, subclass_ref="srd5.1:subclass:champion"),
    _level(4, "fighter", hp=6),
]


def test_asi_feat_through_level_up_creates_a_new_version_and_keeps_history() -> None:
    client, _ = S.seed_http()
    character_id = _fighter_at_level_one(client)

    # A level-up draft advances exactly one Character Level, so walk the rail.
    for target in (2, 3, 4):
        view = _level_up(client, character_id, FIGHTER_RAIL[:target])
        if target == 4:
            view = _take_feat(client, view, "content:asi-feat", TOUGH)
        view = _finish(client, view)
        _assert_ready(client, view)
        S.http_confirm(client, view)

    versions = client.get(f"/api/characters/{character_id}/versions").json()
    assert [entry["version_no"] for entry in versions] == [1, 2, 3, 4]

    version_one = _build(client, character_id, 1)
    version_four = _build(client, character_id, 4)
    assert version_one["feat_refs"] == []
    assert version_one["static_derived_modifiers"] == []
    assert version_four["feat_refs"] == [TOUGH]
    assert version_four["static_derived_modifiers"][0]["target"] == "max_hp"

    sheet = client.get(f"/api/characters/{character_id}/sheet").json()
    assert TOUGH in {entry["key"] for entry in sheet["features"]}


# --- K-E2E-03 — prerequisite and non-repeatable rejection --------------------


def test_an_unmet_prerequisite_is_reported_and_blocks_confirm_without_side_effects() -> None:
    client, engine = S.seed_http()
    view = S.http_create_draft(
        client,
        _draft_payload(
            name="M01-K Blocked",
            race="phb2014:race:variant-human",
            levels=[_level(1, "fighter", hp=10)],
        ),
    )
    view = _finish(client, view)

    feat_choice = _choice(view, "content:race-feat")
    blocked = next(
        option
        for option in feat_choice["options"]
        if option["option_id"] == ELEMENTAL_ADEPT
    )
    assert blocked["disabled_reason_code"] == "feat_prerequisite_not_met"
    assert blocked["disabled_reason_params"]["requirements"] == [{"type": "spellcasting"}]

    before = client.get(f"/api/characters").json()
    view = _set_choice(client, view, feat_choice, [ELEMENTAL_ADEPT])
    review = _review(client, view)
    assert review["can_confirm"] is False
    assert "feat_prerequisite_not_met" in {issue["code"] for issue in review["issues"]}

    response = client.post(
        f"/api/character-builder/drafts/{view['draft']['id']}/confirm"
    )
    assert response.status_code >= 400
    assert client.get(f"/api/characters").json() == before


def test_a_second_non_repeatable_acquisition_is_rejected_by_the_server() -> None:
    client, _ = S.seed_http()
    view = S.http_create_draft(
        client,
        _draft_payload(
            name="M01-K Duplicate",
            race="phb2014:race:variant-human",
            levels=FIGHTER_RAIL,
        ),
    )
    view = _take_feat(client, view, "content:race-feat", TOUGH)
    view = _finish(client, view)

    asi_choice = _choice(view, "content:asi-feat")
    repeat = next(option for option in asi_choice["options"] if option["option_id"] == TOUGH)
    assert repeat["disabled_reason_code"] == "feat_not_repeatable"

    view = _set_choice(client, view, asi_choice, [TOUGH])
    review = _review(client, view)
    assert review["can_confirm"] is False
    assert "feat_not_repeatable" in {issue["code"] for issue in review["issues"]}


# --- K-E2E-04 — repeatable feat across two opportunities ----------------------


WIZARD_RAIL = [
    _level(1, "wizard", hp=6),
    _level(2, "wizard", hp=4, subclass_ref="srd5.1:subclass:evocation"),
    *[_level(index, "wizard", hp=4) for index in range(3, 9)],
]


def _wizard_spell_plan(client, view):
    """Fill the caster's permanent spell selections from the review summary."""

    review = _review(client, view)
    plan: dict[str, Any] = {}
    for profile in review["resolved_summary"]["spellcasting_profiles"]:
        taken: set[str] = set()
        cantrips = [
            option["spell_key"]
            for option in profile["available_spells"]
            if option["level"] == 0
        ][: profile["cantrip_count"]]
        taken.update(cantrips)
        leveled = [
            option["spell_key"]
            for option in profile["available_spells"]
            if option["level"] >= 1 and option["spell_key"] not in taken
        ]
        plan[profile["profile_id"]] = {
            "cantrip_keys": cantrips,
            "known_spell_keys": leveled[: profile["known_spell_count"]],
            "spellbook_spell_keys": leveled[: profile["spellbook_count"]],
        }
    return S.http_patch(client, view, {"spell_choices": plan})


def test_repeatable_feat_keeps_both_acquisitions_through_confirm_and_reload() -> None:
    client, _ = S.seed_http()
    view = S.http_create_draft(
        client,
        _draft_payload(name="M01-K Repeatable", race="srd5.1:race:human", levels=WIZARD_RAIL),
    )

    opportunities = [
        item for item in view["choices"] if item["option_source"] == "content:asi-feat"
    ]
    assert len(opportunities) == 2

    selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
    for opportunity in opportunities:
        selections[opportunity["choice_id"]] = {
            "choice_id": opportunity["choice_id"],
            "source_ref": opportunity.get("source_ref"),
            "selected_option_ids": [ELEMENTAL_ADEPT],
        }
    view = S.http_patch(client, view, {"choice_selections": selections})

    elements = [
        item for item in view["choices"] if item["option_source"] == "content:feat:enum"
    ]
    assert len(elements) == 2
    selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
    for child, value in zip(elements, ("enum:fire", "enum:cold"), strict=True):
        selections[child["choice_id"]] = {
            "choice_id": child["choice_id"],
            "source_ref": child.get("source_ref"),
            "selected_option_ids": [value],
        }
    view = S.http_patch(client, view, {"choice_selections": selections})

    view = _finish(client, view)
    view = _wizard_spell_plan(client, view)
    _assert_ready(client, view)

    confirmed = S.http_confirm(client, view)
    build = _build(client, confirmed["character_id"], 1)

    acquisitions = build["feat_acquisitions"]
    assert len(acquisitions) == 2
    assert {entry["feat_ref"] for entry in acquisitions} == {ELEMENTAL_ADEPT}
    assert len({entry["acquisition_id"] for entry in acquisitions}) == 2
    assert sorted(entry["selections"]["element"][0] for entry in acquisitions) == [
        "enum:cold",
        "enum:fire",
    ]
    # The unique summary is still a summary, not the source of truth.
    assert build["feat_refs"] == [ELEMENTAL_ADEPT]


# --- K-E2E-05 — non-Fighter Martial Adept -------------------------------------


def test_non_fighter_martial_adept_persists_maneuvers_and_its_resource() -> None:
    client, _ = S.seed_http()
    view = S.http_create_draft(
        client,
        _draft_payload(name="M01-K Martial Wizard", race="srd5.1:race:human", levels=WIZARD_RAIL),
    )
    view = _take_feat(client, view, "content:asi-feat", MARTIAL_ADEPT)

    maneuvers = _choice(view, "content:feat:maneuver")
    legal = [option["option_id"] for option in maneuvers["options"] if not option.get("disabled_reason")]
    assert len(legal) >= maneuvers["choose_count"]
    view = _set_choice(client, view, maneuvers, legal[: maneuvers["choose_count"]])

    view = _finish(client, view)
    view = _wizard_spell_plan(client, view)
    _assert_ready(client, view)

    confirmed = S.http_confirm(client, view)
    build = _build(client, confirmed["character_id"], 1)

    granted = [ref for ref in build["feature_refs"] if ":feature:maneuver-" in ref]
    assert sorted(granted) == sorted(legal[: maneuvers["choose_count"]])
    provenance = {
        entry["feature_ref"]: entry["source_ref"]
        for entry in build["feature_grant_sources"]
        if entry["feature_ref"] in granted
    }
    assert set(provenance.values()) == {MARTIAL_ADEPT}

    grant = next(
        entry for entry in build["feat_resource_grants"] if entry["resource_id"] == "superiority-dice"
    )
    assert grant["die_size"] == 6
    assert sorted(grant["recharge"]) == ["long_rest", "short_rest"]

    sheet = client.get(f"/api/characters/{confirmed['character_id']}/sheet").json()
    superiority = sheet["resources"]["feature:superiority-dice"]
    assert superiority["used"] == 0
    assert superiority["remaining"] == 1


# --- K-E2E-06 / 07 — casters select PHB-only spells ---------------------------


def test_a_caster_can_select_and_persist_a_phb_only_spell() -> None:
    client, _ = S.seed_http()
    view = S.http_create_draft(
        client,
        _draft_payload(name="M01-K Caster", race="srd5.1:race:human", levels=WIZARD_RAIL[:5]),
    )
    view = _finish(client, view)

    review = _review(client, view)
    profile = review["resolved_summary"]["spellcasting_profiles"][0]
    available = {option["spell_key"] for option in profile["available_spells"]}
    assert CHROMATIC_ORB in available

    cantrips = [
        option["spell_key"] for option in profile["available_spells"] if option["level"] == 0
    ][: profile["cantrip_count"]]
    leveled = [CHROMATIC_ORB] + [
        option["spell_key"]
        for option in profile["available_spells"]
        if option["level"] >= 1 and option["spell_key"] != CHROMATIC_ORB
    ]
    view = S.http_patch(
        client,
        view,
        {
            "spell_choices": {
                profile["profile_id"]: {
                    "cantrip_keys": cantrips,
                    "spellbook_spell_keys": leveled[: profile["spellbook_count"]],
                }
            }
        },
    )
    _assert_ready(client, view)

    confirmed = S.http_confirm(client, view)
    build = _build(client, confirmed["character_id"], 1)
    persisted = {
        entry["spell_key"]
        for entry in build["spell_access_entries"]
        if entry["access_type"] == "spellbook"
    }
    assert CHROMATIC_ORB in persisted


# --- K.13 restart / compatibility ---------------------------------------------


def test_feats_spells_and_versions_survive_a_service_restart() -> None:
    client, engine = S.seed_http()

    # 1. Variant Human with a static-derived PHB feat.
    view = S.http_create_draft(
        client,
        _draft_payload(
            name="M01-K Restart VH",
            race="phb2014:race:variant-human",
            levels=[_level(1, "fighter", hp=10)],
        ),
    )
    view = _take_feat(
        client, view, "content:race-feat", OBSERVANT, nested={"content:feat:ability": ["ability:wisdom"]}
    )
    view = _finish(client, view)
    variant_id = S.http_confirm(client, view)["character_id"]

    # 2. Repeatable feat across two ASI opportunities on a caster.
    view = S.http_create_draft(
        client,
        _draft_payload(name="M01-K Restart Wizard", race="srd5.1:race:human", levels=WIZARD_RAIL),
    )
    opportunities = [
        item for item in view["choices"] if item["option_source"] == "content:asi-feat"
    ]
    selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
    for opportunity in opportunities:
        selections[opportunity["choice_id"]] = {
            "choice_id": opportunity["choice_id"],
            "source_ref": opportunity.get("source_ref"),
            "selected_option_ids": [ELEMENTAL_ADEPT],
        }
    view = S.http_patch(client, view, {"choice_selections": selections})
    elements = [item for item in view["choices"] if item["option_source"] == "content:feat:enum"]
    selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
    for child, value in zip(elements, ("enum:fire", "enum:cold"), strict=True):
        selections[child["choice_id"]] = {
            "choice_id": child["choice_id"],
            "source_ref": child.get("source_ref"),
            "selected_option_ids": [value],
        }
    view = S.http_patch(client, view, {"choice_selections": selections})
    view = _finish(client, view)
    view = _wizard_spell_plan(client, view)
    wizard_id = S.http_confirm(client, view)["character_id"]

    before = {
        "variant_build": _build(client, variant_id, 1),
        "variant_sheet": client.get(f"/api/characters/{variant_id}/sheet").json(),
        "wizard_build": _build(client, wizard_id, 1),
        "wizard_versions": client.get(f"/api/characters/{wizard_id}/versions").json(),
    }

    restarted = S.rebind_http(engine)

    after = {
        "variant_build": restarted.get(f"/api/characters/{variant_id}/versions/1").json()["build"],
        "variant_sheet": restarted.get(f"/api/characters/{variant_id}/sheet").json(),
        "wizard_build": restarted.get(f"/api/characters/{wizard_id}/versions/1").json()["build"],
        "wizard_versions": restarted.get(f"/api/characters/{wizard_id}/versions").json(),
    }

    assert after == before
    assert after["wizard_build"]["feat_acquisitions"] != []
    assert len(after["wizard_build"]["feat_acquisitions"]) == 2
    assert after["variant_build"]["content_sources"] == before["variant_build"]["content_sources"]


def test_the_srd_grappler_identity_is_untouched_by_the_phb_catalog() -> None:
    content = S.registry()

    assert content.get_optional("srd5.1:feat:grappler") is not None
    assert content.get_optional("phb2014:feat:grappler") is None
    keys = {entry.key for entry in content.list_kind("feat")}
    assert len([key for key in keys if key.endswith(":feat:grappler")]) == 1


# --- Direct high-level create vs sequential level up --------------------------


def test_direct_high_level_create_matches_sequential_level_up() -> None:
    client, _ = S.seed_http()

    direct = S.http_create_draft(
        client,
        _draft_payload(name="M01-K Direct", race="srd5.1:race:human", levels=FIGHTER_RAIL),
    )
    direct = _take_feat(client, direct, "content:asi-feat", TOUGH)
    direct = _finish(client, direct)
    direct_id = S.http_confirm(client, direct)["character_id"]

    sequential_id = _fighter_at_level_one(client, name="M01-K Sequential")
    for target in (2, 3, 4):
        view = _level_up(client, sequential_id, FIGHTER_RAIL[:target])
        if target == 4:
            view = _take_feat(client, view, "content:asi-feat", TOUGH)
        view = _finish(client, view)
        review = _review(client, view)
        assert review["can_confirm"] is True, (target, review["issues"])
        S.http_confirm(client, view)

    direct_build = _build(client, direct_id, 1)
    sequential_build = _build(client, sequential_id, 4)

    assert direct_build["feat_refs"] == sequential_build["feat_refs"] == [TOUGH]
    assert direct_build["static_derived_modifiers"] == sequential_build["static_derived_modifiers"]
    assert direct_build["class_progression"] == sequential_build["class_progression"]

    direct_sheet = client.get(f"/api/characters/{direct_id}/sheet").json()
    sequential_sheet = client.get(f"/api/characters/{sequential_id}/sheet").json()
    assert direct_sheet["max_hp"] == sequential_sheet["max_hp"]
    assert direct_sheet["passive_perception"] == sequential_sheet["passive_perception"]
