from __future__ import annotations

from dataclasses import dataclass

from app.content.registry import ContentRegistry
from app.domain.character.schemas import AbilityScores, CharacterBuild, RoleplayProfile
from app.domain.character_builder.basics import resolve_creation_summary
from app.domain.character_builder.choices import build_foundation_choices
from app.domain.character_builder.progression import (
    build_progression_choices,
    class_summary,
    compile_progression,
    progression_summary,
    validate_progression,
)
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


def _effective_abilities(summary: BuilderResolvedSummary) -> dict[str, int] | None:
    if not summary.ability_scores:
        return None
    return {entry.ability: entry.effective for entry in summary.ability_scores}


def _build_ability_scores(summary: BuilderResolvedSummary) -> AbilityScores | None:
    if len(summary.ability_scores) != 6:
        return None
    scores = {entry.ability: entry.resolved for entry in summary.ability_scores}
    try:
        return AbilityScores.model_validate(scores)
    except ValueError:
        return None


def _roleplay_profile(draft: BuilderDraft) -> RoleplayProfile:
    raw = draft.draft_payload.roleplay_profile
    allowed = {
        key: raw[key]
        for key in (
            "appearance",
            "biography",
            "personality_traits",
            "ideals",
            "bonds",
            "flaws",
        )
        if key in raw
    }
    return RoleplayProfile.model_validate(allowed)


def compile_builder_draft(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> BuilderCompileResult:
    foundation_choices = tuple(
        choice
        for choice in build_foundation_choices(draft, registry)
        if choice.option_source != "content:class"
    )
    progression_choices = build_progression_choices(draft, registry)
    choices = foundation_choices + progression_choices

    # Class/subclass rows are authoritative in level_choices and are validated by
    # validate_progression(). Only the nested proficiency choices still use the
    # generic choice_selections contract.
    generic_progression_choices = tuple(
        choice
        for choice in progression_choices
        if choice.option_source == "content:class-proficiency"
    )
    validation_choices = foundation_choices + generic_progression_choices
    foundation_issues = [
        issue
        for issue in validate_foundation_draft(draft, registry, validation_choices)
        if issue.code != "incomplete_level_progression"
    ]
    resolved_summary = resolve_creation_summary(draft, registry, choices)
    progression_issues = list(
        validate_progression(
            draft,
            registry,
            effective_abilities=_effective_abilities(resolved_summary),
        )
    )
    issues = foundation_issues + progression_issues

    nodes = progression_summary(draft, registry)
    resolved_summary = resolved_summary.model_copy(
        update={
            "starting_class_name": nodes[0].class_name if nodes else None,
            "class_summary": class_summary(nodes),
            "progression": nodes,
        }
    )

    build_candidate: CharacterBuild | None = None
    has_blocking = any(issue.severity is BuilderIssueSeverity.BLOCKING_ERROR for issue in issues)
    abilities = _build_ability_scores(resolved_summary)
    payload = draft.draft_payload
    if (
        not has_blocking
        and abilities is not None
        and payload.basic is not None
        and payload.race_selection is not None
        and payload.background_selection is not None
        and payload.target_level is not None
    ):
        compiled = compile_progression(
            draft,
            registry,
            grants=resolved_summary.grants,
            choices=choices,
        )
        build_candidate = CharacterBuild(
            ruleset=payload.basic.ruleset,
            race_ref=payload.race_selection.reference_id,
            subrace_ref=(
                payload.subrace_selection.reference_id if payload.subrace_selection is not None else None
            ),
            background_ref=payload.background_selection.reference_id,
            alignment_ref=(
                payload.alignment_selection.reference_id
                if payload.alignment_selection is not None
                else None
            ),
            character_level=payload.target_level,
            class_progression=compiled.class_progression,
            subclasses=compiled.subclasses,
            ability_scores=abilities,
            proficiencies=compiled.proficiencies,
            saving_throw_proficiencies=compiled.saving_throw_proficiencies,
            skill_choices=compiled.skill_choices,
            feature_refs=compiled.feature_refs,
            hp_progression=compiled.hp_progression,
            roleplay_profile=_roleplay_profile(draft),
            numeric_overrides=payload.numeric_overrides,
        )

    # P1-C intentionally produces a P0-compatible Build candidate for progression
    # tests, but Confirm stays closed until ASI/feat, spellcasting, equipment and
    # review are completed by P1-D through P1-F.
    if not has_blocking:
        issues.append(
            BuilderIssue(
                code="builder_phase_not_complete",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="draft_payload",
                message=(
                    "Class progression is valid. ASI/Feat, spellcasting, equipment and final review "
                    "must be completed before Confirm is enabled."
                ),
            )
        )

    return BuilderCompileResult(
        build_candidate=build_candidate,
        resolved_summary=resolved_summary,
        choices=choices,
        validation=make_validation_result(issues),
    )
