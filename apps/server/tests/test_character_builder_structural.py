from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

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
)
from app.domain.character_builder.structural import asi_occurrences_at_class_level


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


def _level(
    character_level: int,
    class_name: str,
    *,
    hp: int,
    subclass: str | None = None,
) -> BuilderLevelChoice:
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=f"srd5.1:class:{class_name}",
        hp_method="first_level" if character_level == 1 else "fixed_average",
        hp_base_gain=hp,
        subclass_ref=(f"srd5.1:subclass:{subclass}" if subclass else None),
    )


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


def _payload(
    levels: tuple[BuilderLevelChoice, ...],
    *,
    strength: int = 15,
    dexterity: int = 13,
    constitution: int = 12,
    intelligence: int = 14,
    wisdom: int = 10,
    charisma: int = 8,
    numeric_overrides: tuple[dict[str, object], ...] = (),
    selections: dict[str, BuilderChoiceSelection] | None = None,
) -> BuilderDraftPayload:
    return BuilderDraftPayload(
        basic=BuilderBasicInput(name="P1-D Hero"),
        target_level=len(levels),
        race_selection=BuilderReferenceSelection(reference_id="srd5.1:race:human"),
        background_selection=BuilderReferenceSelection(reference_id="srd5.1:background:acolyte"),
        ability_generation={
            "method": "manual",
            "scores": {
                "strength": strength,
                "dexterity": dexterity,
                "constitution": constitution,
                "intelligence": intelligence,
                "wisdom": wisdom,
                "charisma": charisma,
            },
        },
        level_choices=levels,
        choice_selections=selections or {},
        numeric_overrides=numeric_overrides,
    )


def _selection(choice_id: str, *option_ids: str) -> BuilderChoiceSelection:
    return BuilderChoiceSelection(
        choice_id=choice_id,
        selected_option_ids=tuple(option_ids),
    )


def _auto_fill_required(payload: BuilderDraftPayload):
    registry = load_default_content_registry()
    selections = dict(payload.choice_selections)
    used_reference_options: set[str] = set()

    for _ in range(8):
        current = payload.model_copy(update={"choice_selections": selections})
        result = compile_builder_draft(_draft(current), registry)
        changed = False
        for choice in result.choices:
            if (
                not choice.required
                or choice.disabled_reason is not None
                or choice.option_source in DIRECT_SOURCES
                or choice.choice_id in selections
            ):
                continue
            available = [
                option
                for option in choice.options
                if option.disabled_reason is None
                and (
                    choice.allow_duplicates
                    or option.reference_id is None
                    or option.option_id not in used_reference_options
                )
            ]
            assert available, choice.choice_id
            if choice.allow_duplicates:
                selected = tuple(available[0].option_id for _ in range(choice.choose_count))
            else:
                assert len(available) >= choice.choose_count, choice.choice_id
                selected = tuple(option.option_id for option in available[: choice.choose_count])
            for option_id in selected:
                option = next(item for item in choice.options if item.option_id == option_id)
                if option.reference_id is not None:
                    used_reference_options.add(option_id)
            selections[choice.choice_id] = BuilderChoiceSelection(
                choice_id=choice.choice_id,
                source_ref=choice.source_ref,
                selected_option_ids=selected,
            )
            changed = True
        if not changed:
            return _draft(payload.model_copy(update={"choice_selections": selections})), registry

    raise AssertionError("required choices did not converge")


def _codes(result) -> set[str]:
    return {issue.code for issue in result.validation.issues}


def test_fighter_asi_uses_cumulative_class_level_delta() -> None:
    registry = load_default_content_registry()

    assert asi_occurrences_at_class_level(registry, "srd5.1:class:fighter", 4) == 1
    assert asi_occurrences_at_class_level(registry, "srd5.1:class:fighter", 5) == 0
    assert asi_occurrences_at_class_level(registry, "srd5.1:class:fighter", 6) == 1


def test_all_srd_class_level_asi_deltas_are_non_negative() -> None:
    registry = load_default_content_registry()

    for class_entry in registry.list_kind("class"):
        for class_level in range(1, 21):
            assert asi_occurrences_at_class_level(registry, class_entry.key, class_level) >= 0


def test_multiclass_asi_timing_uses_same_class_level_not_total_character_level() -> None:
    levels = (
        _level(1, "wizard", hp=6),
        _level(2, "fighter", hp=6),
        _level(3, "fighter", hp=6),
        _level(4, "fighter", hp=6, subclass="champion"),
        _level(5, "fighter", hp=6),
    )
    draft, registry = _auto_fill_required(
        _payload(levels, strength=14, intelligence=14)
    )
    result = compile_builder_draft(draft, registry)
    asi_choices = [
        choice for choice in result.choices if choice.option_source == "content:asi-feat"
    ]

    assert [choice.choice_id for choice in asi_choices] == ["level:5:asi-feat:0"]
    assert not any(choice.choice_id.startswith("level:4:asi-feat") for choice in result.choices)


def test_asi_can_put_two_points_in_one_ability_and_compiles_once() -> None:
    selections = {
        "level:4:asi-feat:0": _selection("level:4:asi-feat:0", "asi"),
        "level:4:asi-abilities:0": _selection(
            "level:4:asi-abilities:0",
            "ability:strength",
            "ability:strength",
        ),
    }
    draft, registry = _auto_fill_required(
        _payload(_fighter_levels(4), strength=17, selections=selections)
    )
    result = compile_builder_draft(draft, registry)

    assert "disabled_choice_option_selected" not in _codes(result)
    assert result.build_candidate is not None
    assert result.build_candidate.ability_scores.strength == 20
    assert result.build_candidate.feat_refs == ()
    strength = next(
        score for score in result.resolved_summary.ability_scores if score.ability == "strength"
    )
    assert strength.base == 17
    assert strength.permanent_bonus == 3  # Human +1, ASI +2.
    assert strength.resolved == 20


def test_asi_split_form_compiles_both_permanent_increases() -> None:
    selections = {
        "level:4:asi-feat:0": _selection("level:4:asi-feat:0", "asi"),
        "level:4:asi-abilities:0": _selection(
            "level:4:asi-abilities:0",
            "ability:strength",
            "ability:dexterity",
        ),
    }
    draft, registry = _auto_fill_required(
        _payload(_fighter_levels(4), strength=15, dexterity=13, selections=selections)
    )
    result = compile_builder_draft(draft, registry)

    assert result.build_candidate is not None
    assert result.build_candidate.ability_scores.strength == 17
    assert result.build_candidate.ability_scores.dexterity == 15


def test_asi_cap_rejects_increase_past_twenty() -> None:
    selections = {
        "level:4:asi-feat:0": _selection("level:4:asi-feat:0", "asi"),
        "level:4:asi-abilities:0": _selection(
            "level:4:asi-abilities:0",
            "ability:strength",
            "ability:strength",
        ),
    }
    draft, registry = _auto_fill_required(
        _payload(_fighter_levels(4), strength=18, selections=selections)
    )
    result = compile_builder_draft(draft, registry)

    assert "disabled_choice_option_selected" in _codes(result)
    assert result.build_candidate is None


def test_grappler_prerequisite_blocks_below_strength_thirteen() -> None:
    selections = {
        "level:4:asi-feat:0": _selection(
            "level:4:asi-feat:0",
            "srd5.1:feat:grappler",
        ),
    }
    draft, registry = _auto_fill_required(
        _payload(_fighter_levels(4), strength=11, selections=selections)
    )
    result = compile_builder_draft(draft, registry)
    branch = next(choice for choice in result.choices if choice.choice_id == "level:4:asi-feat:0")
    grappler = next(option for option in branch.options if option.option_id == "srd5.1:feat:grappler")

    assert grappler.disabled_reason is not None
    assert "disabled_choice_option_selected" in _codes(result)
    assert result.build_candidate is None


def test_numeric_override_can_satisfy_feat_numeric_prerequisite_without_changing_build_score() -> None:
    selections = {
        "level:4:asi-feat:0": _selection(
            "level:4:asi-feat:0",
            "srd5.1:feat:grappler",
        ),
    }
    draft, registry = _auto_fill_required(
        _payload(
            _fighter_levels(4),
            strength=11,
            numeric_overrides=({"key": "ability:strength", "value": 13},),
            selections=selections,
        )
    )
    result = compile_builder_draft(draft, registry)
    branch = next(choice for choice in result.choices if choice.choice_id == "level:4:asi-feat:0")
    grappler = next(option for option in branch.options if option.option_id == "srd5.1:feat:grappler")

    assert grappler.disabled_reason is None
    assert "disabled_choice_option_selected" not in _codes(result)
    assert result.build_candidate is not None
    assert result.build_candidate.ability_scores.strength == 12  # Human +1 only.
    assert result.build_candidate.feat_refs == ("srd5.1:feat:grappler",)
    strength = next(
        score for score in result.resolved_summary.ability_scores if score.ability == "strength"
    )
    assert strength.resolved == 12
    assert strength.effective == 13
    assert strength.overridden is True


def test_switching_from_asi_to_feat_does_not_leave_stale_ability_bonus() -> None:
    selections = {
        "level:4:asi-feat:0": _selection(
            "level:4:asi-feat:0",
            "srd5.1:feat:grappler",
        ),
        "level:4:asi-abilities:0": _selection(
            "level:4:asi-abilities:0",
            "ability:strength",
            "ability:strength",
        ),
    }
    draft, registry = _auto_fill_required(
        _payload(_fighter_levels(4), strength=13, selections=selections)
    )
    result = compile_builder_draft(draft, registry)
    ability_choice = next(
        choice for choice in result.choices if choice.choice_id == "level:4:asi-abilities:0"
    )

    assert ability_choice.disabled_reason is not None
    assert result.build_candidate is not None
    assert result.build_candidate.ability_scores.strength == 14  # Human +1; stale ASI ignored.
    assert result.build_candidate.feat_refs == ("srd5.1:feat:grappler",)


def test_unknown_feat_and_extra_asi_occurrence_are_rejected() -> None:
    unknown_feat = {
        "level:4:asi-feat:0": _selection(
            "level:4:asi-feat:0",
            "srd5.1:feat:not-real",
        ),
    }
    draft, registry = _auto_fill_required(
        _payload(_fighter_levels(4), selections=unknown_feat)
    )
    result = compile_builder_draft(draft, registry)
    assert "invalid_choice_option" in _codes(result)
    assert result.build_candidate is None

    illegal_level_one = {
        "level:1:asi-feat:0": _selection("level:1:asi-feat:0", "asi"),
    }
    draft, registry = _auto_fill_required(
        _payload(_fighter_levels(1), selections=illegal_level_one)
    )
    result = compile_builder_draft(draft, registry)
    assert "invalid_choice_option" in _codes(result)
    assert result.build_candidate is None


def test_numeric_override_does_not_create_structural_eligibility() -> None:
    draft, registry = _auto_fill_required(
        _payload(
            _fighter_levels(1),
            strength=8,
            numeric_overrides=({"key": "ability:strength", "value": 20},),
        )
    )
    result = compile_builder_draft(draft, registry)

    assert not any(choice.option_source == "content:asi-feat" for choice in result.choices)
    assert not any(choice.option_source == "content:subclass" for choice in result.choices)
