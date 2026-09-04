from __future__ import annotations

import pytest

from app.interop.content_ref_walker import (
    BUILD_STABLE_KEY_PATHS,
    STATE_STABLE_KEY_PATHS,
    assert_no_unwalked_stable_keys,
)


EXPECTED_BUILD_PATHS = {
    "race_ref",
    "race_variant_ref",
    "race_variant_group_selections[].race_variant_ref",
    "subrace_ref",
    "lineage_ref",
    "ancestral_origin_ref",
    "ancestral_legacy.retained_skill_refs[]",
    "background_ref",
    "alignment_ref",
    "class_progression[]",
    "subclasses[].class_ref",
    "subclasses[].subclass_ref",
    "proficiencies[]",
    "saving_throw_proficiencies[]",
    "skill_choices[]",
    "skill_expertise_refs[]",
    "language_refs[]",
    "feature_refs[]",
    "feature_grant_sources[].feature_ref",
    "feature_grant_sources[].source_ref",
    "feat_refs[]",
    "feat_acquisitions[].feat_ref",
    "static_derived_modifiers[].source_ref",
    "feat_resource_grants[].source_ref",
    "infusion_refs[]",
    "spellcasting_profiles[].source_key",
    "spellcasting_profiles[].class_ref",
    "spell_access_entries[].spell_key",
    "spell_access_entries[].source_key",
    "starting_equipment[].item_ref",
    "numeric_overrides[skill_modifier:*].key",
    "numeric_overrides[spell_save_dc:*].key",
}

EXPECTED_STATE_PATHS = {
    "conditions[].condition_ref",
    "prepared_spells[].spell_key",
    "inventory_state[].item_ref",
    "active_infusions[].infusion_ref",
    "spell_storing_item.spell_ref",
}


def test_m03b_build_and_state_stable_key_inventory_is_explicit() -> None:
    assert BUILD_STABLE_KEY_PATHS == EXPECTED_BUILD_PATHS
    assert STATE_STABLE_KEY_PATHS == EXPECTED_STATE_PATHS


def test_m03b_walker_audit_fails_for_new_unwalked_ref_field() -> None:
    with pytest.raises(RuntimeError, match="walker inventory is stale"):
        assert_no_unwalked_stable_keys(
            {"future_feature_ref": "xge:feature:future-feature"},
            set(),
            root="build",
        )


def test_m03b_walker_audit_accepts_ref_already_in_explicit_walk() -> None:
    assert_no_unwalked_stable_keys(
        {"future_feature_ref": "xge:feature:future-feature"},
        {"xge:feature:future-feature"},
        root="build",
    )
