from __future__ import annotations

from collections import Counter

from app.content.registry import ContentRegistry
from app.domain.character_builder.schemas import (
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderReferenceSelection,
    BuilderValidationResult,
)


def make_validation_result(
    issues: tuple[BuilderIssue, ...] | list[BuilderIssue],
) -> BuilderValidationResult:
    normalized = tuple(issues)
    blocking = any(
        issue.severity is BuilderIssueSeverity.BLOCKING_ERROR
        for issue in normalized
    )
    non_standard_count = sum(
        issue.severity is BuilderIssueSeverity.NON_STANDARD
        for issue in normalized
    )
    return BuilderValidationResult(
        issues=normalized,
        can_confirm=not blocking,
        non_standard_count=non_standard_count,
    )


def _missing(code: str, path: str, message: str) -> BuilderIssue:
    return BuilderIssue(
        code=code,
        severity=BuilderIssueSeverity.BLOCKING_ERROR,
        path=path,
        message=message,
    )


def _validate_reference(
    registry: ContentRegistry,
    *,
    selection: BuilderReferenceSelection,
    expected_kind: str,
    path: str,
) -> BuilderIssue | None:
    entry = registry.get_optional(selection.reference_id)
    if entry is None:
        return BuilderIssue(
            code="unknown_reference",
            severity=BuilderIssueSeverity.BLOCKING_ERROR,
            path=path,
            message=f"Unknown {expected_kind} reference: {selection.reference_id}",
            related_refs=(selection.reference_id,),
        )
    kind = entry.key.split(":", 2)[1] if ":" in entry.key else ""
    if kind != expected_kind:
        return BuilderIssue(
            code="wrong_reference_kind",
            severity=BuilderIssueSeverity.BLOCKING_ERROR,
            path=path,
            message=(
                f"Expected a {expected_kind} reference, got {selection.reference_id}"
            ),
            related_refs=(selection.reference_id,),
        )
    return None


def validate_foundation_draft(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[BuilderIssue, ...]:
    payload = draft.draft_payload
    issues: list[BuilderIssue] = []

    if payload.basic is None or payload.basic.name is None or not payload.basic.name.strip():
        issues.append(
            _missing(
                "missing_character_name",
                "draft_payload.basic.name",
                "Character name is required before Confirm.",
            )
        )
    elif payload.basic.name != payload.basic.name.strip():
        issues.append(
            BuilderIssue(
                code="name_whitespace_will_be_trimmed",
                severity=BuilderIssueSeverity.WARNING,
                path="draft_payload.basic.name",
                message="Leading or trailing whitespace in the character name will be trimmed.",
            )
        )

    if payload.target_level is None:
        issues.append(
            _missing(
                "missing_target_level",
                "draft_payload.target_level",
                "Target character level is required before Confirm.",
            )
        )

    if payload.race_selection is None:
        issues.append(
            _missing(
                "missing_race",
                "draft_payload.race_selection",
                "Race selection is required before Confirm.",
            )
        )
    else:
        issue = _validate_reference(
            registry,
            selection=payload.race_selection,
            expected_kind="race",
            path="draft_payload.race_selection.reference_id",
        )
        if issue is not None:
            issues.append(issue)

    if payload.background_selection is None:
        issues.append(
            _missing(
                "missing_background",
                "draft_payload.background_selection",
                "Background selection is required before Confirm.",
            )
        )
    else:
        issue = _validate_reference(
            registry,
            selection=payload.background_selection,
            expected_kind="background",
            path="draft_payload.background_selection.reference_id",
        )
        if issue is not None:
            issues.append(issue)

    if not payload.ability_generation:
        issues.append(
            _missing(
                "missing_ability_generation",
                "draft_payload.ability_generation",
                "Ability generation input is required before Confirm.",
            )
        )

    if payload.target_level is not None:
        if len(payload.level_choices) != payload.target_level:
            issues.append(
                BuilderIssue(
                    code="incomplete_level_progression",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="draft_payload.level_choices",
                    message=(
                        "Level choices must contain one ordered entry per target level "
                        f"(expected {payload.target_level}, got {len(payload.level_choices)})."
                    ),
                )
            )

    override_keys = [override.key for override in payload.numeric_overrides]
    duplicates = sorted(
        key for key, count in Counter(override_keys).items() if count > 1
    )
    if duplicates:
        issues.append(
            BuilderIssue(
                code="duplicate_numeric_override",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="draft_payload.numeric_overrides",
                message="Numeric override keys must be unique.",
            )
        )

    for index, override in enumerate(payload.numeric_overrides):
        issues.append(
            BuilderIssue(
                code="numeric_override",
                severity=BuilderIssueSeverity.NON_STANDARD,
                path=f"draft_payload.numeric_overrides.{index}",
                message=(
                    f"Numeric override {override.key} intentionally replaces a calculated value."
                ),
            )
        )

    return tuple(issues)
