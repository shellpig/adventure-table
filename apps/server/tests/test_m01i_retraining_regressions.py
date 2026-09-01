from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character.schemas import AbilityScores, CharacterBuild, SpellAccessEntry
from app.domain.character_builder.m01i_runtime import prepare_optional_class_features_for_m01i
from app.domain.character_builder.m01i_validation import (
    active_retraining_choices,
    apply_cantrip_retraining_for_m01i,
    validate_final_feature_pool_dependencies,
)
from app.domain.character_builder.optional_class_features import (
    _choice_id,
    build_optional_retraining_choices,
)
from app.domain.character_builder.schemas import (
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderHPMethod,
    BuilderLevelChoice,
    BuilderMode,
)


BARD = "srd5.1:class:bard"
SORCERER = "srd5.1:class:sorcerer"
WARLOCK = "srd5.1:class:warlock"
BARDIC_VERSATILITY = "tce:feature:bardic-versatility"
MAGE_HAND = "srd5.1:spell:mage-hand"


def _level(character_level: int, class_ref: str) -> BuilderLevelChoice:
    hit_die = 6 if class_ref == SORCERER else 8
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=class_ref,
        hp_method=(
            BuilderHPMethod.FIRST_LEVEL
            if character_level == 1
            else BuilderHPMethod.FIXED_AVERAGE
        ),
        hp_base_gain=hit_die if character_level == 1 else hit_die // 2 + 1,
    )


def _base_multiclass_build() -> CharacterBuild:
    return CharacterBuild(
        content_sources=("srd5.1",),
        race_ref="srd5.1:race:human",
        character_level=4,
        class_progression=(BARD, BARD, BARD, SORCERER),
        ability_scores=AbilityScores(
            strength=10,
            dexterity=14,
            constitution=12,
            intelligence=10,
            wisdom=10,
            charisma=16,
        ),
        spell_access_entries=(
            SpellAccessEntry(
                entry_id="class:bard:known:mage-hand",
                spell_key=MAGE_HAND,
                source_type="class",
                source_key=BARD,
                access_type="known",
                casting_ability="charisma",
            ),
            SpellAccessEntry(
                entry_id="class:sorcerer:known:mage-hand",
                spell_key=MAGE_HAND,
                source_type="class",
                source_key=SORCERER,
                access_type="known",
                casting_ability="charisma",
            ),
        ),
        hp_progression=(8, 5, 5, 4),
    )


def _level_up_draft(selections: dict[str, BuilderChoiceSelection] | None = None) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.LEVEL_UP,
        character_id=uuid4(),
        base_version_id=uuid4(),
        revision=1,
        draft_payload=BuilderDraftPayload(
            target_level=5,
            level_choices=(
                _level(1, BARD),
                _level(2, BARD),
                _level(3, BARD),
                _level(4, SORCERER),
                _level(5, BARD),
            ),
            choice_selections=selections or {},
        ),
        created_at=now,
        updated_at=now,
    )


def _selection(choice_id: str, *option_ids: str, source_ref: str | None = None) -> BuilderChoiceSelection:
    return BuilderChoiceSelection(
        choice_id=choice_id,
        source_ref=source_ref,
        selected_option_ids=tuple(option_ids),
    )


def test_versatility_controls_require_the_optional_feature_to_be_active() -> None:
    registry = load_default_content_registry()
    base = _base_multiclass_build()
    draft = _level_up_draft()
    runtime = prepare_optional_class_features_for_m01i(draft, registry, base_build=base)

    raw = build_optional_retraining_choices(draft, runtime, base_build=base)
    assert any(choice.source_ref == BARDIC_VERSATILITY for choice in raw)
    assert not active_retraining_choices(raw, runtime)

    feature_choice_id = _choice_id(draft, "optional-feature", BARDIC_VERSATILITY)
    draft = _level_up_draft(
        {
            feature_choice_id: _selection(
                feature_choice_id,
                BARDIC_VERSATILITY,
                source_ref=BARDIC_VERSATILITY,
            )
        }
    )
    runtime = prepare_optional_class_features_for_m01i(draft, registry, base_build=base)
    raw = build_optional_retraining_choices(draft, runtime, base_build=base)

    active = active_retraining_choices(raw, runtime)
    assert active
    assert {choice.source_ref for choice in active} == {BARDIC_VERSATILITY}


def test_cantrip_retraining_changes_only_the_owning_class_source() -> None:
    registry = load_default_content_registry()
    base = _base_multiclass_build()
    initial = _level_up_draft()
    feature_choice_id = _choice_id(initial, "optional-feature", BARDIC_VERSATILITY)
    draft = _level_up_draft(
        {
            feature_choice_id: _selection(
                feature_choice_id,
                BARDIC_VERSATILITY,
                source_ref=BARDIC_VERSATILITY,
            )
        }
    )
    runtime = prepare_optional_class_features_for_m01i(draft, registry, base_build=base)
    choices = active_retraining_choices(
        build_optional_retraining_choices(draft, runtime, base_build=base),
        runtime,
    )
    action = next(
        choice
        for choice in choices
        if choice.option_source == "content:optional-feature:retraining-action"
    )
    old_choice = next(
        choice
        for choice in choices
        if choice.option_source == "content:optional-feature:retraining-from:cantrip"
    )
    new_choice = next(
        choice
        for choice in choices
        if choice.option_source == "content:optional-feature:retraining-to:cantrip"
    )
    replacement = next(
        option.reference_id
        for option in new_choice.options
        if option.reference_id is not None and option.reference_id != MAGE_HAND
    )
    replace_action = action.options[0].option_id

    selections = dict(draft.draft_payload.choice_selections)
    selections[action.choice_id] = _selection(action.choice_id, replace_action, source_ref=action.source_ref)
    selections[old_choice.choice_id] = _selection(old_choice.choice_id, MAGE_HAND, source_ref=old_choice.source_ref)
    selections[new_choice.choice_id] = _selection(new_choice.choice_id, replacement, source_ref=new_choice.source_ref)
    payload = draft.draft_payload.model_copy(update={"choice_selections": selections})
    draft = draft.model_copy(update={"draft_payload": payload})
    runtime = prepare_optional_class_features_for_m01i(draft, registry, base_build=base)

    updated, issues = apply_cantrip_retraining_for_m01i(
        base.spell_access_entries,
        draft,
        runtime,
    )

    assert issues == ()
    by_source = {entry.source_key: entry.spell_key for entry in updated}
    assert by_source[BARD] == replacement
    assert by_source[SORCERER] == MAGE_HAND


def _warlock_build(*feature_refs: str) -> CharacterBuild:
    return CharacterBuild(
        content_sources=("srd5.1", "tce"),
        race_ref="srd5.1:race:human",
        character_level=5,
        class_progression=(WARLOCK,) * 5,
        ability_scores=AbilityScores(
            strength=10,
            dexterity=14,
            constitution=12,
            intelligence=10,
            wisdom=10,
            charisma=16,
        ),
        feature_refs=tuple(feature_refs),
        hp_progression=(8, 5, 5, 5, 5),
    )


def test_final_build_rechecks_feature_pool_dependencies_after_retraining() -> None:
    registry = load_default_content_registry()
    invalid = _warlock_build("tce:feature:far-scribe")

    issues = validate_final_feature_pool_dependencies(invalid, registry)

    assert {issue.code for issue in issues} == {
        "optional_pool_final_feature_prerequisite_not_met"
    }
    assert issues[0].related_refs == (
        "tce:feature:far-scribe",
        "srd5.1:feature:pact-of-the-tome",
    )

    valid = _warlock_build(
        "srd5.1:feature:pact-of-the-tome",
        "tce:feature:far-scribe",
    )
    assert validate_final_feature_pool_dependencies(valid, registry) == ()
