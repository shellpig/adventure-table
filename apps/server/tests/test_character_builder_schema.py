from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.content import load_default_content_registry
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.compiler import compile_builder_draft
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderDraft,
    BuilderDraftCreateInput,
    BuilderDraftPayload,
    BuilderIssueSeverity,
    BuilderMode,
    BuilderReferenceSelection,
)


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


def _scores() -> dict[str, int]:
    return {
        "strength": 15,
        "dexterity": 14,
        "constitution": 13,
        "intelligence": 12,
        "wisdom": 10,
        "charisma": 8,
    }


def test_partial_create_draft_schema_is_strict_but_incomplete_is_allowed() -> None:
    payload = BuilderDraftPayload(
        basic=BuilderBasicInput(name="Partial Hero"),
        target_level=3,
    )
    assert payload.race_selection is None
    assert payload.level_choices == ()

    with pytest.raises(ValidationError):
        BuilderDraftPayload.model_validate(
            {"basic": {"name": "Bad extra", "unexpected": True}, "target_level": 1}
        )

    with pytest.raises(ValidationError):
        BuilderDraftPayload.model_validate({"target_level": 21})

    with pytest.raises(ValidationError):
        BuilderDraftPayload.model_validate(
            {"ability_generation": {"method": "manual", "scores": {"strength": 10}}}
        )

    with pytest.raises(ValidationError):
        BuilderDraftCreateInput(mode=BuilderMode.CREATE, character_id=uuid4())

    with pytest.raises(ValidationError):
        BuilderDraftCreateInput(
            mode=BuilderMode.LEVEL_UP,
            character_id=uuid4(),
            base_version_id=None,
        )


def test_foundation_validation_is_machine_readable_and_supports_all_severities() -> None:
    registry = load_default_content_registry()
    payload = BuilderDraftPayload(
        basic=BuilderBasicInput(name=" Ada "),
        target_level=1,
        race_selection=BuilderReferenceSelection(reference_id="srd5.1:race:human"),
        background_selection=BuilderReferenceSelection(reference_id="srd5.1:background:acolyte"),
        ability_generation={"method": "manual", "scores": _scores()},
        level_choices=(
            {
                "character_level": 1,
                "class_ref": "srd5.1:class:fighter",
                "hp_method": "first_level",
                "hp_base_gain": 10,
            },
        ),
        numeric_overrides=({"key": "armor_class", "value": 17},),
    )
    result = compile_builder_draft(_draft(payload), registry)
    issues = result.validation.issues

    assert any(
        issue.severity is BuilderIssueSeverity.WARNING
        and issue.code == "name_whitespace_will_be_trimmed"
        and issue.path == "draft_payload.basic.name"
        for issue in issues
    )
    assert any(
        issue.severity is BuilderIssueSeverity.NON_STANDARD
        and issue.code == "numeric_override"
        and issue.path == "draft_payload.numeric_overrides.0"
        for issue in issues
    )
    assert any(issue.severity is BuilderIssueSeverity.BLOCKING_ERROR for issue in issues)
    assert result.validation.can_confirm is False
    assert result.validation.non_standard_count == 1


def test_incomplete_validation_and_choice_ids_are_stable_across_unrelated_edits() -> None:
    registry = load_default_content_registry()
    original = _draft(
        BuilderDraftPayload(basic=BuilderBasicInput(name="One"), target_level=2)
    )
    renamed = original.model_copy(
        update={
            "draft_payload": original.draft_payload.model_copy(
                update={"basic": BuilderBasicInput(name="Two")}
            )
        }
    )

    first = compile_builder_draft(original, registry)
    second = compile_builder_draft(original, registry)
    renamed_result = compile_builder_draft(renamed, registry)

    first_ids = [choice.choice_id for choice in first.choices]
    assert first_ids == [choice.choice_id for choice in second.choices]
    assert first_ids == [choice.choice_id for choice in renamed_result.choices]
    assert deterministic_choice_id("level", "1", "class-selection") in first_ids

    codes = {issue.code for issue in first.validation.issues}
    assert {
        "missing_race",
        "missing_background",
        "missing_ability_generation",
        "incomplete_level_progression",
    }.issubset(codes)
    assert first.validation.can_confirm is False
