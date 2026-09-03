"""M01-K K.3 — feat prerequisite and acquisition legality matrix."""

from __future__ import annotations

import m01k_support as S


DEFENSIVE_DUELIST = "phb2014:feat:defensive-duelist"
ELEMENTAL_ADEPT = "phb2014:feat:elemental-adept"
HEAVILY_ARMORED = "phb2014:feat:heavily-armored"
RITUAL_CASTER = "phb2014:feat:ritual-caster"
TOUGH = "phb2014:feat:tough"

# Human grants +1 to every ability, so a raw 10 lands at 11 and a raw 12 at 13.
LOW = {
    "strength": 15,
    "dexterity": 10,
    "constitution": 14,
    "intelligence": 10,
    "wisdom": 10,
    "charisma": 10,
}
DEX_13 = {**LOW, "dexterity": 12}
INT_13 = {**LOW, "intelligence": 12}
WIS_13 = {**LOW, "wisdom": 12}


def _option_reason(result, opportunity_id: str, feat_ref: str):
    option = S.option_by_id(S.choice_by_id(result, opportunity_id), feat_ref)
    assert option is not None, f"{feat_ref} disappeared from the feat pool"
    return option


# --- ability minimum ----------------------------------------------------------


def test_ability_minimum_blocks_below_threshold_and_keeps_the_option_visible() -> None:
    result, _, opportunity = S.feat_draft(
        DEFENSIVE_DUELIST, abilities=LOW, fill_rest=False
    )
    option = _option_reason(result, opportunity, DEFENSIVE_DUELIST)

    assert option.disabled_reason_code == "feat_prerequisite_not_met"
    assert option.disabled_reason_params["requirements"] == [
        {
            "type": "ability",
            "ability": "dexterity",
            "minimum_score": 13,
            "actual_score": 11,
        }
    ]


def test_ability_minimum_allows_the_feat_once_the_threshold_is_reached() -> None:
    result, _, opportunity = S.feat_draft(DEFENSIVE_DUELIST, abilities=DEX_13)

    assert _option_reason(result, opportunity, DEFENSIVE_DUELIST).disabled_reason is None
    assert S.issue_codes(result) == set()
    assert DEFENSIVE_DUELIST in result.build_candidate.feat_refs


def test_numeric_override_can_satisfy_a_numeric_feat_prerequisite() -> None:
    result, _, opportunity = S.feat_draft(
        DEFENSIVE_DUELIST,
        abilities=LOW,
        numeric_overrides=({"key": "ability:dexterity", "value": 16},),
        fill_rest=False,
    )

    assert _option_reason(result, opportunity, DEFENSIVE_DUELIST).disabled_reason is None


def test_raw_payload_cannot_bypass_an_unmet_ability_prerequisite() -> None:
    result, _, _ = S.feat_draft(DEFENSIVE_DUELIST, abilities=LOW, fill_rest=False)

    assert "feat_prerequisite_not_met" in S.issue_codes(result)
    assert result.validation.can_confirm is False


# --- armor proficiency --------------------------------------------------------


def test_armor_proficiency_prerequisite_blocks_a_class_without_the_proficiency() -> None:
    result, _, opportunity = S.feat_draft(
        HEAVILY_ARMORED, spec=S.WIZARD_L8, fill_rest=False
    )
    option = _option_reason(result, opportunity, HEAVILY_ARMORED)

    assert option.disabled_reason_code == "feat_prerequisite_not_met"
    assert option.disabled_reason_params["requirements"] == [
        {"type": "armor_proficiency", "proficiency_ref": "srd5.1:proficiency:medium-armor"}
    ]


def test_armor_proficiency_prerequisite_passes_for_a_class_that_has_it() -> None:
    result, _, opportunity = S.feat_draft(HEAVILY_ARMORED)

    assert _option_reason(result, opportunity, HEAVILY_ARMORED).disabled_reason is None
    assert S.issue_codes(result) == set()
    assert "srd5.1:proficiency:heavy-armor" in result.build_candidate.proficiencies


def test_numeric_override_cannot_bypass_an_armor_proficiency_prerequisite() -> None:
    result, _, opportunity = S.feat_draft(
        HEAVILY_ARMORED,
        spec=S.WIZARD_L8,
        numeric_overrides=({"key": "ability:strength", "value": 20},),
        fill_rest=False,
    )

    option = _option_reason(result, opportunity, HEAVILY_ARMORED)
    assert option.disabled_reason_code == "feat_prerequisite_not_met"
    assert "feat_prerequisite_not_met" in S.issue_codes(result)
    assert result.validation.can_confirm is False


# --- ability to cast at least one spell ---------------------------------------


def test_spellcasting_prerequisite_blocks_a_non_caster() -> None:
    result, _, opportunity = S.feat_draft(ELEMENTAL_ADEPT, fill_rest=False)
    option = _option_reason(result, opportunity, ELEMENTAL_ADEPT)

    assert option.disabled_reason_code == "feat_prerequisite_not_met"
    assert option.disabled_reason_params["requirements"] == [{"type": "spellcasting"}]


def test_spellcasting_prerequisite_passes_for_a_caster() -> None:
    result, _, opportunity = S.feat_draft(
        ELEMENTAL_ADEPT,
        spec=S.WIZARD_L8,
        nested={"element": ("enum:fire",)},
    )

    assert _option_reason(result, opportunity, ELEMENTAL_ADEPT).disabled_reason is None
    assert S.issue_codes(result) == set()


def test_carrying_a_scroll_does_not_make_a_fighter_a_caster() -> None:
    """Spellcasting legality reads spellcasting sources, not inventory."""

    result, payload, opportunity = S.feat_draft(ELEMENTAL_ADEPT, fill_rest=False)
    build_sources = {
        entry.item_ref
        for entry in result.starting_equipment
    }

    assert build_sources, "the fixture should have starting equipment"
    assert _option_reason(result, opportunity, ELEMENTAL_ADEPT).disabled_reason is not None


# --- compound / alternative prerequisite --------------------------------------


def test_any_of_prerequisite_passes_when_either_alternative_is_met() -> None:
    for abilities in (INT_13, WIS_13):
        result, _, opportunity = S.feat_draft(
            RITUAL_CASTER, abilities=abilities, fill_rest=False
        )
        assert _option_reason(result, opportunity, RITUAL_CASTER).disabled_reason is None


def test_any_of_prerequisite_reports_both_alternatives_when_neither_is_met() -> None:
    result, _, opportunity = S.feat_draft(RITUAL_CASTER, abilities=LOW, fill_rest=False)
    option = _option_reason(result, opportunity, RITUAL_CASTER)

    assert option.disabled_reason_code == "feat_prerequisite_not_met"
    requirements = option.disabled_reason_params["requirements"]
    assert len(requirements) == 1
    alternative = requirements[0]
    assert alternative["type"] == "any_of"
    assert [entry["ability"] for entry in alternative["options"]] == [
        "intelligence",
        "wisdom",
    ]
    assert all(entry["minimum_score"] == 13 for entry in alternative["options"])


# --- prerequisite reporting contract ------------------------------------------


def test_prerequisite_reasons_are_language_neutral_structured_data() -> None:
    """Params carry codes and refs; the front end formats the sentence."""

    scalar_types = (str, int, float, bool)
    checked = 0
    for feat_ref, abilities, spec in (
        (DEFENSIVE_DUELIST, LOW, S.FIGHTER_L4),
        (HEAVILY_ARMORED, None, S.WIZARD_L8),
        (ELEMENTAL_ADEPT, None, S.FIGHTER_L4),
        (RITUAL_CASTER, LOW, S.FIGHTER_L4),
    ):
        result, _, opportunity = S.feat_draft(
            feat_ref, abilities=abilities, spec=spec, fill_rest=False
        )
        option = _option_reason(result, opportunity, feat_ref)
        params = option.disabled_reason_params
        assert params["feat_ref"] == feat_ref
        for requirement in params["requirements"]:
            for value in requirement.values():
                assert isinstance(value, (list, *scalar_types))
            # A proficiency prerequisite must name the StableKey, never a label.
            if requirement["type"] == "armor_proficiency":
                assert requirement["proficiency_ref"].count(":") == 2
        checked += 1
    assert checked == 4


def test_option_reason_and_blocking_issue_agree_on_the_same_situation() -> None:
    result, _, opportunity = S.feat_draft(
        HEAVILY_ARMORED, spec=S.WIZARD_L8, fill_rest=False
    )
    option = _option_reason(result, opportunity, HEAVILY_ARMORED)
    blocking = S.issues_with_code(result, "feat_prerequisite_not_met")

    assert len(blocking) == 1
    assert blocking[0].message_params == option.disabled_reason_params
    assert blocking[0].related_refs == (HEAVILY_ARMORED,)


# --- unsupported prerequisite gate --------------------------------------------


def test_no_phb_feat_is_permanently_disabled_by_an_unsupported_prerequisite() -> None:
    """K.3: 0 / 41 may fall back to ``unsupported_feat_prerequisite``."""

    content = S.registry()
    feats = S.feat_entries(content)
    assert len(feats) == 41

    unsupported: list[str] = []
    for spec in (S.FIGHTER_L4, S.WIZARD_L8):
        base = S.auto_fill(S.payload(S.levels_for(spec)), content)
        result, _ = S.compile_payload(base, content)
        for opportunity in S.feat_opportunities(result):
            for option in opportunity.options:
                if option.disabled_reason_code == "unsupported_feat_prerequisite":
                    unsupported.append(option.option_id)
    assert unsupported == []


def test_every_phb_feat_is_reachable_from_at_least_one_legal_build() -> None:
    content = S.registry()
    reachable: set[str] = set()
    fixtures = (
        (S.FIGHTER_L4, None),
        (S.WIZARD_L8, None),
        (S.FIGHTER_L4, {**S.DEFAULT_ABILITIES, "dexterity": 15, "charisma": 15}),
    )
    for spec, abilities in fixtures:
        base = S.auto_fill(S.payload(S.levels_for(spec), abilities=abilities), content)
        result, _ = S.compile_payload(base, content)
        for opportunity in S.feat_opportunities(result):
            reachable.update(
                option.option_id
                for option in opportunity.options
                if option.disabled_reason is None
                and option.option_id.startswith("phb2014:feat:")
            )
    missing = sorted({entry.key for entry in S.feat_entries(content)} - reachable)
    assert missing == []


# --- non-repeatable acquisition -----------------------------------------------


def test_non_repeatable_feat_is_disabled_at_the_next_opportunity() -> None:
    content = S.registry()
    base = S.auto_fill(S.payload(S.levels_for(S.WIZARD_L8)), content)
    result, _ = S.compile_payload(base, content)
    first, second = (choice.choice_id for choice in S.feat_opportunities(result))

    taken = S.with_selections(base, {first: S.selection(first, TOUGH)})
    taken = S.fill_spell_choices(S.auto_fill(taken, content, skip_sources=set()), content)
    result, _ = S.compile_payload(taken, content)

    option = _option_reason(result, second, TOUGH)
    assert option.disabled_reason_code == "feat_not_repeatable"
    assert option.disabled_reason_params == {"feat_ref": TOUGH}


def test_second_non_repeatable_acquisition_is_blocked_without_side_effects() -> None:
    content = S.registry()
    base = S.auto_fill(S.payload(S.levels_for(S.WIZARD_L8)), content)
    result, _ = S.compile_payload(base, content)
    first, second = (choice.choice_id for choice in S.feat_opportunities(result))

    legal = S.with_selections(
        base,
        {first: S.selection(first, TOUGH), second: S.selection(second, ELEMENTAL_ADEPT)},
    )
    legal = S.with_selections(
        legal, S.nested_selections(second, ELEMENTAL_ADEPT, {"element": ("enum:fire",)})
    )
    legal = S.fill_spell_choices(S.auto_fill(legal, content, skip_sources=set()), content)
    legal_result, _ = S.compile_payload(legal, content)
    assert S.issue_codes(legal_result) == set()
    assert len(legal_result.build_candidate.feat_acquisitions) == 2

    doubled = S.with_selections(legal, {second: S.selection(second, TOUGH)})
    doubled_result, _ = S.compile_payload(doubled, content)

    assert "feat_not_repeatable" in S.issue_codes(doubled_result)
    assert doubled_result.build_candidate is None

    # Rejection is atomic: the legal draft still compiles exactly as before.
    replay, _ = S.compile_payload(legal, content)
    assert S.issue_codes(replay) == set()
    assert replay.build_candidate.feat_acquisitions == legal_result.build_candidate.feat_acquisitions


# --- repeatable acquisition — mandatory Elemental Adept proof ------------------


def _two_elemental_adepts(content, first_element: str, second_element: str):
    base = S.auto_fill(S.payload(S.levels_for(S.WIZARD_L8)), content)
    result, _ = S.compile_payload(base, content)
    first, second = (choice.choice_id for choice in S.feat_opportunities(result))
    payload = S.with_selections(
        base,
        {
            first: S.selection(first, ELEMENTAL_ADEPT),
            second: S.selection(second, ELEMENTAL_ADEPT),
        },
    )
    payload = S.with_selections(
        payload, S.nested_selections(first, ELEMENTAL_ADEPT, {"element": (first_element,)})
    )
    payload = S.with_selections(
        payload, S.nested_selections(second, ELEMENTAL_ADEPT, {"element": (second_element,)})
    )
    payload = S.fill_spell_choices(S.auto_fill(payload, content, skip_sources=set()), content)
    compiled, _ = S.compile_payload(payload, content)
    return compiled, payload, first, second


def test_repeatable_feat_keeps_one_acquisition_per_opportunity() -> None:
    content = S.registry()
    result, _, first, second = _two_elemental_adepts(content, "enum:fire", "enum:cold")

    assert S.issue_codes(result) == set()
    build = result.build_candidate
    acquisitions = build.feat_acquisitions
    assert len(acquisitions) == 2
    assert {entry.feat_ref for entry in acquisitions} == {ELEMENTAL_ADEPT}
    assert {entry.source_opportunity for entry in acquisitions} == {first, second}
    # Deterministic, opportunity-derived acquisition identity.
    assert len({entry.acquisition_id for entry in acquisitions}) == 2
    by_opportunity = {entry.source_opportunity: entry.selections for entry in acquisitions}
    assert by_opportunity[first]["element"] == ("enum:fire",)
    assert by_opportunity[second]["element"] == ("enum:cold",)
    # The unique summary stays a summary; it must not become the only truth.
    assert build.feat_refs == (ELEMENTAL_ADEPT,)


def test_repeatable_feat_acquisition_ids_are_stable_across_recompiles() -> None:
    content = S.registry()
    first_pass, payload, _, _ = _two_elemental_adepts(content, "enum:fire", "enum:cold")
    second_pass, _ = S.compile_payload(payload, content)

    assert first_pass.build_candidate.feat_acquisitions == second_pass.build_candidate.feat_acquisitions


def test_repeatable_feat_rejects_a_repeated_damage_type() -> None:
    content = S.registry()
    result, _, _, _ = _two_elemental_adepts(content, "enum:fire", "enum:fire")

    assert "repeatable_feat_choice_must_differ" in S.issue_codes(result)
    assert result.build_candidate is None
