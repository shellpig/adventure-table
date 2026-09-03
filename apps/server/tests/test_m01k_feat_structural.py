"""M01-K K.4 — feat structural mechanics matrix and static derived values."""

from __future__ import annotations

import m01k_support as S
from app.domain.rules.abilities import ability_modifier, effective_ability_score
from app.domain.rules.feature_resources import feature_resource_capacities
from app.domain.rules.hit_points import calculate_max_hp
from app.domain.rules.skills import passive_investigation, passive_perception


ACTOR = "phb2014:feat:actor"
ATHLETE = "phb2014:feat:athlete"
MAGIC_INITIATE = "phb2014:feat:magic-initiate"
MARTIAL_ADEPT = "phb2014:feat:martial-adept"
OBSERVANT = "phb2014:feat:observant"
RESILIENT = "phb2014:feat:resilient"
SKILLED = "phb2014:feat:skilled"
TOUGH = "phb2014:feat:tough"
WEAPON_MASTER = "phb2014:feat:weapon-master"

BATTLE_MASTER_POOL = "feature:superiority-dice"


def _child(result, opportunity_id: str, field: str):
    return S.choice_by_id(result, S.child_choice_id(opportunity_id, field))


# Alert has no ability increase, no nested choices and no static modifiers, so a
# build that takes it isolates whatever the feat under test contributes.
NEUTRAL_FEAT = "phb2014:feat:alert"


def _baseline_build(content, spec=S.FIGHTER_L4, levels=None):
    """A build that takes a structurally neutral feat, for A/B comparison."""

    result, _, _ = S.feat_draft(NEUTRAL_FEAT, spec=spec, levels=levels, content=content)
    assert S.issue_codes(result) == set()
    return result.build_candidate


# --- half-feat ability increase -----------------------------------------------


def test_fixed_half_feat_raises_exactly_one_ability_once() -> None:
    content = S.registry()
    baseline = _baseline_build(content)
    result, _, _ = S.feat_draft(ACTOR, content=content)
    build = result.build_candidate

    assert S.issue_codes(result) == set()
    assert build.ability_scores.charisma == baseline.ability_scores.charisma + 1
    for ability in ("strength", "dexterity", "constitution", "intelligence", "wisdom"):
        assert getattr(build.ability_scores, ability) == getattr(baseline.ability_scores, ability)


def test_half_feat_increase_is_not_applied_twice_on_recompile() -> None:
    content = S.registry()
    result, payload, _ = S.feat_draft(ATHLETE, content=content, nested={"ability": ("ability:strength",)})
    again, _ = S.compile_payload(payload, content)

    assert result.build_candidate.ability_scores == again.build_candidate.ability_scores


def test_half_feat_rejects_an_ability_outside_the_content_option_list() -> None:
    content = S.registry()
    result, payload, opportunity = S.feat_draft(
        WEAPON_MASTER, content=content, nested={"ability": ("ability:charisma",)}, fill_rest=False
    )
    choice = _child(result, opportunity, "ability")

    assert {option.option_id for option in choice.options} == {
        "ability:strength",
        "ability:dexterity",
    }
    assert "invalid_choice_option" in S.issue_codes(result)


# --- Resilient ----------------------------------------------------------------


def test_resilient_grants_the_chosen_ability_and_its_saving_throw() -> None:
    content = S.registry()
    baseline = _baseline_build(content)
    for ability, save_ref in (
        ("strength", "srd5.1:ability:str"),
        ("dexterity", "srd5.1:ability:dex"),
        ("constitution", "srd5.1:ability:con"),
        ("intelligence", "srd5.1:ability:int"),
        ("wisdom", "srd5.1:ability:wis"),
        ("charisma", "srd5.1:ability:cha"),
    ):
        result, _, _ = S.feat_draft(
            RESILIENT, content=content, nested={"ability": (f"ability:{ability}",)}
        )
        build = result.build_candidate
        assert S.issue_codes(result) == set(), ability
        assert getattr(build.ability_scores, ability) == getattr(baseline.ability_scores, ability) + 1
        assert save_ref in build.saving_throw_proficiencies


def test_resilient_blocks_an_incomplete_ability_choice() -> None:
    content = S.registry()
    result, _, _ = S.feat_draft(RESILIENT, content=content, fill_rest=False)

    assert "incomplete_feat_choice" in S.issue_codes(result)
    assert result.validation.can_confirm is False


def test_resilient_round_trips_through_a_recompile() -> None:
    content = S.registry()
    result, payload, _ = S.feat_draft(
        RESILIENT, content=content, nested={"ability": ("ability:wisdom",)}
    )
    again, _ = S.compile_payload(payload, content)

    assert again.build_candidate.saving_throw_proficiencies == result.build_candidate.saving_throw_proficiencies
    assert again.build_candidate.ability_scores == result.build_candidate.ability_scores


# --- Skilled ------------------------------------------------------------------


def test_skilled_requires_exactly_three_distinct_legal_proficiencies() -> None:
    content = S.registry()
    result, payload, opportunity = S.feat_draft(SKILLED, content=content, fill_rest=False)
    choice = _child(result, opportunity, "proficiencies")
    assert choice.choose_count == 3
    options = [option.option_id for option in choice.options]

    legal = S.with_selections(
        payload, S.nested_selections(opportunity, SKILLED, {"proficiencies": tuple(options[:3])})
    )
    legal_result, _ = S.compile_payload(legal, content)
    assert S.issue_codes(legal_result) == set()

    for label, values in (
        ("two", options[:2]),
        ("four", options[:4]),
    ):
        wrong = S.with_selections(
            payload, S.nested_selections(opportunity, SKILLED, {"proficiencies": tuple(values)})
        )
        wrong_result, _ = S.compile_payload(wrong, content)
        assert "incomplete_feat_choice" in S.issue_codes(wrong_result), label

    duplicated = S.with_selections(
        payload,
        S.nested_selections(
            opportunity, SKILLED, {"proficiencies": (options[0], options[0], options[1])}
        ),
    )
    duplicated_result, _ = S.compile_payload(duplicated, content)
    assert "duplicate_choice_option" in S.issue_codes(duplicated_result)

    wrong_kind = S.with_selections(
        payload,
        S.nested_selections(
            opportunity,
            SKILLED,
            {"proficiencies": (options[0], options[1], "srd5.1:proficiency:battleaxes")},
        ),
    )
    wrong_kind_result, _ = S.compile_payload(wrong_kind, content)
    assert "illegal_feat_nested_choice" in S.issue_codes(wrong_kind_result)


def test_skilled_skill_selections_land_in_the_build() -> None:
    content = S.registry()
    baseline = _baseline_build(content)
    already = set(baseline.skill_choices)
    result, _, opportunity = S.feat_draft(SKILLED, content=content, fill_rest=False)
    options = [
        option.option_id
        for option in _child(result, opportunity, "proficiencies").options
        if ":proficiency:skill-" in option.option_id
        and option.option_id.replace(":proficiency:skill-", ":skill:") not in already
    ]
    assert len(options) >= 3

    chosen, _, _ = S.feat_draft(
        SKILLED, content=content, nested={"proficiencies": tuple(options[:3])}
    )
    build = chosen.build_candidate
    assert S.issue_codes(chosen) == set()
    granted = set(build.skill_choices)
    for option_id in options[:3]:
        assert option_id.replace(":proficiency:skill-", ":skill:") in granted


# --- Weapon Master ------------------------------------------------------------


def test_weapon_master_takes_its_counts_from_content_not_a_hardcoded_list() -> None:
    content = S.registry()
    feat = content.get(WEAPON_MASTER)
    expected = next(raw for raw in feat.data["choices"] if raw["id"] == "weapons")

    result, payload, opportunity = S.feat_draft(WEAPON_MASTER, content=content, fill_rest=False)
    choice = _child(result, opportunity, "weapons")

    assert choice.choose_count == expected["choose"]
    assert choice.option_source == "content:feat:weapon_proficiency"
    assert all(option.option_id.count(":proficiency:") == 1 for option in choice.options)

    weapons = [option.option_id for option in choice.options][: expected["choose"]]
    legal = S.with_selections(
        payload,
        S.nested_selections(
            opportunity,
            WEAPON_MASTER,
            {"ability": ("ability:strength",), "weapons": tuple(weapons)},
        ),
    )
    legal = S.auto_fill(legal, content, skip_sources=set())
    legal_result, _ = S.compile_payload(legal, content)
    assert S.issue_codes(legal_result) == set()
    for weapon in weapons:
        assert weapon in legal_result.build_candidate.proficiencies


def test_weapon_master_rejects_duplicate_and_wrong_kind_weapon_choices() -> None:
    content = S.registry()
    result, payload, opportunity = S.feat_draft(WEAPON_MASTER, content=content, fill_rest=False)
    weapons = [option.option_id for option in _child(result, opportunity, "weapons").options][:4]

    duplicated = S.with_selections(
        payload,
        S.nested_selections(
            opportunity,
            WEAPON_MASTER,
            {"ability": ("ability:strength",), "weapons": (weapons[0], weapons[0], weapons[1], weapons[2])},
        ),
    )
    assert "duplicate_choice_option" in S.issue_codes(S.compile_payload(duplicated, content)[0])

    wrong_kind = S.with_selections(
        payload,
        S.nested_selections(
            opportunity,
            WEAPON_MASTER,
            {
                "ability": ("ability:strength",),
                "weapons": (*weapons[:3], "srd5.1:proficiency:skill-acrobatics"),
            },
        ),
    )
    assert "illegal_feat_nested_choice" in S.issue_codes(S.compile_payload(wrong_kind, content)[0])


# --- Magic Initiate -----------------------------------------------------------


def test_magic_initiate_derives_its_spell_pool_from_the_selected_source_class() -> None:
    content = S.registry()
    result, _, opportunity = S.feat_draft(
        MAGIC_INITIATE, content=content, nested={"spell-source": ("srd5.1:class:wizard",)}, fill_rest=False
    )

    cantrips = _child(result, opportunity, "cantrips")
    spell = _child(result, opportunity, "spell")
    assert cantrips.choose_count == 2
    assert spell.choose_count == 1
    assert all(
        content.get(option.option_id).data["level"] == 0 for option in cantrips.options
    )
    assert all(
        content.get(option.option_id).data["level"] == 1 for option in spell.options
    )
    # The PHB non-SRD catalog participates in the derived pool.
    assert "phb2014:spell:blade-ward" in {option.option_id for option in cantrips.options}
    assert "phb2014:spell:chromatic-orb" in {option.option_id for option in spell.options}


def test_magic_initiate_persists_its_source_and_spell_access() -> None:
    content = S.registry()
    result, _, _ = S.feat_draft(
        MAGIC_INITIATE,
        content=content,
        nested={
            "spell-source": ("srd5.1:class:wizard",),
            "cantrips": ("phb2014:spell:blade-ward", "srd5.1:spell:acid-splash"),
            "spell": ("phb2014:spell:chromatic-orb",),
        },
    )
    build = result.build_candidate

    assert S.issue_codes(result) == set()
    acquisition = next(
        entry for entry in build.feat_acquisitions if entry.feat_ref == MAGIC_INITIATE
    )
    assert acquisition.selections["spell-source"] == ("srd5.1:class:wizard",)
    granted = {
        entry.spell_key
        for entry in build.spell_access_entries
        if entry.source_type == "feat" and entry.source_key == MAGIC_INITIATE
    }
    assert granted == {
        "phb2014:spell:blade-ward",
        "srd5.1:spell:acid-splash",
        "phb2014:spell:chromatic-orb",
    }


def test_magic_initiate_blocks_wrong_class_and_wrong_level_spells() -> None:
    content = S.registry()
    _, payload, opportunity = S.feat_draft(
        MAGIC_INITIATE,
        content=content,
        nested={
            "spell-source": ("srd5.1:class:wizard",),
            "cantrips": ("phb2014:spell:blade-ward", "srd5.1:spell:acid-splash"),
            "spell": ("phb2014:spell:chromatic-orb",),
        },
    )

    wrong_class = S.with_selections(
        payload, S.nested_selections(opportunity, MAGIC_INITIATE, {"spell": ("srd5.1:spell:cure-wounds",)})
    )
    assert "illegal_feat_nested_choice" in S.issue_codes(S.compile_payload(wrong_class, content)[0])

    wrong_level = S.with_selections(
        payload,
        S.nested_selections(
            opportunity,
            MAGIC_INITIATE,
            {"cantrips": ("phb2014:spell:chromatic-orb", "srd5.1:spell:acid-splash")},
        ),
    )
    assert "illegal_feat_nested_choice" in S.issue_codes(S.compile_payload(wrong_level, content)[0])


def test_switching_the_magic_initiate_source_invalidates_stale_spell_picks() -> None:
    content = S.registry()
    _, payload, opportunity = S.feat_draft(
        MAGIC_INITIATE,
        content=content,
        nested={
            "spell-source": ("srd5.1:class:wizard",),
            "cantrips": ("phb2014:spell:blade-ward", "srd5.1:spell:acid-splash"),
            "spell": ("phb2014:spell:chromatic-orb",),
        },
    )
    switched = S.with_selections(
        payload, S.nested_selections(opportunity, MAGIC_INITIATE, {"spell-source": ("srd5.1:class:cleric",)})
    )
    result, _ = S.compile_payload(switched, content)

    assert "illegal_feat_nested_choice" in S.issue_codes(result)
    assert result.validation.can_confirm is False


# --- Martial Adept — source-granted maneuver entitlement ----------------------


def test_non_fighter_martial_adept_unlocks_the_canonical_maneuver_pool() -> None:
    content = S.registry()
    result, _, opportunity = S.feat_draft(MARTIAL_ADEPT, spec=S.WIZARD_L8, content=content)
    build = result.build_candidate
    choice = _child(result, opportunity, "maneuvers")

    assert S.issue_codes(result) == set()
    assert choice.choose_count == content.get(MARTIAL_ADEPT).data["choices"][0]["choose"]
    # Reuses the canonical Battle Master maneuver identities, no duplicates.
    assert all(
        content.get(option.option_id).data["choice_pool_option"]["pool"] == "battle-master-maneuver"
        for option in choice.options
    )
    selected = [ref for ref in build.feature_refs if ":feature:maneuver-" in ref]
    assert len(selected) == choice.choose_count
    provenance = {
        entry.feature_ref: entry.source_ref
        for entry in build.feature_grant_sources
        if entry.feature_ref in selected
    }
    assert set(provenance.values()) == {MARTIAL_ADEPT}


def test_non_fighter_without_martial_adept_is_still_blocked_by_the_class_gate() -> None:
    content = S.registry()
    result, _, opportunity = S.feat_draft(
        MARTIAL_ADEPT, spec=S.WIZARD_L8, content=content, fill_rest=False
    )
    entitled = _child(result, opportunity, "maneuvers")
    maneuver = entitled.options[0].option_id

    # Same wizard, same maneuver, but the entitlement never existed.
    plain, _, _ = S.feat_draft(ACTOR, spec=S.WIZARD_L8, content=content)
    forced = plain.build_candidate.model_copy(
        update={"feature_refs": (*plain.build_candidate.feature_refs, maneuver)}
    )

    from app.domain.character_builder.m01i_validation import (
        validate_final_feature_pool_dependencies,
    )

    codes = {issue.code for issue in validate_final_feature_pool_dependencies(forced, content)}
    assert "optional_pool_final_class_prerequisite_not_met" in codes


def test_martial_adept_rejects_wrong_count_and_duplicate_maneuvers() -> None:
    content = S.registry()
    result, payload, opportunity = S.feat_draft(
        MARTIAL_ADEPT, spec=S.WIZARD_L8, content=content, fill_rest=False
    )
    options = [option.option_id for option in _child(result, opportunity, "maneuvers").options]

    for values, expected in (
        ((options[0],), "incomplete_feat_choice"),
        ((options[0], options[1], options[2]), "incomplete_feat_choice"),
        ((options[0], options[0]), "duplicate_choice_option"),
        ((options[0], "srd5.1:skill:acrobatics"), "illegal_feat_nested_choice"),
    ):
        candidate = S.with_selections(
            payload, S.nested_selections(opportunity, MARTIAL_ADEPT, {"maneuvers": values})
        )
        assert expected in S.issue_codes(S.compile_payload(candidate, content)[0]), values


def test_martial_adept_materializes_its_superiority_die_resource() -> None:
    content = S.registry()
    result, _, _ = S.feat_draft(MARTIAL_ADEPT, spec=S.WIZARD_L8, content=content)
    build = result.build_candidate
    raw = content.get(MARTIAL_ADEPT).data["resource"]

    grant = next(
        entry for entry in build.feat_resource_grants if entry.resource_id == "superiority-dice"
    )
    assert grant.capacity == raw["capacity"]
    assert grant.die_size == raw["die_size"]
    assert set(grant.recharge) == set(raw["recharge"])
    assert grant.stacking == raw["stacking"]
    assert grant.source_ref == MARTIAL_ADEPT
    assert feature_resource_capacities(build, content)[BATTLE_MASTER_POOL] == raw["capacity"]


def test_martial_adept_aggregates_into_an_existing_superiority_pool() -> None:
    """A Battle Master who also takes the feat gets one aggregated pool."""

    content = S.registry()
    levels = S.class_levels(
        "fighter", 4, first_hp=10, later_hp=6, subclass_ref="phb2014:subclass:battle-master", subclass_level=3
    )
    result, _, _ = S.feat_draft(MARTIAL_ADEPT, levels=levels, content=content)
    build = result.build_candidate

    assert S.issue_codes(result) == set()
    capacities = feature_resource_capacities(build, content)
    # Battle Master at fighter 3-6 grants four dice; the feat adds exactly one.
    assert capacities[BATTLE_MASTER_POOL] == 5
    assert len([key for key in capacities if "superiority" in key]) == 1


# --- unconditional static derived values --------------------------------------


def test_tough_scales_max_hp_with_character_level() -> None:
    content = S.registry()
    for spec, level in ((S.FIGHTER_L4, 4), (S.FIGHTER_L8, 8)):
        result, _, _ = S.feat_draft(TOUGH, spec=spec, content=content)
        build = result.build_candidate
        constitution = ability_modifier(effective_ability_score(build, "constitution"))

        assert S.issue_codes(result) == set()
        assert build.static_derived_modifiers == (
            S.StaticDerivedModifier(target="max_hp", value=2, per_level=True, source_ref=TOUGH),
        )
        assert calculate_max_hp(build) == sum(build.hp_progression) + constitution * level + 2 * level


def test_tough_recomputes_after_gaining_levels_without_manual_upkeep() -> None:
    content = S.registry()
    low, _, _ = S.feat_draft(TOUGH, spec=S.FIGHTER_L4, content=content)
    high, _, _ = S.feat_draft(TOUGH, spec=S.FIGHTER_L8, content=content)

    delta_levels = 4
    base_delta = sum(high.build_candidate.hp_progression) - sum(low.build_candidate.hp_progression)
    constitution = ability_modifier(
        effective_ability_score(high.build_candidate, "constitution")
    )
    assert calculate_max_hp(high.build_candidate) - calculate_max_hp(low.build_candidate) == (
        base_delta + constitution * delta_levels + 2 * delta_levels
    )


def test_a_character_without_tough_is_untouched() -> None:
    content = S.registry()
    baseline = _baseline_build(content)
    constitution = ability_modifier(effective_ability_score(baseline, "constitution"))

    assert baseline.static_derived_modifiers == ()
    assert calculate_max_hp(baseline) == sum(baseline.hp_progression) + constitution * 4


def test_numeric_override_still_wins_over_the_tough_modifier() -> None:
    content = S.registry()
    result, _, _ = S.feat_draft(
        TOUGH, content=content, numeric_overrides=({"key": "max_hp", "value": 99},)
    )

    assert calculate_max_hp(result.build_candidate) == 99


def test_observant_raises_both_passive_scores() -> None:
    content = S.registry()
    baseline = _baseline_build(content)
    result, _, _ = S.feat_draft(
        OBSERVANT, content=content, nested={"ability": ("ability:wisdom",)}
    )
    build = result.build_candidate

    assert S.issue_codes(result) == set()
    targets = {
        (modifier.target, modifier.value, modifier.per_level, modifier.source_ref)
        for modifier in build.static_derived_modifiers
    }
    assert targets == {
        ("passive_perception", 5, False, OBSERVANT),
        ("passive_investigation", 5, False, OBSERVANT),
    }
    # Perception also gains the +1 WIS from the half-feat; Investigation does not.
    assert passive_perception(build, content) == passive_perception(baseline, content) + 6
    assert passive_investigation(build, content) == passive_investigation(baseline, content) + 5


def test_observant_stacks_on_top_of_proficiency_and_expertise_order() -> None:
    content = S.registry()
    levels = S.class_levels(
        "rogue", 4, first_hp=8, later_hp=5, subclass_ref="srd5.1:subclass:thief", subclass_level=3
    )
    plain = _baseline_build(content, levels=levels)
    observant, _, _ = S.feat_draft(
        OBSERVANT, levels=levels, content=content, nested={"ability": ("ability:intelligence",)}
    )
    build = observant.build_candidate

    assert S.issue_codes(observant) == set()
    # Rogue Expertise may already double Perception / Investigation. The feat adds
    # its flat +5 on top of that, plus whatever its INT increase moves the
    # Investigation modifier by.
    intelligence_delta = ability_modifier(
        effective_ability_score(build, "intelligence")
    ) - ability_modifier(effective_ability_score(plain, "intelligence"))
    assert passive_perception(build, content) == passive_perception(plain, content) + 5
    assert passive_investigation(build, content) == (
        passive_investigation(plain, content) + 5 + intelligence_delta
    )
