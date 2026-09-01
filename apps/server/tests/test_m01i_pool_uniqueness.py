from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character_builder.m01i_validation import validate_unique_feature_pool_selections
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderMode,
    BuilderOptionKind,
)


BLIND_FIGHTING = "tce:feature:blind-fighting"


def _choice(choice_id: str, option_source: str) -> BuilderChoice:
    return BuilderChoice(
        choice_id=choice_id,
        label=choice_id,
        source_ref="srd5.1:feature:fighting-style",
        required=True,
        choose_count=1,
        option_source=option_source,
        options=(
            BuilderChoiceOption(
                option_id=BLIND_FIGHTING,
                label="Blind Fighting",
                kind=BuilderOptionKind.REFERENCE,
                reference_id=BLIND_FIGHTING,
            ),
        ),
        selected_option_ids=(BLIND_FIGHTING,),
    )


def _draft(*choice_ids: str) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=BuilderDraftPayload(
            choice_selections={
                choice_id: BuilderChoiceSelection(
                    choice_id=choice_id,
                    selected_option_ids=(BLIND_FIGHTING,),
                )
                for choice_id in choice_ids
            }
        ),
        created_at=now,
        updated_at=now,
    )


def test_same_fighting_style_cannot_fill_two_acquisition_slots() -> None:
    registry = load_default_content_registry()
    first = _choice("fighter:fighting-style", "content:feature:fighting-style")
    second = _choice("champion:additional-style", "content:feature:additional-fighting-style")

    issues = validate_unique_feature_pool_selections(
        _draft(first.choice_id, second.choice_id),
        (first, second),
        registry,
    )

    assert len(issues) == 1
    assert issues[0].code == "duplicate_optional_pool_selection"
    assert issues[0].related_refs == (BLIND_FIGHTING,)


def test_retraining_from_control_does_not_count_as_a_second_acquisition() -> None:
    registry = load_default_content_registry()
    original = _choice("fighter:fighting-style", "content:feature:fighting-style")
    from_control = _choice(
        "level:4:m01-i:retraining:from",
        "content:optional-feature:retraining-from:feature_pool",
    )

    issues = validate_unique_feature_pool_selections(
        _draft(original.choice_id, from_control.choice_id),
        (original, from_control),
        registry,
    )

    assert issues == ()
