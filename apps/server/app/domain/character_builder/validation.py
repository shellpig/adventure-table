from __future__ import annotations

from collections import Counter

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.registry import ContentRegistry
from app.domain.character_builder.rules import load_ability_generation_rules
from app.domain.character_builder.schemas import (
    AbilityGenerationMethod,
    BuilderChoice,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderReferenceSelection,
    BuilderValidationResult,
)


# Bard/Rogue Expertise and the subclass features that reuse its shape select a
# proficiency the character already holds rather than granting a new one.
EXPERTISE_OPTION_SOURCE = "content:feature:feature-specific-expertise_options"


def make_validation_result(
    issues: tuple[BuilderIssue, ...] | list[BuilderIssue],
) -> BuilderValidationResult:
    normalized = tuple(issues)
    blocking = any(issue.severity is BuilderIssueSeverity.BLOCKING_ERROR for issue in normalized)
    non_standard_count = sum(issue.severity is BuilderIssueSeverity.NON_STANDARD for issue in normalized)
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
    try:
        kind = parse_stable_key(entry.key).kind
    except ValueError:
        kind = ""
    if kind != expected_kind:
        return BuilderIssue(
            code="wrong_reference_kind",
            severity=BuilderIssueSeverity.BLOCKING_ERROR,
            path=path,
            message=f"Expected a {expected_kind} reference, got {selection.reference_id}",
            related_refs=(selection.reference_id,),
        )
    return None


def _validate_ability_generation(draft: BuilderDraft) -> list[BuilderIssue]:
    generation = draft.draft_payload.ability_generation
    if generation is None:
        return [
            _missing(
                "missing_ability_generation",
                "draft_payload.ability_generation",
                "Ability generation input is required before Confirm.",
            )
        ]

    rules = load_ability_generation_rules()
    scores = generation.scores.as_dict()
    issues: list[BuilderIssue] = []
    if generation.method is AbilityGenerationMethod.STANDARD_ARRAY:
        if sorted(scores.values()) != sorted(rules.standard_array):
            issues.append(
                BuilderIssue(
                    code="invalid_standard_array_assignment",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="draft_payload.ability_generation.scores",
                    message="Standard Array must assign every configured array value exactly once.",
                )
            )
    elif generation.method is AbilityGenerationMethod.POINT_BUY:
        illegal = {ability: value for ability, value in scores.items() if value not in rules.point_buy_costs}
        if illegal:
            issues.append(
                BuilderIssue(
                    code="point_buy_score_out_of_range",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="draft_payload.ability_generation.scores",
                    message="Point Buy scores must stay within the configured legal score range.",
                )
            )
        else:
            spent = sum(rules.point_buy_costs[value] for value in scores.values())
            if spent > rules.point_buy_budget:
                issues.append(
                    BuilderIssue(
                        code="point_buy_budget_exceeded",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path="draft_payload.ability_generation.scores",
                        message=f"Point Buy spends {spent} points; budget is {rules.point_buy_budget}.",
                    )
                )
    elif generation.method is AbilityGenerationMethod.MANUAL:
        non_standard = [
            ability
            for ability, value in scores.items()
            if value < rules.manual_standard_min or value > rules.manual_standard_max
        ]
        if non_standard:
            issues.append(
                BuilderIssue(
                    code="manual_ability_outside_standard_generation",
                    severity=BuilderIssueSeverity.NON_STANDARD,
                    path="draft_payload.ability_generation.scores",
                    message=(
                        "Manual ability input contains values outside the normal physical-roll result range; "
                        "the values are preserved and explicitly marked non-standard."
                    ),
                )
            )
    return issues


def _validate_builder_choices(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
) -> list[BuilderIssue]:
    issues: list[BuilderIssue] = []
    direct_sources = {
        "content:race",
        "content:background",
        "content:alignment",
        "content:subrace",
        "builder:ability-generation",
    }
    selected_reference_ids: list[tuple[str, str]] = []

    for choice in choices:
        if choice.disabled_reason is not None or choice.option_source in direct_sources:
            continue
        selection = draft.draft_payload.choice_selections.get(choice.choice_id)
        selected = selection.selected_option_ids if selection is not None else ()
        path = f"draft_payload.choice_selections.{choice.choice_id}"
        if choice.required and len(selected) != choice.choose_count:
            issues.append(
                BuilderIssue(
                    code="invalid_choice_count",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=path,
                    message=f"{choice.label} requires exactly {choice.choose_count} selection(s).",
                    related_refs=((choice.source_ref,) if choice.source_ref else ()),
                )
            )
            continue
        option_by_id = {option.option_id: option for option in choice.options}
        illegal = tuple(option_id for option_id in selected if option_id not in option_by_id)
        if illegal:
            issues.append(
                BuilderIssue(
                    code="invalid_choice_option",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=path,
                    message=f"{choice.label} contains an option that is not currently eligible.",
                    related_refs=illegal,
                )
            )
            continue

        disabled = tuple(
            option_id
            for option_id in selected
            if option_by_id[option_id].disabled_reason is not None
        )
        if disabled:
            issues.append(
                BuilderIssue(
                    code="disabled_choice_option",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=path,
                    message=f"{choice.label} contains an option whose requirements are not met.",
                    related_refs=disabled,
                )
            )
            continue

        # Expertise does not grant a proficiency, it doubles one the character
        # already has, so its selections intentionally repeat an earlier choice.
        # Every other choice that hands out a reference must still be unique.
        grants_reference = not (choice.option_source or "").startswith(
            EXPERTISE_OPTION_SOURCE
        )
        for option_id in selected:
            option = option_by_id[option_id]
            if (
                grants_reference
                and option.reference_id is not None
                and option.category != "ability_bonus"
            ):
                selected_reference_ids.append((option.reference_id, path))

    duplicate_refs = {
        ref
        for ref, count in Counter(ref for ref, _ in selected_reference_ids).items()
        if count > 1
    }
    for duplicate in sorted(duplicate_refs):
        issues.append(
            BuilderIssue(
                code="duplicate_starting_choice",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="draft_payload.choice_selections",
                message=f"The same starting reference was selected more than once: {duplicate}",
                related_refs=(duplicate,),
            )
        )
    return issues


def validate_foundation_draft(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
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

    race_entry = None
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
        else:
            race_entry = registry.get(payload.race_selection.reference_id)
            subraces = race_entry.data.get("subraces")
            if isinstance(subraces, list) and subraces and payload.subrace_selection is None:
                issues.append(
                    _missing(
                        "missing_subrace",
                        "draft_payload.subrace_selection",
                        "The selected race requires a subrace selection.",
                    )
                )

    if payload.subrace_selection is not None:
        issue = _validate_reference(
            registry,
            selection=payload.subrace_selection,
            expected_kind="subrace",
            path="draft_payload.subrace_selection.reference_id",
        )
        if issue is not None:
            issues.append(issue)
        elif payload.race_selection is None:
            issues.append(
                BuilderIssue(
                    code="subrace_requires_race",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="draft_payload.subrace_selection",
                    message="A subrace cannot be selected before its parent race.",
                )
            )
        else:
            subrace = registry.get(payload.subrace_selection.reference_id)
            parent = subrace.data.get("race")
            try:
                expected_parent = (
                    reference_to_stable_key(parent, kinds={"race"})
                    if isinstance(parent, dict)
                    else None
                )
            except ValueError:
                expected_parent = None
            if expected_parent != payload.race_selection.reference_id:
                issues.append(
                    BuilderIssue(
                        code="subrace_race_mismatch",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path="draft_payload.subrace_selection.reference_id",
                        message="Selected subrace does not belong to the selected race.",
                        related_refs=(
                            payload.race_selection.reference_id,
                            payload.subrace_selection.reference_id,
                        ),
                    )
                )

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

    if payload.alignment_selection is not None:
        issue = _validate_reference(
            registry,
            selection=payload.alignment_selection,
            expected_kind="alignment",
            path="draft_payload.alignment_selection.reference_id",
        )
        if issue is not None:
            issues.append(issue)

    issues.extend(_validate_ability_generation(draft))
    issues.extend(_validate_builder_choices(draft, choices))

    if payload.target_level is not None and len(payload.level_choices) != payload.target_level:
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
    duplicates = sorted(key for key, count in Counter(override_keys).items() if count > 1)
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
                message=f"Numeric override {override.key} intentionally replaces a calculated value.",
            )
        )

    return tuple(issues)
