"""M01-O — XGE/TCE feat expansion runs through the real builder pipeline."""

from __future__ import annotations

import m01k_support as S
import m01m_support
from app.content.localization_files import load_content_localization_catalog
from app.paths import resolve_content_root


PRODIGY = "xge:feat:prodigy"
SQUAT_NIMBLENESS = "xge:feat:squat-nimbleness"
DRAGON_FEAR = "xge:feat:dragon-fear"
DROW_HIGH_MAGIC = "xge:feat:drow-high-magic"
ELVEN_ACCURACY = "xge:feat:elven-accuracy"
INFERNAL_CONSTITUTION = "xge:feat:infernal-constitution"
FLAMES_OF_PHLEGETHOS = "xge:feat:flames-of-phlegethos"
ARTIFICER_INITIATE = "tce:feat:artificer-initiate"
CHEF = "tce:feat:chef"
ELDRITCH_ADEPT = "tce:feat:eldritch-adept"
FEY_TOUCHED = "tce:feat:fey-touched"
FIGHTING_INITIATE = "tce:feat:fighting-initiate"
GUNNER = "tce:feat:gunner"
METAMAGIC_ADEPT = "tce:feat:metamagic-adept"
POISONER = "tce:feat:poisoner"
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


def test_selecting_a_feat_with_an_unmet_origin_prerequisite_reports_a_structured_issue() -> None:
    # Ancestry / lineage / size failures must serialize into BuilderIssue params
    # instead of crashing the compile when a client patches a disabled option.
    result, _, _ = S.feat_draft(
        SQUAT_NIMBLENESS,
        race="srd5.1:race:human",
        nested={"ability": ("ability:strength",)},
        fill_rest=False,
    )

    assert "feat_prerequisite_not_met" in S.issue_codes(result)
    issue = next(issue for issue in result.validation.issues if issue.code == "feat_prerequisite_not_met")
    assert issue.message_params["requirements"][0]["type"] == "any_of"


def test_eldritch_adept_offers_the_canonical_invocation_pool_with_warlock_only_prerequisites() -> None:
    result, _, opportunity = S.feat_draft(ELDRITCH_ADEPT, spec=S.WIZARD_L8, fill_rest=False)
    options = {option.option_id: option for option in _child(result, opportunity, "invocation").options}

    assert "srd5.1:feature:eldritch-invocation-devils-sight" in options
    assert options["srd5.1:feature:eldritch-invocation-devils-sight"].disabled_reason is None
    assert options["tce:feature:eldritch-mind"].disabled_reason is None
    assert (
        options["srd5.1:feature:eldritch-invocation-agonizing-blast"].disabled_reason_code
        == "feat_invocation_prerequisite_not_met"
    )
    assert (
        options["srd5.1:feature:eldritch-invocation-mire-the-mind"].disabled_reason_params["required_warlock_level"]
        == 5
    )

    legal, _, _ = S.feat_draft(
        ELDRITCH_ADEPT,
        spec=S.WIZARD_L8,
        nested={"invocation": ("srd5.1:feature:eldritch-invocation-devils-sight",)},
    )
    assert S.issue_codes(legal) == set()
    assert "srd5.1:feature:eldritch-invocation-devils-sight" in legal.build_candidate.feature_refs


def test_dragon_hide_natural_armor_joins_the_unarmored_ac_candidates() -> None:
    from app.domain.character.schemas import CharacterState
    from app.domain.rules.armor_class import calculate_armor_class

    result, _, _ = S.feat_draft(
        "xge:feat:dragon-hide",
        race="srd5.1:race:dragonborn",
        nested={"ability": ("ability:strength",)},
    )
    build = result.build_candidate
    dexterity_modifier = (build.ability_scores.dexterity - 10) // 2

    assert S.issue_codes(result) == set()
    assert calculate_armor_class(build, CharacterState(current_hp=10), S.registry()) == 13 + dexterity_modifier


def test_squat_nimbleness_adds_five_feet_to_walking_speed_once() -> None:
    result, _, _ = S.feat_draft(
        SQUAT_NIMBLENESS,
        race="vgm:race:goblin",
        spec=S.WIZARD_L8,
        nested={"ability": ("ability:dexterity",), "skill": ("srd5.1:proficiency:skill-athletics",)},
    )

    assert S.issue_codes(result) == set()
    assert result.build_candidate.walking_speed == S.registry().get("vgm:race:goblin").data["speed"] + 5


def test_fighting_initiate_excludes_the_style_the_fighter_already_knows() -> None:
    result, _, opportunity = S.feat_draft("tce:feat:fighting-initiate", spec=S.FIGHTER_L4)
    build = result.build_candidate
    feat_style = build.feat_acquisitions[0].selections["style"][0]
    class_style = next(
        ref for ref in build.feature_refs if ref.startswith("srd5.1:feature:fighter-fighting-style-") and ref != feat_style
    )
    options = {option.option_id: option for option in _child(result, opportunity, "style").options}

    assert S.issue_codes(result) == set()
    assert options[class_style].disabled_reason_code == "feat_fighting_style_already_known"
    assert options[feat_style].disabled_reason is None
    assert "tce:feature:blessed-warrior" not in options


def test_class_fighting_style_slot_disables_the_style_a_feat_already_granted() -> None:
    result, _, _ = S.feat_draft(
        "tce:feat:fighting-initiate",
        race="phb2014:race:variant-human",
        spec=S.FIGHTER_L4,
        nested={"style": ("srd5.1:feature:fighter-fighting-style-defense",)},
        fill_rest=False,
    )
    class_slot = next(
        choice
        for choice in result.choices
        if choice.choice_id.startswith("level:1:srd5.1:feature:fighter-fighting-style")
    )
    option = S.option_by_id(class_slot, "srd5.1:feature:fighter-fighting-style-defense")

    assert option.disabled_reason_code == "pool_option_granted_by_feat"
    assert option.disabled_reason_params["feat_ref"] == "tce:feat:fighting-initiate"


def test_superior_technique_through_fighting_initiate_exposes_its_maneuver_choice() -> None:
    result, _, opportunity = S.feat_draft(
        "tce:feat:fighting-initiate",
        spec=S.FIGHTER_L4,
        nested={"style": ("tce:feature:superior-technique",)},
    )
    build = result.build_candidate
    nested = next(choice for choice in result.choices if choice.source_ref == "tce:feature:superior-technique")
    maneuver = nested.selected_option_ids[0]

    assert S.issue_codes(result) == set()
    assert nested.option_source == "content:feature:optional-nested"
    assert maneuver.startswith("phb2014:feature:maneuver-")
    assert "tce:feature:superior-technique" in build.feature_refs
    assert maneuver in build.feature_refs
    assert {
        (source.feature_ref, source.source_ref)
        for source in build.feature_grant_sources
        if source.feature_ref in {maneuver, "tce:feature:superior-technique"}
    } == {
        (maneuver, "tce:feature:superior-technique"),
        ("tce:feature:superior-technique", "tce:feat:fighting-initiate"),
    }


def test_typed_static_facts_land_on_the_build_and_round_trip() -> None:
    from app.domain.character.schemas import CharacterBuild

    gunner, _, _ = S.feat_draft(GUNNER, spec=S.FIGHTER_L4)
    telepathic, _, _ = S.feat_draft("tce:feat:telepathic", spec=S.WIZARD_L8, nested={"ability": ("ability:charisma",)})
    artificer, _, _ = S.feat_draft(
        ARTIFICER_INITIATE,
        spec=S.WIZARD_L8,
        nested={
            "tool": ("srd5.1:proficiency:tinkers-tools",),
            "cantrip": ("srd5.1:spell:mending",),
            "spell": ("srd5.1:spell:cure-wounds",),
        },
    )

    assert [fact.model_dump() for fact in gunner.build_candidate.feat_static_facts] == [
        {"kind": "weapon_proficiency_category", "category": "firearms", "source_ref": GUNNER}
    ]
    assert [fact.model_dump() for fact in telepathic.build_candidate.feat_static_facts] == [
        {
            "kind": "one_way_telepathy",
            "range_ft": 60,
            "requires_visible_target": True,
            "requires_shared_language": True,
            "grants_reply": False,
            "source_ref": "tce:feat:telepathic",
        }
    ]
    assert [fact.model_dump() for fact in artificer.build_candidate.feat_static_facts] == [
        {
            "kind": "spellcasting_focus",
            "tool_ref": "srd5.1:proficiency:tinkers-tools",
            "casting_ability": "intelligence",
            "source_ref": ARTIFICER_INITIATE,
        }
    ]
    for build in (gunner.build_candidate, telepathic.build_candidate, artificer.build_candidate):
        assert CharacterBuild.model_validate_json(build.model_dump_json()) == build


def test_dragon_fear_requires_dragonborn_ancestry() -> None:
    dragonborn = _available_result(race="srd5.1:race:dragonborn")
    human = _available_result(race="srd5.1:race:human")

    assert _feat_option(dragonborn, DRAGON_FEAR).disabled_reason is None
    human_option = _feat_option(human, DRAGON_FEAR)
    assert human_option.disabled_reason_code == "feat_prerequisite_not_met"

    # Reject selection zero-side-effect assert
    rejected_result, _, _ = S.feat_draft(
        DRAGON_FEAR,
        race="srd5.1:race:human",
        nested={"ability": ("ability:strength",)},
        fill_rest=False,
    )
    assert "feat_prerequisite_not_met" in S.issue_codes(rejected_result)
    assert rejected_result.build_candidate is None or not any(
        fa.feat_ref == DRAGON_FEAR for fa in rejected_result.build_candidate.feat_acquisitions
    )
    baseline = S.auto_fill(S.payload(S.levels_for(S.FIGHTER_L4), race="srd5.1:race:human"), S.registry())
    baseline_res, _ = S.compile_payload(baseline, S.registry())
    effective_str = next(a.effective for a in rejected_result.resolved_summary.ability_scores if a.ability == "strength")
    baseline_str = next(a.effective for a in baseline_res.resolved_summary.ability_scores if a.ability == "strength")
    assert effective_str == baseline_str


def test_drow_high_magic_requires_drow_lineage_not_any_elf() -> None:
    content = S.registry()
    levels = S.levels_for(S.FIGHTER_L4)

    # 1. Drow -> eligible
    drow_payload = m01m_support.with_subrace(
        S.payload(levels, race="srd5.1:race:elf"),
        "phb2014:subrace:drow",
    )
    drow_base = S.auto_fill(drow_payload, content)
    drow_result, _ = S.compile_payload(drow_base, content)
    assert _feat_option(drow_result, DROW_HIGH_MAGIC).disabled_reason is None

    # 2. High Elf -> feat_prerequisite_not_met, requirements[0]["type"] == "lineage"
    high_elf_payload = m01m_support.with_subrace(
        S.payload(levels, race="srd5.1:race:elf"),
        "srd5.1:subrace:high-elf",
    )
    high_elf_base = S.auto_fill(high_elf_payload, content)
    high_elf_result, _ = S.compile_payload(high_elf_base, content)
    high_elf_option = _feat_option(high_elf_result, DROW_HIGH_MAGIC)
    assert high_elf_option.disabled_reason_code == "feat_prerequisite_not_met"
    assert high_elf_option.disabled_reason_params["requirements"][0]["type"] == "lineage"

    # 3. Half-Elf (no subrace) -> rejected
    half_elf_result = _available_result(race="srd5.1:race:half-elf")
    half_elf_option = _feat_option(half_elf_result, DROW_HIGH_MAGIC)
    assert half_elf_option.disabled_reason_code == "feat_prerequisite_not_met"

    # Rejection selection zero-side-effect assert
    opp = S.feat_opportunities(high_elf_result)[0]
    rejected_payload = S.with_selections(
        high_elf_base,
        {opp.choice_id: S.selection(opp.choice_id, DROW_HIGH_MAGIC, source_ref=opp.source_ref)},
    )
    rejected_result, _ = S.compile_payload(rejected_payload, content)
    assert "feat_prerequisite_not_met" in S.issue_codes(rejected_result)
    issue = next(i for i in rejected_result.validation.issues if i.code == "feat_prerequisite_not_met")
    assert issue.message_params["requirements"][0]["type"] == "lineage"
    assert rejected_result.build_candidate is None or not any(
        fa.feat_ref == DROW_HIGH_MAGIC for fa in rejected_result.build_candidate.feat_acquisitions
    )


def test_elven_accuracy_accepts_elf_and_half_elf_and_rejects_human() -> None:
    elf = _available_result(race="srd5.1:race:elf")
    half_elf = _available_result(race="srd5.1:race:half-elf")
    human = _available_result(race="srd5.1:race:human")

    assert _feat_option(elf, ELVEN_ACCURACY).disabled_reason is None
    assert _feat_option(half_elf, ELVEN_ACCURACY).disabled_reason is None
    human_option = _feat_option(human, ELVEN_ACCURACY)
    assert human_option.disabled_reason_code == "feat_prerequisite_not_met"

    # Rejection selection zero-side-effect assert
    rejected_result, _, _ = S.feat_draft(
        ELVEN_ACCURACY,
        race="srd5.1:race:human",
        nested={"ability": ("ability:dexterity",)},
        fill_rest=False,
    )
    assert "feat_prerequisite_not_met" in S.issue_codes(rejected_result)
    assert rejected_result.build_candidate is None or not any(
        fa.feat_ref == ELVEN_ACCURACY for fa in rejected_result.build_candidate.feat_acquisitions
    )
    baseline = S.auto_fill(S.payload(S.levels_for(S.FIGHTER_L4), race="srd5.1:race:human"), S.registry())
    baseline_res, _ = S.compile_payload(baseline, S.registry())
    effective_dex = next(a.effective for a in rejected_result.resolved_summary.ability_scores if a.ability == "dexterity")
    baseline_dex = next(a.effective for a in baseline_res.resolved_summary.ability_scores if a.ability == "dexterity")
    assert effective_dex == baseline_dex


def test_fighting_initiate_rejects_a_build_without_martial_weapon_proficiency() -> None:
    wizard = _available_result(spec=S.WIZARD_L8)
    fighter = _available_result(spec=S.FIGHTER_L4)

    wizard_option = _feat_option(wizard, FIGHTING_INITIATE)
    assert wizard_option.disabled_reason_code == "feat_prerequisite_not_met"
    assert wizard_option.disabled_reason_params["requirements"][0]["type"] == "proficiency"
    assert _feat_option(fighter, FIGHTING_INITIATE).disabled_reason is None

    # Rejection selection zero-side-effect assert
    rejected_result, _, _ = S.feat_draft(
        FIGHTING_INITIATE,
        spec=S.WIZARD_L8,
        nested={"style": ("srd5.1:feature:fighter-fighting-style-defense",)},
        fill_rest=False,
    )
    assert "feat_prerequisite_not_met" in S.issue_codes(rejected_result)
    assert rejected_result.build_candidate is None or not any(
        fa.feat_ref == FIGHTING_INITIATE for fa in rejected_result.build_candidate.feat_acquisitions
    )


def test_race_variants_keep_their_base_ancestry_for_racial_feats() -> None:
    content = S.registry()
    levels = S.levels_for(S.FIGHTER_L4)

    # Half-Elf + scag:race-variant:half-elf-wood-descent -> Elven Accuracy, Prodigy both available
    half_elf_wood = m01m_support.with_variant(
        S.payload(levels, race="srd5.1:race:half-elf"),
        "scag:race-variant:half-elf-wood-descent",
    )
    half_elf_res, _ = S.compile_payload(S.auto_fill(half_elf_wood, content), content)
    assert _feat_option(half_elf_res, ELVEN_ACCURACY).disabled_reason is None
    assert _feat_option(half_elf_res, PRODIGY).disabled_reason is None

    # Tiefling + mtf:race-variant:zariel-tiefling -> Infernal Constitution, Flames of Phlegethos both available
    zariel_tiefling = m01m_support.with_variant(
        S.payload(levels, race="srd5.1:race:tiefling"),
        "mtf:race-variant:zariel-tiefling",
    )
    zariel_res, _ = S.compile_payload(S.auto_fill(zariel_tiefling, content), content)
    assert _feat_option(zariel_res, INFERNAL_CONSTITUTION).disabled_reason is None
    assert _feat_option(zariel_res, FLAMES_OF_PHLEGETHOS).disabled_reason is None

    # Variant Human: Prodigy available, build.race_ref remains phb2014:race:variant-human
    var_human_res = _available_result(race="phb2014:race:variant-human")
    assert _feat_option(var_human_res, PRODIGY).disabled_reason is None
    var_human_draft, _, _ = S.feat_draft(
        PRODIGY,
        race="phb2014:race:variant-human",
        nested={
            "skill": ("srd5.1:proficiency:skill-investigation",),
            "tool": ("srd5.1:proficiency:thieves-tools",),
            "language": ("srd5.1:language:elvish",),
            "expertise": ("srd5.1:skill:investigation",),
        },
    )
    assert var_human_draft.build_candidate.race_ref == "phb2014:race:variant-human"


def test_chef_and_poisoner_reuse_the_canonical_tool_proficiency_identity() -> None:
    content = S.registry()
    assert [e.key for e in content.list_kind("proficiency") if "cooks-utensils" in e.key] == ["srd5.1:proficiency:cooks-utensils"]
    assert [e.key for e in content.list_kind("proficiency") if "poisoners-kit" in e.key] == ["srd5.1:proficiency:poisoners-kit"]
    assert not any("chef" in e.key or e.key.startswith("tce:proficiency:") for e in content.list_kind("proficiency"))

    chef_res, _, _ = S.feat_draft(
        CHEF,
        spec=S.FIGHTER_L4,
        nested={"ability": ("ability:constitution",)},
    )
    chef_build = chef_res.build_candidate
    assert chef_build.proficiencies.count("srd5.1:proficiency:cooks-utensils") == 1

    poisoner_res, _, _ = S.feat_draft(
        POISONER,
        spec=S.FIGHTER_L4,
    )
    poisoner_build = poisoner_res.build_candidate
    assert poisoner_build.proficiencies.count("srd5.1:proficiency:poisoners-kit") == 1

    # Background deduplication: Folk Hero with cooks-utensils chosen doesn't duplicate with Chef
    folk_payload = S.payload(
        S.levels_for(S.FIGHTER_L4),
        background="phb2014:background:folk-hero",
    )
    folk_base = S.auto_fill(folk_payload, content)
    compiled_first, _ = S.compile_payload(folk_base, content)
    artisan_choice = next(
        (c for c in compiled_first.choices if any("cooks-utensils" in opt.option_id for opt in c.options)),
        None,
    )
    if artisan_choice is not None:
        folk_base = S.with_selections(
            folk_base,
            {artisan_choice.choice_id: S.selection(artisan_choice.choice_id, "srd5.1:proficiency:cooks-utensils", source_ref=artisan_choice.source_ref)},
        )
    compiled_second, _ = S.compile_payload(folk_base, content)
    opp = S.feat_opportunities(compiled_second)[0]
    folk_chef_payload = S.with_selections(
        folk_base,
        {
            opp.choice_id: S.selection(opp.choice_id, CHEF, source_ref=opp.source_ref),
            **S.nested_selections(opp.choice_id, CHEF, {"ability": ("ability:constitution",)}),
        },
    )
    folk_chef_res, _ = S.compile_payload(S.auto_fill(folk_chef_payload, content), content)
    assert S.issue_codes(folk_chef_res) == set()
    assert folk_chef_res.build_candidate.proficiencies.count("srd5.1:proficiency:cooks-utensils") == 1


def test_metamagic_adept_rejects_duplicate_metamagic_selection() -> None:
    result, _, opportunity = S.feat_draft(
        METAMAGIC_ADEPT,
        spec=S.WIZARD_L8,
        nested={
            "metamagic": (
                "srd5.1:feature:metamagic-careful-spell",
                "srd5.1:feature:metamagic-careful-spell",
            )
        },
        fill_rest=False,
    )

    assert "duplicate_choice_option" in S.issue_codes(result)
    issue = next(i for i in result.validation.issues if i.code == "duplicate_choice_option")
    assert issue.message_params["choice_id"] == S.child_choice_id(opportunity, "metamagic")
    assert result.build_candidate is None or not any(
        grant.resource_id == "metamagic-adept-sorcery-points" for grant in result.build_candidate.feat_resource_grants
    )


def test_infernal_constitution_exposes_resistances_and_poison_save_advantage() -> None:
    content = S.registry()
    data = content.get(INFERNAL_CONSTITUTION).data
    mechanics = data.get("mechanics", [])

    res_mech = next(m for m in mechanics if m.get("kind") == "damage_resistance")
    assert set(res_mech["damage_types"]) == {"cold", "poison"}
    save_mech = next(m for m in mechanics if m.get("kind") == "save_advantage")
    assert save_mech["against"] == "poisoned_condition"

    baseline = S.auto_fill(
        S.payload(S.levels_for(S.FIGHTER_L4), race="srd5.1:race:tiefling"),
        content,
    )
    base_res, _ = S.compile_payload(baseline, content)
    base_con = next(a.effective for a in base_res.resolved_summary.ability_scores if a.ability == "constitution")

    result, _, _ = S.feat_draft(
        INFERNAL_CONSTITUTION,
        race="srd5.1:race:tiefling",
        spec=S.FIGHTER_L4,
    )
    assert S.issue_codes(result) == set()
    build = result.build_candidate
    assert build.ability_scores.constitution == base_con + 1


def test_expanded_spellcasting_atom_unlocks_phb_caster_feats_for_subclass_casters() -> None:
    phb_caster_feats = (
        "phb2014:feat:elemental-adept",
        "phb2014:feat:spell-sniper",
        "phb2014:feat:war-caster",
    )

    eldritch_knight_levels = S.class_levels(
        "fighter",
        4,
        first_hp=10,
        later_hp=6,
        subclass_ref="phb2014:subclass:eldritch-knight",
        subclass_level=3,
    )
    arcane_trickster_levels = S.class_levels(
        "rogue",
        4,
        first_hp=8,
        later_hp=5,
        subclass_ref="phb2014:subclass:arcane-trickster",
        subclass_level=3,
    )

    eldritch_knight = _available_result(levels=eldritch_knight_levels)
    arcane_trickster = _available_result(levels=arcane_trickster_levels)
    champion = _available_result(spec=S.FIGHTER_L4)
    wizard = _available_result(spec=S.WIZARD_L8)

    for feat_key in phb_caster_feats:
        assert _feat_option(eldritch_knight, feat_key).disabled_reason is None
        assert _feat_option(arcane_trickster, feat_key).disabled_reason is None
        assert _feat_option(champion, feat_key).disabled_reason_code == "feat_prerequisite_not_met"
        assert _feat_option(wizard, feat_key).disabled_reason is None
