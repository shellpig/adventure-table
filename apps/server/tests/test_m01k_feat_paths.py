"""M01-K K.5 — Variant Human and ASI feat paths share one inventory and resolver."""

from __future__ import annotations

import m01k_support as S


VARIANT_HUMAN = "phb2014:race:variant-human"
RESILIENT = "phb2014:feat:resilient"
HEAVILY_ARMORED = "phb2014:feat:heavily-armored"
MAGIC_INITIATE = "phb2014:feat:magic-initiate"

LOW_DEX = {
    "strength": 15,
    "dexterity": 10,
    "constitution": 14,
    "intelligence": 12,
    "wisdom": 12,
    "charisma": 10,
}


def _pool(result, opportunity_id: str) -> dict[str, str | None]:
    choice = S.choice_by_id(result, opportunity_id)
    return {
        option.option_id: option.disabled_reason_code
        for option in choice.options
        if option.option_id.startswith(("phb2014:feat:", "srd5.1:feat:"))
    }


def _variant_human_pool(content, *, abilities=None):
    base = S.auto_fill(
        S.payload(S.levels_for(S.FIGHTER_L4), race=VARIANT_HUMAN, abilities=abilities),
        content,
    )
    result, _ = S.compile_payload(base, content)
    opportunity = S.choice_by_source(result, "content:race-feat")
    return result, base, opportunity.choice_id


def _asi_pool(content, *, abilities=None):
    base = S.auto_fill(S.payload(S.levels_for(S.FIGHTER_L4), abilities=abilities), content)
    result, _ = S.compile_payload(base, content)
    opportunity = S.choice_by_source(result, "content:asi-feat")
    return result, base, opportunity.choice_id


def test_both_paths_offer_the_same_feat_inventory() -> None:
    content = S.registry()
    variant_result, _, variant_opportunity = _variant_human_pool(content)
    asi_result, _, asi_opportunity = _asi_pool(content)

    variant_feats = set(_pool(variant_result, variant_opportunity))
    asi_feats = set(_pool(asi_result, asi_opportunity))

    assert variant_feats == asi_feats
    assert len(variant_feats) == 42  # 41 PHB non-SRD feats plus SRD Grappler
    assert "srd5.1:feat:grappler" in variant_feats


def test_both_paths_apply_the_same_prerequisite_resolver() -> None:
    """One Variant Human fighter has both opportunities, so the only variable
    left between the two pools is which code path evaluated them."""

    content = S.registry()
    base = S.auto_fill(
        S.payload(S.levels_for(S.FIGHTER_L4), race=VARIANT_HUMAN, abilities=LOW_DEX),
        content,
    )
    result, _ = S.compile_payload(base, content)
    origin = S.choice_by_source(result, "content:race-feat").choice_id
    asi = S.choice_by_source(result, "content:asi-feat").choice_id

    assert _pool(result, origin) == _pool(result, asi)

    # And the reason payloads match, not just the enabled/disabled flags.
    for feat_ref in ("phb2014:feat:defensive-duelist", "phb2014:feat:elemental-adept"):
        origin_option = S.option_by_id(S.choice_by_id(result, origin), feat_ref)
        asi_option = S.option_by_id(S.choice_by_id(result, asi), feat_ref)
        assert origin_option.disabled_reason_code == asi_option.disabled_reason_code
        assert origin_option.disabled_reason_params == asi_option.disabled_reason_params


def test_both_paths_expose_the_same_nested_choices_for_a_structural_feat() -> None:
    content = S.registry()
    variant_result, _, variant_opportunity = S.feat_draft(
        MAGIC_INITIATE,
        race=VARIANT_HUMAN,
        content=content,
        nested={"spell-source": ("srd5.1:class:wizard",)},
        fill_rest=False,
    )
    asi_result, _, asi_opportunity = S.feat_draft(
        MAGIC_INITIATE,
        content=content,
        nested={"spell-source": ("srd5.1:class:wizard",)},
        fill_rest=False,
    )

    for field in ("spell-source", "cantrips", "spell"):
        variant_choice = S.choice_by_id(variant_result, S.child_choice_id(variant_opportunity, field))
        asi_choice = S.choice_by_id(asi_result, S.child_choice_id(asi_opportunity, field))
        assert variant_choice.option_source == asi_choice.option_source
        assert variant_choice.choose_count == asi_choice.choose_count
        assert [option.option_id for option in variant_choice.options] == [
            option.option_id for option in asi_choice.options
        ]


def test_both_paths_compile_the_same_permanent_grants() -> None:
    content = S.registry()
    nested = {"ability": ("ability:wisdom",)}
    variant_result, _, _ = S.feat_draft(
        RESILIENT, race=VARIANT_HUMAN, content=content, nested=nested
    )
    asi_result, _, _ = S.feat_draft(RESILIENT, content=content, nested=nested)

    assert S.issue_codes(variant_result) == set()
    assert S.issue_codes(asi_result) == set()
    variant_build = variant_result.build_candidate
    asi_build = asi_result.build_candidate

    assert variant_build.feat_refs == asi_build.feat_refs == (RESILIENT,)
    assert "srd5.1:ability:wis" in variant_build.saving_throw_proficiencies
    assert "srd5.1:ability:wis" in asi_build.saving_throw_proficiencies
    assert [entry.selections for entry in variant_build.feat_acquisitions] == [
        entry.selections for entry in asi_build.feat_acquisitions
    ]


def test_both_paths_record_the_acquisition_against_their_own_opportunity() -> None:
    content = S.registry()
    variant_result, _, variant_opportunity = S.feat_draft(
        HEAVILY_ARMORED, race=VARIANT_HUMAN, content=content
    )
    asi_result, _, asi_opportunity = S.feat_draft(HEAVILY_ARMORED, content=content)

    variant_acquisition = variant_result.build_candidate.feat_acquisitions[0]
    asi_acquisition = asi_result.build_candidate.feat_acquisitions[0]

    assert variant_acquisition.source_opportunity == variant_opportunity
    assert asi_acquisition.source_opportunity == asi_opportunity
    assert variant_acquisition.acquisition_id != asi_acquisition.acquisition_id
    assert variant_acquisition.feat_ref == asi_acquisition.feat_ref


def test_a_feat_taken_as_variant_human_cannot_be_repeated_at_an_asi() -> None:
    """Acquisition legality is one rule across both paths, not two."""

    content = S.registry()
    base = S.auto_fill(
        S.payload(S.levels_for(S.FIGHTER_L4), race=VARIANT_HUMAN), content
    )
    result, _ = S.compile_payload(base, content)
    origin = S.choice_by_source(result, "content:race-feat").choice_id
    asi = S.choice_by_source(result, "content:asi-feat").choice_id

    taken = S.with_selections(base, {origin: S.selection(origin, HEAVILY_ARMORED)})
    taken = S.auto_fill(taken, content, skip_sources=S.FEAT_OPPORTUNITY_SOURCES)
    taken_result, _ = S.compile_payload(taken, content)

    option = S.option_by_id(S.choice_by_id(taken_result, asi), HEAVILY_ARMORED)
    assert option.disabled_reason_code == "feat_not_repeatable"

    forced = S.with_selections(taken, {asi: S.selection(asi, HEAVILY_ARMORED)})
    forced_result, _ = S.compile_payload(forced, content)
    assert "feat_not_repeatable" in S.issue_codes(forced_result)
    assert forced_result.validation.can_confirm is False
