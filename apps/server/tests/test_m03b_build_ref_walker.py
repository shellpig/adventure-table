"""M03-B B.3 — the explicit StableKey walker and its staleness audit."""

from __future__ import annotations

import re

import pytest

from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.interop.content_ref_walker import (
    BUILD_REF_FIELD_NAMES,
    BUILD_STABLE_KEY_PATHS,
    STATE_REF_FIELD_NAMES,
    STATE_STABLE_KEY_PATHS,
    assert_no_unwalked_stable_keys,
    collect_build_refs,
    collect_state_refs,
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

# P0-C deterministic fixture, listed by hand so a walker change has to be
# argued for rather than absorbed by a self-generated expectation.
P0_FIXTURE_BUILD_REFS = {
    "srd5.1:ability:con",
    "srd5.1:ability:str",
    "srd5.1:background:acolyte",
    "srd5.1:class:fighter",
    "srd5.1:class:wizard",
    "srd5.1:equipment:chain-mail",
    "srd5.1:equipment:longsword",
    "srd5.1:equipment:shield",
    "srd5.1:feature:arcane-recovery",
    "srd5.1:feature:second-wind",
    "srd5.1:item:potion-of-healing-common",
    "srd5.1:race:human",
    "srd5.1:skill:arcana",
    "srd5.1:skill:athletics",
    "srd5.1:skill:perception",
    "srd5.1:spell:detect-magic",
    "srd5.1:spell:fireball",
    "srd5.1:spell:magic-missile",
    "srd5.1:spell:shield",
    "srd5.1:subclass:champion",
    "srd5.1:subclass:evocation",
}

P0_FIXTURE_STATE_REFS = {
    "srd5.1:equipment:chain-mail",
    "srd5.1:equipment:longsword",
    "srd5.1:equipment:shield",
    "srd5.1:item:potion-of-healing-common",
}


def _fixture() -> tuple[object, object]:
    build = build_p0_fighter_wizard_fixture()
    return build, build_p0_fighter_wizard_state(build)


def test_m03b_build_and_state_stable_key_inventory_is_explicit() -> None:
    assert BUILD_STABLE_KEY_PATHS == EXPECTED_BUILD_PATHS
    assert STATE_STABLE_KEY_PATHS == EXPECTED_STATE_PATHS


def test_m03b_audit_field_names_derive_from_the_declared_inventory() -> None:
    """One source of truth: the audit cannot drift from the path inventory."""

    expected_build = {
        re.sub(r"\[[^\]]*\]", "", path).rsplit(".", 1)[-1]
        for path in BUILD_STABLE_KEY_PATHS
        if not path.startswith("numeric_overrides[")
    }
    assert BUILD_REF_FIELD_NAMES == expected_build
    assert STATE_REF_FIELD_NAMES == {
        re.sub(r"\[[^\]]*\]", "", path).rsplit(".", 1)[-1]
        for path in STATE_STABLE_KEY_PATHS
    }


def test_m03b_walker_returns_the_expected_refs_for_the_p0_fixture() -> None:
    build, state = _fixture()
    assert {ref.stable_key for ref in collect_build_refs(build)} == P0_FIXTURE_BUILD_REFS
    assert {ref.stable_key for ref in collect_state_refs(state)} == P0_FIXTURE_STATE_REFS
    assert {ref.pack for ref in collect_build_refs(build)} == {"srd5.1"}


def test_m03b_walker_is_deterministic_across_repeated_calls() -> None:
    build, state = _fixture()
    assert collect_build_refs(build) == collect_build_refs(build)
    assert collect_state_refs(state) == collect_state_refs(state)


def test_m03b_walker_accepts_serialized_payloads_identically() -> None:
    build, state = _fixture()
    assert collect_build_refs(build.model_dump(mode="json")) == collect_build_refs(build)
    assert collect_state_refs(state.model_dump(mode="json")) == collect_state_refs(state)


@pytest.mark.parametrize(
    "dropped",
    ["class_progression", "skill_choices", "saving_throw_proficiencies", "feature_refs"],
)
def test_m03b_audit_catches_a_contractual_field_the_walk_stopped_collecting(
    dropped: str,
) -> None:
    build, _ = _fixture()
    payload = build.model_dump(mode="python")
    walked = {ref.stable_key for ref in collect_build_refs(build)}
    stopped = {value for value in payload[dropped] if isinstance(value, str)}
    assert stopped, f"{dropped} must be populated for this test to mean anything"

    with pytest.raises(RuntimeError, match="walker inventory is stale"):
        assert_no_unwalked_stable_keys(
            payload,
            walked - stopped,
            root="build",
            field_names=BUILD_REF_FIELD_NAMES,
        )


def test_m03b_audit_ignores_free_form_roleplay_text_shaped_like_a_ref() -> None:
    """Player prose is never a portability requirement, whatever it is named."""

    build, _ = _fixture()
    hostile = build.model_copy(
        update={
            "roleplay_profile": build.roleplay_profile.model_copy(
                update={"custom_fields": {"patron_ref": ("srd5.1:race:elf",)}}
            )
        }
    )
    assert collect_build_refs(hostile) == collect_build_refs(build)


def test_m03b_audit_ignores_fields_outside_the_declared_inventory() -> None:
    """A new model field is the schema inventory test's job, not a 500."""

    assert_no_unwalked_stable_keys(
        {"future_feature_ref": "xge:feature:future-feature"},
        set(),
        root="build",
        field_names=BUILD_REF_FIELD_NAMES,
    )
