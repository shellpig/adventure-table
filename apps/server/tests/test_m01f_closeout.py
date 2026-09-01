from __future__ import annotations

from copy import deepcopy

import pytest

from app.content import load_default_content_registry
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character.schemas import AncestralLegacySelection, ConditionState
from app.domain.character_builder.lineages import (
    ASI_PATTERN_1_1_1,
    ASI_PATTERN_2_1,
    LINEAGE_ASI_PATTERN_CHOICE_ID,
    LINEAGE_ASI_PLUS_ONE_CHOICE_ID,
    LINEAGE_ASI_PLUS_TWO_CHOICE_ID,
    LINEAGE_ASI_TRIPLE_CHOICE_ID,
    LINEAGE_MOVEMENT_CHOICE_ID,
    LINEAGE_SIZE_CHOICE_ID,
    LINEAGE_SKILL_CHOICE_ID,
    build_lineage_choices,
    compile_lineage,
    eligible_ancestral_movements,
    eligible_ancestral_skills,
)
from app.domain.character_builder.reconciliation import reconcile_character_state
from app.domain.character_builder.schemas import BuilderChoiceSelection, BuilderMode
from app.domain.character_builder.structural import validate_structural_choice_integrity
from app.domain.character_builder.validation import validate_foundation_draft
from app.domain.rules.hit_points import calculate_max_hp
from test_m01f_dhampir_lineage import (
    ARCANA,
    DARKVISION,
    DEATHLESS_NATURE,
    DHAMPIR,
    HALF_ELF,
    PERCEPTION,
    SPIDER_CLIMB,
    STEALTH,
    VAMPIRIC_BITE,
    _base_build,
    _direct_lineage_selections,
    _draft,
    _selection,
)


def _branch_b_selections(*abilities: str) -> dict[str, BuilderChoiceSelection]:
    selections = _direct_lineage_selections()
    selections.pop(LINEAGE_ASI_PLUS_TWO_CHOICE_ID, None)
    selections.pop(LINEAGE_ASI_PLUS_ONE_CHOICE_ID, None)
    selections[LINEAGE_ASI_PATTERN_CHOICE_ID] = _selection(
        LINEAGE_ASI_PATTERN_CHOICE_ID,
        ASI_PATTERN_1_1_1,
    )
    selections[LINEAGE_ASI_TRIPLE_CHOICE_ID] = _selection(
        LINEAGE_ASI_TRIPLE_CHOICE_ID,
        *(f"lineage-ability:{ability}:1" for ability in abilities),
    )
    return selections


def _server_choice_issues(draft, registry):
    choices = build_lineage_choices(draft, registry)
    return (
        *validate_foundation_draft(draft, registry, choices),
        *validate_structural_choice_integrity(draft, choices),
    )


def test_f2_branch_b_requires_exactly_three_distinct_abilities() -> None:
    registry = load_default_content_registry()

    valid = _draft(selections=_branch_b_selections("str", "dex", "con"))
    valid_issues = [
        issue
        for issue in _server_choice_issues(valid, registry)
        if issue.path.endswith(LINEAGE_ASI_TRIPLE_CHOICE_ID)
    ]
    assert valid_issues == []

    for abilities in (
        ("str", "str", "con"),
        ("str", "dex"),
        ("str", "dex", "con", "wis"),
    ):
        draft = _draft(selections=_branch_b_selections(*abilities))
        issues = [
            issue
            for issue in _server_choice_issues(draft, registry)
            if issue.path.endswith(LINEAGE_ASI_TRIPLE_CHOICE_ID)
        ]
        assert issues, abilities
        assert any(issue.severity.value == "blocking_error" for issue in issues)


def test_f3_small_is_valid_and_invalid_size_is_server_blocked() -> None:
    registry = load_default_content_registry()
    selections = _direct_lineage_selections()
    selections[LINEAGE_SIZE_CHOICE_ID] = _selection(
        LINEAGE_SIZE_CHOICE_ID,
        "lineage-size:small",
    )
    small = _draft(selections=selections)
    small_issues = [
        issue
        for issue in _server_choice_issues(small, registry)
        if issue.path.endswith(LINEAGE_SIZE_CHOICE_ID)
    ]
    assert small_issues == []
    assert compile_lineage(small, registry).size == "small"

    invalid_selections = dict(selections)
    invalid_selections[LINEAGE_SIZE_CHOICE_ID] = _selection(
        LINEAGE_SIZE_CHOICE_ID,
        "lineage-size:large",
    )
    invalid = _draft(selections=invalid_selections)
    issues = [
        issue
        for issue in _server_choice_issues(invalid, registry)
        if issue.path.endswith(LINEAGE_SIZE_CHOICE_ID)
    ]
    assert any(issue.code == "invalid_choice_option" for issue in issues)
    assert compile_lineage(invalid, registry).size is None


def test_f4_direct_ancestral_legacy_rejects_duplicate_skill() -> None:
    registry = load_default_content_registry()
    selections = _direct_lineage_selections()
    selections[LINEAGE_SKILL_CHOICE_ID] = _selection(
        LINEAGE_SKILL_CHOICE_ID,
        PERCEPTION,
        PERCEPTION,
    )
    draft = _draft(selections=selections)
    issues = [
        issue
        for issue in _server_choice_issues(draft, registry)
        if issue.path.endswith(LINEAGE_SKILL_CHOICE_ID)
    ]
    assert any(issue.code == "duplicate_choice_option" for issue in issues)


def test_f5_origin_fixture_matrix_covers_skill_swim_fly_and_forbidden_only_origins() -> None:
    registry = load_default_content_registry()

    skill_draft = _draft(
        mode=BuilderMode.BUILD_EDIT,
        selections={
            "legacy:skill-versatility": _selection(
                "legacy:skill-versatility",
                "srd5.1:proficiency:skill-perception",
                source_ref="srd5.1:trait:skill-versatility",
            )
        },
    )
    assert eligible_ancestral_skills(skill_draft, registry, _base_build()) == (PERCEPTION,)

    swim_base = _base_build(fly_speed=None).model_copy(
        update={
            "race_variant_ref": "scag:race-variant:half-elf-aquatic-descent",
            "climb_speed": None,
            "swim_speed": 30,
        }
    )
    assert eligible_ancestral_movements(swim_base) == ("swim",)

    fly_base = _base_build(fly_speed=None).model_copy(
        update={
            "race_ref": "vgm:race:aasimar",
            "subrace_ref": "vgm:subrace:protector-aasimar",
            "climb_speed": None,
            "fly_speed": 30,
        }
    )
    assert eligible_ancestral_movements(fly_base) == ("fly",)

    forbidden_only = _base_build(skill_choices=(), fly_speed=None).model_copy(
        update={
            "race_ref": "vgm:race:hobgoblin",
            "climb_speed": None,
            "proficiencies": ("srd5.1:proficiency:light-armor",),
            "feature_refs": ("vgm:feature:saving-face",),
        }
    )
    forbidden_draft = _draft(mode=BuilderMode.BUILD_EDIT, selections={})
    forbidden_choices = build_lineage_choices(
        forbidden_draft,
        registry,
        base_build=forbidden_only,
    )
    assert not any(
        choice.option_source in {
            "content:lineage-legacy-skill",
            "content:lineage-legacy-movement",
        }
        for choice in forbidden_choices
    )


def test_f7_forbidden_legacy_categories_are_not_exposed_as_retention_options() -> None:
    registry = load_default_content_registry()
    base = _base_build(skill_choices=(), fly_speed=None).model_copy(
        update={
            "race_ref": "vgm:race:hobgoblin",
            "walking_speed": 30,
            "climb_speed": None,
            "proficiencies": ("srd5.1:proficiency:light-armor",),
            "feature_refs": ("vgm:feature:saving-face",),
            "spell_access_entries": (),
        }
    )
    draft = _draft(mode=BuilderMode.BUILD_EDIT, selections={})
    choices = build_lineage_choices(draft, registry, base_build=base)

    retention_sources = {
        choice.option_source
        for choice in choices
        if choice.option_source and "legacy" in choice.option_source
    }
    option_ids = {
        option.option_id
        for choice in choices
        for option in choice.options
    }

    # Old racial ASI, weapon/armor proficiencies, racial spells, and unrelated
    # traits/features never become Ancestral Legacy choices. Walking speed is
    # also explicitly absent; only climb/fly/swim may be retained.
    assert "content:ability_bonus_options" not in retention_sources
    assert "srd5.1:proficiency:light-armor" not in option_ids
    assert "vgm:feature:saving-face" not in option_ids
    assert not any("spell" in source for source in retention_sources)
    assert "lineage-movement:walk" not in option_ids

    # A malicious walking-speed retention payload is rejected by the lineage
    # compiler instead of being silently accepted.
    malicious = {
        LINEAGE_SIZE_CHOICE_ID: _selection(
            LINEAGE_SIZE_CHOICE_ID,
            "lineage-size:medium",
        ),
        LINEAGE_MOVEMENT_CHOICE_ID: _selection(
            LINEAGE_MOVEMENT_CHOICE_ID,
            "lineage-movement:walk",
        ),
    }
    rejected = compile_lineage(
        _draft(mode=BuilderMode.BUILD_EDIT, selections=malicious),
        registry,
        base_build=base,
    )
    assert any(
        issue.code == "illegal_ancestral_legacy_movement"
        for issue in rejected.issues
    )


def test_f10_dhampir_reconciliation_preserves_live_state_and_starting_equipment() -> None:
    registry = load_default_content_registry()
    old_build = build_p0_fighter_wizard_fixture()
    old_max = calculate_max_hp(old_build)
    old_state = build_p0_fighter_wizard_state(old_build)
    live_inventory = deepcopy(old_state.inventory_state)
    live_inventory[0] = live_inventory[0].model_copy(update={"quantity": 2})
    old_state = old_state.model_copy(
        update={
            "current_hp": old_max - 9,
            "temporary_hp": 7,
            "conditions": [
                ConditionState(
                    condition_ref="srd5.1:condition:poisoned",
                    note="persists through lineage transformation",
                )
            ],
            "inventory_state": live_inventory,
        }
    )

    new_build = old_build.model_copy(
        update={
            "lineage_ref": DHAMPIR,
            "ancestral_origin_ref": old_build.race_ref,
            "ancestral_legacy": AncestralLegacySelection(),
            "size": "medium",
            "walking_speed": 35,
            "climb_speed": 35,
            "feature_refs": (
                *old_build.feature_refs,
                DARKVISION,
                DEATHLESS_NATURE,
                SPIDER_CLIMB,
                VAMPIRIC_BITE,
            ),
        }
    )
    preview = reconcile_character_state(old_build, old_state, new_build, registry)

    assert preview.can_apply is True, preview.blocking_issues
    assert preview.proposed_state.current_hp == calculate_max_hp(new_build) - 9
    assert preview.proposed_state.temporary_hp == 7
    assert preview.proposed_state.conditions == old_state.conditions
    assert preview.proposed_state.inventory_state == live_inventory
    assert preview.proposed_state.prepared_spell_entry_ids == old_state.prepared_spell_entry_ids
    assert preview.proposed_state.prepared_spells == old_state.prepared_spells
    assert new_build.starting_equipment == old_build.starting_equipment


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("climb", 35),
        ("fly", 50),
        ("swim", 30),
    ],
)
def test_f5_legal_movement_retention_modes_compile(mode: str, expected: int) -> None:
    registry = load_default_content_registry()
    base = _base_build(fly_speed=50).model_copy(update={"swim_speed": 30})
    selections = {
        LINEAGE_SIZE_CHOICE_ID: _selection(
            LINEAGE_SIZE_CHOICE_ID,
            "lineage-size:medium",
        ),
        LINEAGE_MOVEMENT_CHOICE_ID: _selection(
            LINEAGE_MOVEMENT_CHOICE_ID,
            f"lineage-movement:{mode}",
        ),
    }
    compiled = compile_lineage(
        _draft(mode=BuilderMode.BUILD_EDIT, selections=selections),
        registry,
        base_build=base,
    )
    assert not compiled.issues
    actual = {
        "climb": compiled.climb_speed,
        "fly": compiled.fly_speed,
        "swim": compiled.swim_speed,
    }[mode]
    assert actual == expected
