from __future__ import annotations

from dataclasses import dataclass

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild
from app.domain.character_builder.basics import resolve_creation_summary
from app.domain.character_builder.choices import build_foundation_choices
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderResolvedSummary,
    BuilderValidationResult,
)
from app.domain.character_builder.validation import make_validation_result, validate_foundation_draft


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
    choices = build_foundation_choices(draft, registry)
    issues = list(validate_foundation_draft(draft, registry, choices))

    # P1-B resolves creation basics but intentionally stops before class progression.
    # Keep a final guard in case a client injects level_choices early; P1-C replaces it.
    if not any(issue.severity is BuilderIssueSeverity.BLOCKING_ERROR for issue in issues):
        issues.append(
            BuilderIssue(
                code="build_compiler_not_complete",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="draft_payload.level_choices",
                message=(
                    "Character creation basics are valid, but class progression is completed in P1-C "
                    "before a CharacterBuild can be confirmed."
                ),
            )
        )

    return BuilderCompileResult(
        build_candidate=None,
        resolved_summary=resolve_creation_summary(draft, registry, choices),
        choices=choices,
        validation=make_validation_result(issues),
    )
