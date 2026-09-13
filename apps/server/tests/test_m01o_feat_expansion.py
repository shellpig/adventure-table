"""M01-O — XGE/TCE feat expansion runs through the real builder pipeline."""

from __future__ import annotations

import m01k_support as S
from app.content.localization_files import load_content_localization_catalog
from app.paths import resolve_content_root


PRODIGY = "xge:feat:prodigy"
SQUAT_NIMBLENESS = "xge:feat:squat-nimbleness"
ARTIFICER_INITIATE = "tce:feat:artificer-initiate"
ELDRITCH_ADEPT = "tce:feat:eldritch-adept"
FEY_TOUCHED = "tce:feat:fey-touched"
GUNNER = "tce:feat:gunner"
METAMAGIC_ADEPT = "tce:feat:metamagic-adept"
SKILL_EXPERT = "tce:feat:skill-expert"


def _feat_option(result, feat_ref: str):
    for choice in S.feat_opportunities(result):
        for option in choice.options:
            if option.option_id == feat_ref:
                return option
    raise AssertionError(f"missing feat option {feat_ref}")


def _available_result(*, race: str = "srd5.1:race:human", levels=None, spec=S.FIGHTER_L4):
    content = S.registry()
    base = S.auto_fill(
        S.payload(levels or S.levels_for(spec), race=race),
        content,
    )
    return S.compile_payload(base, content)[0]


def _child(result, opportunity_id: str, field: str):
    return S.choice_by_id(result, S.child_choice_id(opportunity_id, field))


def _spell_entry(build, spell_key: str):
    matches = [
        entry
        for entry in build.spell_access_entries
        if entry.spell_key == spell_key and entry.source_type == "feat"
    ]
    assert matches, f"missing spell access {spell_key}"
    return matches[0]


def test_m01o_inventory_and_locale_overlay_are_registered() -> None:
    content = S.registry()
    catalog = load_content_localization_catalog(content, resolve_content_root())

    assert len([entry for entry in content.list_kind("feat", source="xge") if entry.key.startswith("xge:feat:")]) == 15
    assert len([entry for entry in content.list_kind("feat", source="tce") if entry.key.startswith("tce:feat:")]) == 15
    assert catalog.resolve_name(PRODIGY, "zh-TW").value == "奇才"
    assert catalog.resolve_name(METAMAGIC_ADEPT, "zh-TW").value == "超魔學徒"


def test_variant_human_counts_as_human_ancestry_for_xge_racial_feats() -> None:
    human = _available_result(race="phb2014:race:variant-human")
    dragonborn = _available_result(race="srd5.1:race:dragonborn")

    assert _feat_option(human, PRODIGY).disabled_reason is None
    assert _feat_option(dragonborn, PRODIGY).disabled_reason_code == "feat_prerequisite_not_met"


def test_size_or_dwarf_prerequisite_and_allowed_skill_options_are_enforced() -> None:
    small_ancestry = _available_result(race="vgm:race:goblin")
    human = _available_result(race="srd5.1:race:human")
    assert _feat_option(small_ancestry, SQUAT_NIMBLENESS).disabled_reason is None
    assert _feat_option(human, SQUAT_NIMBLENESS).disabled_reason_code == "feat_prerequisite_not_met"

    result, _, opportunity = S.feat_draft(
        SQUAT_NIMBLENESS,
        race="vgm:race:goblin",
        nested={
            "ability": ("ability:dexterity",),
            "skill": ("srd5.1:proficiency:skill-acrobatics",),
        },
        fill_rest=False,
    )

    assert {
        option.option_id
        for option in _child(result, opportunity, "skill").options
    } == {
        "srd5.1:proficiency:skill-acrobatics",
        "srd5.1:proficiency:skill-athletics",
    }


def test_subclass_spellcasting_satisfies_tce_spellcasting_prerequisite() -> None:
    eldritch_knight_levels = S.class_levels(
        "fighter",
        4,
        first_hp=10,
        later_hp=6,
        subclass_ref="phb2014:subclass:eldritch-knight",
        subclass_level=3,
    )
    champion = _available_result(spec=S.FIGHTER_L4)
    eldritch_knight = _available_result(levels=eldritch_knight_levels)

    assert _feat_option(champion, ELDRITCH_ADEPT).disabled_reason_code == "feat_prerequisite_not_met"
    assert _feat_option(eldritch_knight, ELDRITCH_ADEPT).disabled_reason is None


def test_skill_expert_grants_selected_skill_and_matching_expertise() -> None:
    result, _, _ = S.feat_draft(
        SKILL_EXPERT,
        spec=S.WIZARD_L8,
        nested={
            "ability": ("ability:intelligence",),
            "skill": ("srd5.1:proficiency:skill-investigation",),
            "expertise": ("srd5.1:skill:investigation",),
        },
    )
    build = result.build_candidate

    assert S.issue_codes(result) == set()
    assert "srd5.1:skill:investigation" in build.skill_choices
    assert "srd5.1:skill:investigation" in build.skill_expertise_refs


def test_artificer_initiate_grants_artificer_spells_and_selected_tool() -> None:
    result, _, _ = S.feat_draft(
        ARTIFICER_INITIATE,
        spec=S.WIZARD_L8,
        nested={
            "tool": ("srd5.1:proficiency:tinkers-tools",),
            "cantrip": ("srd5.1:spell:mending",),
            "spell": ("srd5.1:spell:cure-wounds",),
        },
    )
    build = result.build_candidate

    assert S.issue_codes(result) == set()
    assert "srd5.1:proficiency:tinkers-tools" in build.proficiencies
    cantrip = _spell_entry(build, "srd5.1:spell:mending")
    spell = _spell_entry(build, "srd5.1:spell:cure-wounds")
    assert cantrip.casting_ability == "intelligence"
    assert cantrip.uses_per_rest is None
    assert spell.casting_ability == "intelligence"
    assert spell.uses_per_rest == 1
    assert spell.recharge_types == ("long_rest",)


def test_fey_touched_links_fixed_and_selected_spells_to_chosen_ability() -> None:
    result, _, _ = S.feat_draft(
        FEY_TOUCHED,
        spec=S.WIZARD_L8,
        nested={
            "ability": ("ability:wisdom",),
            "spell": ("srd5.1:spell:charm-person",),
        },
    )
    build = result.build_candidate

    assert S.issue_codes(result) == set()
    for spell_key in ("srd5.1:spell:misty-step", "srd5.1:spell:charm-person"):
        entry = _spell_entry(build, spell_key)
        assert entry.casting_ability == "wisdom"
        assert entry.uses_per_rest == 1
        assert entry.recharge_types == ("long_rest",)


def test_metamagic_adept_grants_distinct_options_and_restricted_resource() -> None:
    result, _, _ = S.feat_draft(
        METAMAGIC_ADEPT,
        spec=S.WIZARD_L8,
        nested={
            "metamagic": (
                "srd5.1:feature:metamagic-careful-spell",
                "srd5.1:feature:metamagic-subtle-spell",
            ),
        },
    )
    build = result.build_candidate

    assert S.issue_codes(result) == set()
    assert "srd5.1:feature:metamagic-careful-spell" in build.feature_refs
    grant = next(
        resource
        for resource in build.feat_resource_grants
        if resource.resource_id == "metamagic-adept-sorcery-points"
    )
    assert grant.capacity == 2
    assert grant.recharge == ("long_rest",)
    assert grant.allowed_spend_tags == ("metamagic",)


def test_gunner_keeps_firearms_as_deferred_typed_fact() -> None:
    data = S.registry().get(GUNNER).data

    assert data["automation"] == "structured_deferred_combat"
    assert data["weapon_proficiency_categories"] == ["firearms"]
    assert "srd5.1:proficiency:firearms" not in data.get("proficiency_grants", [])
