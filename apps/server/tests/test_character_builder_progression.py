from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.content import load_default_content_registry
from app.domain.character_builder.compiler import compile_builder_draft
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderLevelChoice,
    BuilderMode,
    BuilderReferenceSelection,
    BuilderSpellChoiceInput,
)


DIRECT_SOURCES = {
    "content:race",
    "content:background",
    "content:alignment",
    "content:subrace",
    "content:class",
    "content:subclass",
    "builder:ability-generation",
}


def _draft(payload: BuilderDraftPayload) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=payload,
        created_at=now,
        updated_at=now,
    )


def _scores(
    strength: int = 15,
    dexterity: int = 13,
    constitution: int = 12,
    intelligence: int = 14,
    wisdom: int = 10,
    charisma: int = 8,
) -> dict[str, int]:
    return {
        "strength": strength,
        "dexterity": dexterity,
        "constitution": constitution,
        "intelligence": intelligence,
        "wisdom": wisdom,
        "charisma": charisma,
    }


def _level(
    character_level: int,
    class_name: str,
    *,
    hp: int,
    subclass: str | None = None,
    manual: bool = False,
) -> BuilderLevelChoice:
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=f"srd5.1:class:{class_name}",
        hp_method=(
            "first_level"
            if character_level == 1
            else ("manual_rolled" if manual else "fixed_average")
        ),
        hp_base_gain=hp,
        subclass_ref=(f"srd5.1:subclass:{subclass}" if subclass else None),
    )


def _payload(levels: tuple[BuilderLevelChoice, ...], *, scores: dict[str, int] | None = None) -> BuilderDraftPayload:
    return BuilderDraftPayload(
        basic=BuilderBasicInput(name="P1-C Hero"),
        target_level=len(levels),
        race_selection=BuilderReferenceSelection(reference_id="srd5.1:race:human"),
        background_selection=BuilderReferenceSelection(reference_id="srd5.1:background:acolyte"),
        ability_generation={
            "method": "standard_array",
            "scores": scores or _scores(),
        },
        level_choices=levels,
    )


def _spell_choices_for_profiles(result) -> dict[str, BuilderSpellChoiceInput]:
    choices: dict[str, BuilderSpellChoiceInput] = {}
    for profile in result.resolved_summary.spellcasting_profiles:
        cantrips = tuple(
            spell.spell_key
            for spell in profile.available_spells
            if spell.level == 0
        )[: profile.cantrip_count]
        leveled = tuple(
            spell.spell_key
            for spell in profile.available_spells
            if 1 <= spell.level <= profile.max_spell_level
        )
        choices[profile.profile_id] = BuilderSpellChoiceInput(
            cantrip_keys=cantrips,
            known_spell_keys=leveled[: profile.known_spell_count],
            spellbook_spell_keys=leveled[: profile.spellbook_count],
            # Preparing fewer than the cap is legal; these P1-C regressions do
            # not exercise daily preparation and intentionally leave it empty.
            prepared_spell_keys=(),
        )
    return choices


def _with_required_choices(payload: BuilderDraftPayload, registry):
    selections: dict[str, BuilderChoiceSelection] = {}
    used_reference_option_ids: set[str] = set()

    # Resolve one required choice at a time and recompile after each selection.
    # P1-D choices can change the legality of later choices (for example, an
    # earlier ASI can bring an ability to the score cap), so a one-pass fixture
    # would be able to manufacture a draft that the real builder would reject.
    for _ in range(128):
        current = payload.model_copy(update={"choice_selections": selections})
        result = compile_builder_draft(_draft(current), registry)
        unresolved = next(
            (
                choice
                for choice in result.choices
                if choice.required
                and choice.disabled_reason is None
                and choice.option_source not in DIRECT_SOURCES
                and choice.choice_id not in selections
            ),
            None,
        )
        if unresolved is None:
            # P1-E makes spellcasting a required part of a complete Build.
            # Upgrade the older P1-C/P1-D fixture by selecting deterministic,
            # low-level legal spells from the server-resolved profile options.
            spell_choices = dict(current.spell_choices)
            for profile_id, selection in _spell_choices_for_profiles(result).items():
                spell_choices.setdefault(profile_id, selection)
            return _draft(current.model_copy(update={"spell_choices": spell_choices}))

        available = [
            option
            for option in unresolved.options
            if option.disabled_reason is None
            and (
                unresolved.allow_duplicates
                or option.reference_id is None
                or option.option_id not in used_reference_option_ids
            )
        ]
        assert available, unresolved.choice_id
        if unresolved.allow_duplicates:
            selected = tuple(
                available[0].option_id for _ in range(unresolved.choose_count)
            )
        else:
            assert len(available) >= unresolved.choose_count, unresolved.choice_id
            selected = tuple(
                option.option_id for option in available[: unresolved.choose_count]
            )
        for option_id in selected:
            option = next(
                item for item in unresolved.options if item.option_id == option_id
            )
            if option.reference_id is not None:
                used_reference_option_ids.add(option_id)
        selections[unresolved.choice_id] = BuilderChoiceSelection(
            choice_id=unresolved.choice_id,
            source_ref=unresolved.source_ref,
            selected_option_ids=selected,
        )

    raise AssertionError("required choices did not converge")


def _codes(result) -> set[str]:
    return {issue.code for issue in result.validation.issues}


def _fighter_levels(target: int) -> tuple[BuilderLevelChoice, ...]:
    return tuple(
        _level(
            level,
            "fighter",
            hp=10 if level == 1 else 6,
            subclass="champion" if level == 3 else None,
        )
        for level in range(1, target + 1)
    )


@pytest.mark.parametrize("target_level", range(1, 21))
def test_ordered_fighter_progression_compiles_level_one_through_twenty(target_level: int) -> None:
    registry = load_default_content_registry()
    payload = _payload(_fighter_levels(target_level))
    draft = _with_required_choices(payload, registry)
    result = compile_builder_draft(draft, registry)

    assert "incomplete_level_progression" not in _codes(result)
    assert "invalid_first_level_hp" not in _codes(result)
    assert result.resolved_summary.progression[-1].character_level == target_level
    assert result.resolved_summary.progression[-1].class_level == target_level
    assert [node.class_ref for node in result.resolved_summary.progression] == [
        "srd5.1:class:fighter"
    ] * target_level
    assert result.build_candidate is not None
    assert result.build_candidate.character_level == target_level
    assert result.build_candidate.class_progression == ("srd5.1:class:fighter",) * target_level
    assert len(result.build_candidate.hp_progression) == target_level


def test_direct_high_level_create_exposes_one_ordered_class_node_per_character_level() -> None:
    registry = load_default_content_registry()
    payload = BuilderDraftPayload(
        basic=BuilderBasicInput(name="Rail"),
        target_level=10,
    )
    result = compile_builder_draft(_draft(payload), registry)

    class_choices = [choice for choice in result.choices if choice.option_source == "content:class"]
    assert len(class_choices) == 10
    assert [choice.choice_id for choice in class_choices] == [
        f"level:{level}:class-selection" for level in range(1, 11)
    ]


def test_fighter_five_wizard_five_preserves_exact_acquisition_order_and_rebuilds_p0_shape() -> None:
    registry = load_default_content_registry()
    levels = (
        _level(1, "fighter", hp=10),
        _level(2, "fighter", hp=6),
        _level(3, "fighter", hp=6, subclass="champion"),
        _level(4, "fighter", hp=6),
        _level(5, "fighter", hp=6),
        _level(6, "wizard", hp=4),
        _level(7, "wizard", hp=4, subclass="evocation"),
        _level(8, "wizard", hp=4),
        _level(9, "wizard", hp=4),
        _level(10, "wizard", hp=4),
    )
    draft = _with_required_choices(_payload(levels), registry)
    result = compile_builder_draft(draft, registry)

    assert result.build_candidate is not None
    build = result.build_candidate
    assert build.class_progression == (
        *("srd5.1:class:fighter",) * 5,
        *("srd5.1:class:wizard",) * 5,
    )
    assert build.hp_progression == (10, 6, 6, 6, 6, 4, 4, 4, 4, 4)
    assert {(item.class_ref, item.subclass_ref) for item in build.subclasses} == {
        ("srd5.1:class:fighter", "srd5.1:subclass:champion"),
        ("srd5.1:class:wizard", "srd5.1:subclass:evocation"),
    }
    assert result.resolved_summary.starting_class_name == "Fighter"
    assert result.resolved_summary.class_summary == "Fighter 5 / Wizard 5"
    assert "srd5.1:feature:second-wind" in build.feature_refs
    assert "srd5.1:feature:arcane-recovery" in build.feature_refs


def test_interleaved_progression_tracks_class_level_not_total_level() -> None:
    registry = load_default_content_registry()
    levels = (
        _level(1, "wizard", hp=6),
        _level(2, "fighter", hp=6),
        _level(3, "wizard", hp=4, subclass="evocation"),
        _level(4, "wizard", hp=4),
    )
    draft = _with_required_choices(
        _payload(levels, scores=_scores(strength=14, intelligence=15)),
        registry,
    )
    result = compile_builder_draft(draft, registry)

    nodes = result.resolved_summary.progression
    assert [(node.class_name, node.class_level) for node in nodes] == [
        ("Wizard", 1),
        ("Fighter", 1),
        ("Wizard", 2),
        ("Wizard", 3),
    ]
    assert nodes[2].subclass_required is True
    assert result.build_candidate is not None


def test_starting_class_grants_do_not_reappear_when_multiclassing() -> None:
    registry = load_default_content_registry()
    fighter_first = _with_required_choices(
        _payload(
            (
                _level(1, "fighter", hp=10),
                _level(2, "wizard", hp=4),
                _level(3, "wizard", hp=4, subclass="evocation"),
            )
        ),
        registry,
    )
    wizard_first = _with_required_choices(
        _payload(
            (
                _level(1, "wizard", hp=6),
                _level(2, "fighter", hp=6),
                _level(3, "fighter", hp=6),
                _level(4, "fighter", hp=6, subclass="champion"),
            ),
            scores=_scores(strength=14, intelligence=15),
        ),
        registry,
    )

    fighter_build = compile_builder_draft(fighter_first, registry).build_candidate
    wizard_build = compile_builder_draft(wizard_first, registry).build_candidate
    assert fighter_build is not None and wizard_build is not None
    assert fighter_build.saving_throw_proficiencies == (
        "srd5.1:ability:str",
        "srd5.1:ability:con",
    )
    assert wizard_build.saving_throw_proficiencies == (
        "srd5.1:ability:int",
        "srd5.1:ability:wis",
    )
    assert "srd5.1:proficiency:all-armor" in fighter_build.proficiencies
    assert "srd5.1:proficiency:all-armor" not in wizard_build.proficiencies


def test_multiclass_prerequisites_block_target_and_existing_class_failures() -> None:
    registry = load_default_content_registry()
    legal = _payload(
        (
            _level(1, "wizard", hp=6),
            _level(2, "fighter", hp=6),
        ),
        scores=_scores(strength=14, intelligence=15),
    )
    legal_result = compile_builder_draft(_draft(legal), registry)
    legal_class_choice = next(
        choice for choice in legal_result.choices if choice.choice_id == "level:2:class-selection"
    )
    legal_fighter_option = next(
        option for option in legal_class_choice.options if option.option_id == "srd5.1:class:fighter"
    )
    assert legal_fighter_option.disabled_reason is None
    assert "multiclass_prerequisite_not_met" not in _codes(legal_result)

    human_bonus_boundary = _payload(
        (
            _level(1, "wizard", hp=6),
            _level(2, "fighter", hp=6),
        ),
        scores=_scores(strength=12, dexterity=8, constitution=10, intelligence=14, wisdom=13, charisma=15),
    )
    boundary_result = compile_builder_draft(_draft(human_bonus_boundary), registry)
    boundary_class_choice = next(
        choice for choice in boundary_result.choices if choice.choice_id == "level:2:class-selection"
    )
    boundary_fighter_option = next(
        option for option in boundary_class_choice.options if option.option_id == "srd5.1:class:fighter"
    )
    assert boundary_fighter_option.disabled_reason is None
    assert "multiclass_prerequisite_not_met" not in _codes(boundary_result)

    low_physical = _payload(
        (
            _level(1, "wizard", hp=6),
            _level(2, "fighter", hp=6),
        ),
        scores=_scores(strength=8, dexterity=11, constitution=12, intelligence=15, wisdom=14, charisma=10),
    )
    result = compile_builder_draft(_draft(low_physical), registry)
    assert "multiclass_prerequisite_not_met" in _codes(result)

    class_choice = next(
        choice for choice in result.choices if choice.choice_id == "level:2:class-selection"
    )
    fighter_option = next(option for option in class_choice.options if option.option_id == "srd5.1:class:fighter")
    assert fighter_option.disabled_reason is not None

    low_intelligence = _payload(
        (
            _level(1, "wizard", hp=6),
            _level(2, "fighter", hp=6),
        ),
        scores=_scores(strength=15, dexterity=13, constitution=12, intelligence=8, wisdom=14, charisma=10),
    )
    result = compile_builder_draft(_draft(low_intelligence), registry)
    assert "multiclass_prerequisite_not_met" in _codes(result)
    assert any("Wizard" in issue.message for issue in result.validation.issues)


def test_subclass_timing_rejects_missing_early_and_wrong_class_selections() -> None:
    registry = load_default_content_registry()
    missing = compile_builder_draft(_draft(_payload(
        (
            _level(1, "fighter", hp=10),
            _level(2, "fighter", hp=6),
            _level(3, "fighter", hp=6),
        )
    )), registry)
    assert "missing_subclass_at_timing" in _codes(missing)

    early = compile_builder_draft(_draft(_payload(
        (
            _level(1, "fighter", hp=10, subclass="champion"),
            _level(2, "fighter", hp=6),
        )
    )), registry)
    assert "subclass_selected_too_early" in _codes(early)

    wrong = compile_builder_draft(_draft(_payload(
        (
            _level(1, "fighter", hp=10),
            _level(2, "fighter", hp=6),
            _level(3, "fighter", hp=6, subclass="evocation"),
        )
    )), registry)
    assert "subclass_class_mismatch" in _codes(wrong)


def test_automatic_features_follow_reached_class_levels_only() -> None:
    registry = load_default_content_registry()
    first = compile_builder_draft(
        _with_required_choices(_payload(_fighter_levels(1)), registry), registry
    )
    second = compile_builder_draft(
        _with_required_choices(_payload(_fighter_levels(2)), registry), registry
    )
    assert first.build_candidate is not None and second.build_candidate is not None
    assert "srd5.1:feature:second-wind" in first.build_candidate.feature_refs
    assert "srd5.1:feature:action-surge-1-use" not in first.build_candidate.feature_refs
    assert "srd5.1:feature:action-surge-1-use" in second.build_candidate.feature_refs


def test_hp_rules_distinguish_first_character_level_fixed_average_and_manual_rolls() -> None:
    registry = load_default_content_registry()
    invalid_first = _payload((_level(1, "fighter", hp=6),))
    raw = invalid_first.model_dump(mode="python")
    raw["level_choices"][0]["hp_method"] = "fixed_average"
    result = compile_builder_draft(
        _draft(BuilderDraftPayload.model_validate(raw)), registry
    )
    assert "invalid_first_level_hp" in _codes(result)

    manual = _payload(
        (
            _level(1, "fighter", hp=10),
            _level(2, "fighter", hp=9, manual=True),
        )
    )
    assert "invalid_manual_hp_roll" not in _codes(
        compile_builder_draft(_draft(manual), registry)
    )

    illegal_roll = _payload(
        (
            _level(1, "fighter", hp=10),
            _level(2, "fighter", hp=11, manual=True),
        )
    )
    assert "invalid_manual_hp_roll" in _codes(
        compile_builder_draft(_draft(illegal_roll), registry)
    )

    multiclass_first_wizard_level = _payload(
        (
            _level(1, "fighter", hp=10),
            _level(2, "wizard", hp=6),
        )
    )
    raw = multiclass_first_wizard_level.model_dump(mode="python")
    raw["level_choices"][1]["hp_method"] = "first_level"
    result = compile_builder_draft(
        _draft(BuilderDraftPayload.model_validate(raw)), registry
    )
    assert "first_level_hp_only_at_character_level_one" in _codes(result)


def test_editing_an_earlier_node_marks_stale_downstream_subclass_as_needs_review() -> None:
    registry = load_default_content_registry()
    valid = _payload(
        (
            _level(1, "fighter", hp=10),
            _level(2, "fighter", hp=6),
            _level(3, "fighter", hp=6, subclass="champion"),
            _level(4, "fighter", hp=6),
        )
    )
    raw = valid.model_dump(mode="python")
    raw["level_choices"][2]["class_ref"] = "srd5.1:class:wizard"
    raw["level_choices"][2]["hp_base_gain"] = 4
    edited = BuilderDraftPayload.model_validate(raw)
    result = compile_builder_draft(_draft(edited), registry)

    assert "subclass_class_mismatch" in _codes(result)
    assert result.build_candidate is None
