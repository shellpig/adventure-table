from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character.schemas import AbilityScores, CharacterBuild
from app.domain.character_builder.m01i_runtime import prepare_optional_class_features_for_m01i
from app.domain.character_builder.m01i_validation import active_retraining_choices
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


FIGHTER = "srd5.1:class:fighter"
ARCHERY = "srd5.1:feature:fighter-fighting-style-archery"
MARTIAL_VERSATILITY = "tce:feature:fighter-martial-versatility"


def _level(character_level: int) -> BuilderLevelChoice:
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=FIGHTER,
        hp_method=(
            BuilderHPMethod.FIRST_LEVEL
            if character_level == 1
            else BuilderHPMethod.FIXED_AVERAGE
        ),
        hp_base_gain=10 if character_level == 1 else 6,
    )


def _draft(selections: dict[str, BuilderChoiceSelection] | None = None) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.LEVEL_UP,
        character_id=uuid4(),
        base_version_id=uuid4(),
        revision=1,
        draft_payload=BuilderDraftPayload(
            target_level=4,
            level_choices=tuple(_level(level) for level in range(1, 5)),
            choice_selections=selections or {},
        ),
        created_at=now,
        updated_at=now,
    )


def _base_build() -> CharacterBuild:
    return CharacterBuild(
        content_sources=("srd5.1",),
        race_ref="srd5.1:race:human",
        character_level=3,
        class_progression=(FIGHTER,) * 3,
        ability_scores=AbilityScores(
            strength=16,
            dexterity=14,
            constitution=13,
            intelligence=12,
            wisdom=10,
            charisma=8,
        ),
        feature_refs=(ARCHERY,),
        hp_progression=(10, 6, 6),
    )


def test_martial_versatility_can_retrain_legacy_srd_fighting_style_reference() -> None:
    registry = load_default_content_registry()
    base = _base_build()
    initial = _draft()
    feature_choice_id = _choice_id(
        initial,
        "optional-feature",
        MARTIAL_VERSATILITY,
    )
    draft = _draft(
        {
            feature_choice_id: BuilderChoiceSelection(
                choice_id=feature_choice_id,
                source_ref=MARTIAL_VERSATILITY,
                selected_option_ids=(MARTIAL_VERSATILITY,),
            )
        }
    )

    runtime = prepare_optional_class_features_for_m01i(
        draft,
        registry,
        base_build=base,
    )
    choices = active_retraining_choices(
        build_optional_retraining_choices(draft, runtime, base_build=base),
        runtime,
    )

    from_choice = next(
        choice
        for choice in choices
        if choice.source_ref == MARTIAL_VERSATILITY
        and choice.option_source
        == "content:optional-feature:retraining-from:feature_pool"
    )
    assert [option.reference_id for option in from_choice.options] == [ARCHERY]
