"""M01-O — XGE/TCE feat spell grants and metadata matrix."""

from __future__ import annotations

import m01k_support as S
import m01m_support
from app.domain.character.schemas import TelepathyFact


DROW_HIGH_MAGIC = "xge:feat:drow-high-magic"
FEY_TELEPORTATION = "xge:feat:fey-teleportation"
WOOD_ELF_MAGIC = "xge:feat:wood-elf-magic"
FEY_TOUCHED = "tce:feat:fey-touched"
TELEKINETIC = "tce:feat:telekinetic"
TELEPATHIC = "tce:feat:telepathic"


def _spell_entry(build, spell_key: str, *, source_key: str | None = None):
    matches = [
        entry
        for entry in build.spell_access_entries
        if entry.spell_key == spell_key and entry.source_type == "feat"
    ]
    if source_key is not None:
        matches = [e for e in matches if e.source_key == source_key]
    assert matches, f"missing feat spell access {spell_key}"
    return matches[0]


def _child(result, opportunity_id: str, field: str):
    return S.choice_by_id(result, S.child_choice_id(opportunity_id, field))


def _feat_draft_custom(
    feat_ref: str,
    payload,
    *,
    nested: dict[str, tuple[str, ...]] | None = None,
    content=None,
    fill_rest: bool = True,
):
    content = content or S.registry()
    base = S.auto_fill(payload, content)
    result, _ = S.compile_payload(base, content)
    opp = S.feat_opportunities(result)[0]
    base = S.with_selections(
        base,
        {opp.choice_id: S.selection(opp.choice_id, feat_ref, source_ref=opp.source_ref)},
    )
    if nested:
        base = S.with_selections(base, S.nested_selections(opp.choice_id, feat_ref, nested))
    if fill_rest:
        base = S.auto_fill(base, content, skip_sources=set())
        base = S.fill_spell_choices(base, content)
    result, _ = S.compile_payload(base, content)
    return result, base, opp.choice_id


def test_drow_high_magic_grants_three_charisma_spells_with_their_use_metadata() -> None:
    content = S.registry()
    payload = m01m_support.with_subrace(
        S.payload(S.levels_for(S.FIGHTER_L4), race="srd5.1:race:elf"),
        "phb2014:subrace:drow",
    )
    result, _, _ = _feat_draft_custom(DROW_HIGH_MAGIC, payload, content=content)
    assert S.issue_codes(result) == set()
    build = result.build_candidate

    detect_magic = _spell_entry(build, "srd5.1:spell:detect-magic", source_key=DROW_HIGH_MAGIC)
    assert detect_magic.source_type == "feat"
    assert detect_magic.source_key == DROW_HIGH_MAGIC
    assert detect_magic.casting_ability == "charisma"
    assert detect_magic.uses_per_rest is None

    levitate = _spell_entry(build, "srd5.1:spell:levitate", source_key=DROW_HIGH_MAGIC)
    assert levitate.source_type == "feat"
    assert levitate.source_key == DROW_HIGH_MAGIC
    assert levitate.casting_ability == "charisma"
    assert levitate.uses_per_rest == 1
    assert levitate.recharge_types == ("long_rest",)

    dispel_magic = _spell_entry(build, "srd5.1:spell:dispel-magic", source_key=DROW_HIGH_MAGIC)
    assert dispel_magic.source_type == "feat"
    assert dispel_magic.source_key == DROW_HIGH_MAGIC
    assert dispel_magic.casting_ability == "charisma"
    assert dispel_magic.uses_per_rest == 1
    assert dispel_magic.recharge_types == ("long_rest",)


def test_fey_teleportation_grants_misty_step_and_a_formal_sylvan_language() -> None:
    content = S.registry()
    payload = m01m_support.with_subrace(
        S.payload(S.levels_for(S.FIGHTER_L4), race="srd5.1:race:elf"),
        "srd5.1:subrace:high-elf",
    )
    result, _, _ = _feat_draft_custom(
        FEY_TELEPORTATION,
        payload,
        nested={"ability": ("ability:intelligence",)},
        content=content,
    )
    assert S.issue_codes(result) == set()
    build = result.build_candidate

    misty = _spell_entry(build, "srd5.1:spell:misty-step", source_key=FEY_TELEPORTATION)
    assert misty.source_type == "feat"
    assert misty.source_key == FEY_TELEPORTATION
    assert misty.casting_ability == "intelligence"
    assert misty.uses_per_rest == 1
    assert "short_rest" in misty.recharge_types and "long_rest" in misty.recharge_types
    assert "srd5.1:language:sylvan" in build.language_refs


def test_wood_elf_magic_cantrip_pool_is_druid_only_and_fixed_spells_use_wisdom() -> None:
    content = S.registry()
    payload = m01m_support.with_subrace(
        S.payload(S.levels_for(S.FIGHTER_L4), race="srd5.1:race:elf"),
        "phb2014:subrace:wood-elf",
    )
    result, _, opp = _feat_draft_custom(
        WOOD_ELF_MAGIC,
        payload,
        content=content,
        fill_rest=False,
    )
    cantrip_choice = _child(result, opp, "cantrip")
    assert cantrip_choice.options
    option_ids = {opt.option_id for opt in cantrip_choice.options}
    assert "srd5.1:spell:fire-bolt" not in option_ids

    for opt in cantrip_choice.options:
        entry = content.get(opt.option_id)
        assert entry.data.get("level") == 0
        classes = entry.data.get("classes", [])
        assert any(
            c.get("index") == "druid" or c.get("name") == "Druid" or c.get("url") == "/api/2014/classes/druid"
            for c in classes
        ), f"non-druid cantrip in options: {opt.option_id}"

    # Pick a cantrip and complete
    completed_res, _, _ = _feat_draft_custom(
        WOOD_ELF_MAGIC,
        payload,
        nested={"cantrip": ("srd5.1:spell:druidcraft",)},
        content=content,
    )
    assert S.issue_codes(completed_res) == set()
    build = completed_res.build_candidate

    cantrip_entry = _spell_entry(build, "srd5.1:spell:druidcraft", source_key=WOOD_ELF_MAGIC)
    assert cantrip_entry.source_type == "feat"
    assert cantrip_entry.source_key == WOOD_ELF_MAGIC
    assert cantrip_entry.casting_ability == "wisdom"

    longstrider = _spell_entry(build, "srd5.1:spell:longstrider", source_key=WOOD_ELF_MAGIC)
    assert longstrider.source_type == "feat"
    assert longstrider.source_key == WOOD_ELF_MAGIC
    assert longstrider.casting_ability == "wisdom"
    assert longstrider.uses_per_rest == 1
    assert longstrider.recharge_types == ("long_rest",)

    pass_without_trace = _spell_entry(build, "srd5.1:spell:pass-without-trace", source_key=WOOD_ELF_MAGIC)
    assert pass_without_trace.source_type == "feat"
    assert pass_without_trace.source_key == WOOD_ELF_MAGIC
    assert pass_without_trace.casting_ability == "wisdom"
    assert pass_without_trace.uses_per_rest == 1
    assert pass_without_trace.recharge_types == ("long_rest",)


def test_telekinetic_grants_mage_hand_regardless_of_prior_knowledge() -> None:
    content = S.registry()

    # (a) Fighter L4 (does not know Mage Hand)
    res_a, _, _ = S.feat_draft(
        TELEKINETIC,
        spec=S.FIGHTER_L4,
        nested={"ability": ("ability:intelligence",)},
    )
    assert S.issue_codes(res_a) == set()
    build_a = res_a.build_candidate
    feat_mage_hand_a = _spell_entry(build_a, "srd5.1:spell:mage-hand", source_key=TELEKINETIC)
    assert feat_mage_hand_a.source_type == "feat"
    assert feat_mage_hand_a.source_key == TELEKINETIC
    assert feat_mage_hand_a.casting_ability == "intelligence"

    # (b) Wizard L8, where mage-hand is in class known cantrips
    wiz_payload = S.payload(S.levels_for(S.WIZARD_L8), race="srd5.1:race:human")
    wiz_base = S.auto_fill(wiz_payload, content)
    wiz_base = S.fill_spell_choices(wiz_base, content, prefer=("srd5.1:spell:mage-hand",))
    res_wiz, _, _ = _feat_draft_custom(
        TELEKINETIC,
        wiz_base,
        nested={"ability": ("ability:intelligence",)},
        content=content,
    )
    assert S.issue_codes(res_wiz) == set()
    build_b = res_wiz.build_candidate

    mage_hand_entries = [
        e for e in build_b.spell_access_entries if e.spell_key == "srd5.1:spell:mage-hand"
    ]
    assert len(mage_hand_entries) == 2
    feat_entry = next(e for e in mage_hand_entries if e.source_type == "feat")
    class_entry = next(e for e in mage_hand_entries if e.source_type != "feat")
    assert feat_entry.source_key == TELEKINETIC
    assert feat_entry.casting_ability == "intelligence"
    assert class_entry.source_type == "class"

    # Mechanics contains mage_hand_invisible_and_range_bonus
    feat_data = content.get(TELEKINETIC).data
    assert any(m.get("kind") == "mage_hand_invisible_and_range_bonus" for m in feat_data.get("mechanics", []))


def test_telepathic_grants_detect_thoughts_free_cast_on_the_chosen_ability() -> None:
    result, _, _ = S.feat_draft(
        TELEPATHIC,
        spec=S.WIZARD_L8,
        nested={"ability": ("ability:wisdom",)},
    )
    assert S.issue_codes(result) == set()
    build = result.build_candidate

    entry = _spell_entry(build, "srd5.1:spell:detect-thoughts", source_key=TELEPATHIC)
    assert entry.source_type == "feat"
    assert entry.source_key == TELEPATHIC
    assert entry.casting_ability == "wisdom"
    assert entry.uses_per_rest == 1
    assert entry.recharge_types == ("long_rest",)

    assert any(isinstance(fact, TelepathyFact) for fact in build.feat_static_facts)


def test_feat_spell_access_does_not_pollute_class_known_or_prepared_lists() -> None:
    content = S.registry()
    baseline = S.auto_fill(S.payload(S.levels_for(S.WIZARD_L8), race="srd5.1:race:human"), content)
    baseline = S.auto_fill(baseline, content, skip_sources=set())
    baseline = S.fill_spell_choices(baseline, content)
    base_res = S.compile_payload(baseline, content)[0]
    base_build = base_res.build_candidate
    assert base_build is not None
    base_wiz_prof = next(p for p in base_res.resolved_summary.spellcasting_profiles if p.class_ref == "srd5.1:class:wizard")
    baseline_class_spell_keys = {e.spell_key for e in base_build.spell_access_entries if e.source_type == "class"}

    result, _, _ = S.feat_draft(
        FEY_TOUCHED,
        spec=S.WIZARD_L8,
        nested={
            "ability": ("ability:wisdom",),
            "spell": ("srd5.1:spell:detect-magic",),
        },
    )
    assert S.issue_codes(result) == set()
    build = result.build_candidate

    # Prepared limit calculation is not increased by the feat
    wiz_prof = next(p for p in build.spellcasting_profiles if p.class_ref == "srd5.1:class:wizard")
    assert wiz_prof.prepared_limit == base_wiz_prof.prepared_limit

    # Feat entries are cleanly typed as feat-granted
    feat_spell_keys = {"srd5.1:spell:misty-step", "srd5.1:spell:detect-magic"}
    feat_entries = [e for e in build.spell_access_entries if e.source_type == "feat" and e.source_key == FEY_TOUCHED]
    assert {e.spell_key for e in feat_entries} == feat_spell_keys
    for e in feat_entries:
        assert e.access_type == "granted"
        assert e.source_type == "feat"
        assert e.source_key == FEY_TOUCHED
        assert e.casting_ability == "wisdom"

    # Class entries do not carry the feat source key and match baseline class spell keys exactly
    class_entries = [e for e in build.spell_access_entries if e.source_type == "class"]
    assert {e.spell_key for e in class_entries} == baseline_class_spell_keys
    assert all(e.source_key != FEY_TOUCHED for e in class_entries)
    assert all(e.source_key.startswith("srd5.1:class:wizard") for e in class_entries)
