from __future__ import annotations

from dataclasses import dataclass

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild
from app.domain.character_builder.choices import build_foundation_choices
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderResolvedSummary,
    BuilderValidationResult,
)
from app.domain.character_builder.validation import (
    make_validation_result,
    validate_foundation_draft,
)


@dataclass(frozen=True)
class BuilderCompileResult:
    build_candidate: CharacterBuild | None
    resolved_summary: BuilderResolvedSummary
    choices: tuple[BuilderChoice, ...]
    validation: BuilderValidationResult


def compile_builder_draft(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> BuilderCompileResult:
    issues = list(validate_foundation_draft(draft, registry))

    # P1-A only establishes the domain pipeline. Later P1 subphases replace this
    # final blocker as their real resolvers compile a full CharacterBuild.
    if not any(
        issue.severity is BuilderIssueSeverity.BLOCKING_ERROR for issue in issues
    ):
        issues.append(
            BuilderIssue(
                code="build_compiler_not_complete",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="draft_payload",
                message=(
                    "The Builder domain pipeline is active, but full CharacterBuild "
                    "compilation is completed by later P1 subphases."
                ),
            )
        )

    payload = draft.draft_payload
    selected_reference_count = sum(
        selection is not None
        for selection in (payload.race_selection, payload.background_selection)
    )
    summary = BuilderResolvedSummary(
        name=payload.basic.name if payload.basic is not None else None,
        target_level=payload.target_level,
        selected_reference_count=selected_reference_count,
        choice_selection_count=len(payload.choice_selections),
    )

    return BuilderCompileResult(
        build_candidate=None,
        resolved_summary=summary,
        choices=build_foundation_choices(draft),
        validation=make_validation_result(issues),
    )
