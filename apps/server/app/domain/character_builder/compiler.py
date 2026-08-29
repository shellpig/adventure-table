from __future__ import annotations

from dataclasses import dataclass

from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import (
    AbilityScores,
    CharacterBuild,
    RoleplayProfile,
    SpellResourcePool,
    SpellSlotCapacity,
    SpellcastingProfile,
)
from app.domain.character_builder.basics import resolve_creation_summary
from app.domain.character_builder.choices import build_foundation_choices
from app.domain.character_builder.multiclass import multiclass_option_failure_reason
from app.domain.character_builder.progression import (
    build_progression_choices,
    class_summary,
    compile_progression,
    progression_summary,
    validate_progression,
)
from app.domain.character_builder.schemas import (
    BuilderAbilityScoreSummary,
    BuilderChoice,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderResolvedSummary,
    BuilderValidationResult,
)
from app.domain.character_builder.spellcasting import compile_spellcasting
from app.domain.character_builder.structural import (
    StructuralCompilation,
    build_structural_choices,
    compile_structural_selections,
    validate_structural_choice_integrity,
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


def _resolved_abilities(summary: BuilderResolvedSummary) -> dict[str, int] | None:
    if not summary.ability_scores:
        return None
    return {entry.ability: entry.resolved for entry in summary.ability_scores}


def _apply_structural_ability_bonuses(
    summary: BuilderResolvedSummary,
    structural: StructuralCompilation,
    draft: BuilderDraft,
) -> BuilderResolvedSummary:
    if not summary.ability_scores or not structural.ability_bonuses:
        return summary
    override_map = {
        override.key.removeprefix("ability:"): int(override.value)
        for override in draft.draft_payload.numeric_overrides
        if override.key.startswith("ability:") and float(override.value).is_integer()
    }
    scores: list[BuilderAbilityScoreSummary] = []
    for entry in summary.ability_scores:
        bonus = structural.ability_bonuses.get(entry.ability, 0)
        resolved = entry.resolved + bonus
        scores.append(
            entry.model_copy(
                update={
                    "permanent_bonus": entry.permanent_bonus + bonus,
                    "resolved": resolved,
                    "effective": override_map.get(entry.ability, resolved),
                    "overridden": entry.ability in override_map,
                }
            )
        )
    return summary.model_copy(update={"ability_scores": tuple(scores)})


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


def _effective_progression_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
    effective_abilities: dict[str, int] | None,
) -> tuple[BuilderChoice, ...]:
    result: list[BuilderChoice] = []
    levels = draft.draft_payload.level_choices
    for choice in choices:
        if choice.option_source != "content:class":
            result.append(choice)
            continue
        parts = choice.choice_id.split(":")
        if len(parts) < 3 or parts[0] != "level" or not parts[1].isdigit():
            result.append(choice)
            continue
        character_level = int(parts[1])
        acquired: list[ContentEntry] = []
        seen: set[str] = set()
        for level_choice in levels[: max(0, character_level - 1)]:
            entry = registry.get_optional(level_choice.class_ref)
            if entry is None or not entry.key.startswith("srd5.1:class:") or entry.key in seen:
                continue
            seen.add(entry.key)
            acquired.append(entry)

        next_options = []
        for option in choice.options:
            candidate = registry.get_optional(option.reference_id or "")
            reason = None
            if candidate is not None and candidate.key.startswith("srd5.1:class:"):
                reason = multiclass_option_failure_reason(
                    candidate,
                    tuple(acquired),
                    effective_abilities,
                )
            next_options.append(option.model_copy(update={"disabled_reason": reason}))
        result.append(choice.model_copy(update={"options": tuple(next_options)}))
    return tuple(result)


def compile_builder_draft(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> BuilderCompileResult:
    raw_foundation_choices = tuple(
        choice
        for choice in build_foundation_choices(draft, registry)
        if choice.option_source != "content:class"
    )
    foundation_preview = resolve_creation_summary(draft, registry, raw_foundation_choices)

    structural_data_issue: BuilderIssue | None = None
    try:
        structural_choices = build_structural_choices(
            draft,
            registry,
            starting_abilities=_resolved_abilities(foundation_preview),
        )
    except ValueError as exc:
        structural_choices = ()
        structural_data_issue = BuilderIssue(
            code="structural_rules_data_error",
            severity=BuilderIssueSeverity.BLOCKING_ERROR,
            path="draft_payload.level_choices",
            message=str(exc),
        )

    progression_choices = _effective_progression_choices(
        draft,
        registry,
        build_progression_choices(draft, registry),
        _effective_abilities(foundation_preview),
    )
    live_choice_ids = {
        *(choice.choice_id for choice in progression_choices),
        *(choice.choice_id for choice in structural_choices),
    }
    foundation_choices = tuple(
        choice
        for choice in raw_foundation_choices
        if not (
            choice.option_source == "draft:selection"
            and choice.choice_id in live_choice_ids
        )
    )
    choices = foundation_choices + progression_choices + structural_choices

    # Class/subclass rows are authoritative in level_choices and are validated by
    # validate_progression(). Nested class and P1-D structural choices use the
    # canonical choice_selections contract.
    generic_progression_choices = tuple(
        choice
        for choice in progression_choices
        if choice.option_source == "content:class-proficiency"
    )
    validation_choices = foundation_choices + generic_progression_choices + structural_choices
    foundation_issues = [
        issue
        for issue in validate_foundation_draft(draft, registry, validation_choices)
        if issue.code != "incomplete_level_progression"
    ]
    if structural_data_issue is not None:
        foundation_issues.append(structural_data_issue)
    foundation_issues.extend(validate_structural_choice_integrity(draft, structural_choices))

    resolved_summary = resolve_creation_summary(draft, registry, choices)
    structural = compile_structural_selections(draft, registry, structural_choices)
    resolved_summary = _apply_structural_ability_bonuses(resolved_summary, structural, draft)

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

    automatic_features = tuple(
        dict.fromkeys(
            feature_ref
            for node in nodes
            for feature_ref in node.automatic_feature_refs
        )
    )
    spellcasting = compile_spellcasting(
        draft,
        registry,
        effective_abilities=_effective_abilities(resolved_summary),
        feature_refs=tuple(dict.fromkeys((*automatic_features, *structural.feature_refs))),
    )
    issues.extend(spellcasting.issues)
    resolved_summary = resolved_summary.model_copy(
        update={
            "spellcasting_profiles": spellcasting.profiles,
            "spell_resource_pools": spellcasting.resource_pools,
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
        build_profiles = tuple(
            SpellcastingProfile(
                profile_id=profile.profile_id,
                source_type=profile.source_type,
                source_key=profile.source_key,
                class_ref=profile.class_ref,
                ability=profile.ability,
                access_model=profile.access_model,
                resource_pool_type=profile.resource_pool_type,
                max_spell_level=profile.max_spell_level,
                prepared_limit=profile.prepared_limit,
            )
            for profile in spellcasting.profiles
        )
        build_pools = tuple(
            SpellResourcePool(
                pool_id=pool.pool_id,
                pool_type=pool.pool_type,
                source_profile_id=pool.source_profile_id,
                slots=tuple(
                    SpellSlotCapacity(level=slot.level, capacity=slot.count)
                    for slot in pool.slots
                ),
            )
            for pool in spellcasting.resource_pools
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
            proficiencies=tuple(dict.fromkeys((*compiled.proficiencies, *structural.proficiencies))),
            saving_throw_proficiencies=compiled.saving_throw_proficiencies,
            skill_choices=tuple(dict.fromkeys((*compiled.skill_choices, *structural.skill_choices))),
            feature_refs=tuple(dict.fromkeys((*compiled.feature_refs, *structural.feature_refs))),
            feat_refs=structural.feat_refs,
            spellcasting_profiles=build_profiles,
            spell_access_entries=spellcasting.spell_access_entries,
            spell_resource_pools=build_pools,
            hp_progression=compiled.hp_progression,
            roleplay_profile=_roleplay_profile(draft),
            numeric_overrides=payload.numeric_overrides,
        )

    # P1-E completes spell progression, but Confirm stays closed until P1-F
    # finishes equipment, final review and atomic character creation.
    if not has_blocking:
        issues.append(
            BuilderIssue(
                code="builder_phase_not_complete",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="draft_payload",
                message=(
                    "Spellcasting progression is valid. Starting equipment and final review must be "
                    "completed before Confirm is enabled."
                ),
            )
        )

    return BuilderCompileResult(
        build_candidate=build_candidate,
        resolved_summary=resolved_summary,
        choices=choices,
        validation=make_validation_result(issues),
    )
