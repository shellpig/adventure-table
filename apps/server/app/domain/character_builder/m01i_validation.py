from __future__ import annotations

from collections import Counter

from app.content.identity import parse_stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, SpellAccessEntry
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.optional_class_features import (
    OptionalFeatureRuntime,
    _choice_id,
    _pool_option_spec,
)
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
)


def _selection(draft: BuilderDraft, choice_id: str) -> tuple[str, ...]:
    record = draft.draft_payload.choice_selections.get(choice_id)
    return record.selected_option_ids if record is not None else ()


def active_retraining_choices(
    choices: tuple[BuilderChoice, ...],
    runtime: OptionalFeatureRuntime,
) -> tuple[BuilderChoice, ...]:
    """Expose retraining only when its Optional Class Feature is active.

    Retraining features such as Bardic Versatility are themselves optional
    class features. Merely meeting their level gate must not grant their
    retraining permission when the feature was never adopted into the Build.
    """

    active = set(runtime.active_feature_refs)
    return tuple(choice for choice in choices if choice.source_ref in active)


def _cantrip_replacements(
    draft: BuilderDraft,
    runtime: OptionalFeatureRuntime,
) -> tuple[tuple[str, str, str], ...]:
    """Return old/new cantrip pairs with the exact owning class identity."""

    result: list[tuple[str, str, str]] = []
    for feature_ref in sorted(runtime.specs):
        spec = runtime.specs[feature_ref]
        retraining = spec.retraining
        if feature_ref not in runtime.active_feature_refs or retraining is None:
            continue
        for strategy in retraining.strategies:
            if strategy.kind != "cantrip":
                continue
            action_id = _choice_id(
                draft,
                "retraining",
                feature_ref,
                strategy.id,
                "action",
            )
            replace_id = deterministic_choice_id(action_id, "replace")
            if _selection(draft, action_id) != (replace_id,):
                continue
            old_id = deterministic_choice_id(action_id, "from")
            new_id = deterministic_choice_id(action_id, "to")
            old = _selection(draft, old_id)
            new = _selection(draft, new_id)
            if len(old) != 1 or len(new) != 1 or old[0] == new[0]:
                continue
            result.append(
                (
                    old[0],
                    new[0],
                    strategy.class_ref or spec.parent_class_ref,
                )
            )
    return tuple(result)


def apply_cantrip_retraining_for_m01i(
    entries: tuple[SpellAccessEntry, ...],
    draft: BuilderDraft,
    runtime: OptionalFeatureRuntime,
) -> tuple[tuple[SpellAccessEntry, ...], tuple[BuilderIssue, ...]]:
    """Replace only the cantrip row owned by the retraining feature's class.

    A multiclass character can know the same cantrip from multiple classes.
    Matching only spell_key can mutate the wrong source profile, so both the
    class StableKey and spell StableKey are required here.
    """

    result = list(entries)
    issues: list[BuilderIssue] = []
    for old, new, class_ref in _cantrip_replacements(draft, runtime):
        replacement_index = next(
            (
                index
                for index, entry in enumerate(result)
                if entry.spell_key == old
                and entry.access_type == "known"
                and entry.source_type == "class"
                and entry.source_key == class_ref
            ),
            None,
        )
        if replacement_index is None:
            issues.append(
                BuilderIssue(
                    code="optional_feature_retraining_source_missing",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="build.spell_access_entries",
                    message=(
                        "The selected cantrip retraining no longer matches the "
                        "owning class spell source."
                    ),
                    message_params={
                        "class_ref": class_ref,
                        "old_spell_ref": old,
                        "new_spell_ref": new,
                    },
                    related_refs=(class_ref, old, new),
                )
            )
            continue

        new_spell = runtime.registry.get_optional(new)
        if new_spell is None or not stable_key_is_kind(new_spell.key, "spell"):
            issues.append(
                BuilderIssue(
                    code="optional_feature_retraining_spell_missing",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="build.spell_access_entries",
                    message="The selected replacement cantrip is no longer installed.",
                    related_refs=(new,),
                )
            )
            continue

        entry = result[replacement_index]
        result[replacement_index] = entry.model_copy(
            update={
                "entry_id": (
                    f"class:{parse_stable_key(class_ref).index}:known:"
                    f"{parse_stable_key(new).index}"
                ),
                "spell_key": new,
            }
        )

    return (
        tuple({entry.entry_id: entry for entry in result}.values()),
        tuple(issues),
    )


def validate_final_feature_pool_dependencies(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> tuple[BuilderIssue, ...]:
    """Re-check pool-option legality against the final compiled Build.

    This is intentionally post-retraining. In particular, changing Pact Boon
    must not leave a Talisman-only Invocation in the new immutable Build merely
    because the old Pact existed in the base version while choices were built.
    """

    known = set(build.feature_refs)
    class_levels = Counter(build.class_progression)
    issues: list[BuilderIssue] = []

    for feature_ref in build.feature_refs:
        entry = registry.get_optional(feature_ref)
        if entry is None:
            continue
        spec = _pool_option_spec(entry)
        if spec is None:
            continue

        if spec.eligible_class_refs:
            highest = max(
                (class_levels.get(class_ref, 0) for class_ref in spec.eligible_class_refs),
                default=0,
            )
            if highest < spec.minimum_class_level:
                issues.append(
                    BuilderIssue(
                        code="optional_pool_final_class_prerequisite_not_met",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path="build.feature_refs",
                        message="A selected feature-pool option is no longer legal for the final class progression.",
                        message_params={"option_ref": feature_ref},
                        related_refs=(feature_ref,),
                    )
                )
                continue

        missing = tuple(ref for ref in spec.required_feature_refs if ref not in known)
        if missing:
            issues.append(
                BuilderIssue(
                    code="optional_pool_final_feature_prerequisite_not_met",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="build.feature_refs",
                    message="A selected feature-pool option lost a required class feature.",
                    message_params={
                        "option_ref": feature_ref,
                        "required_feature_refs": list(missing),
                    },
                    related_refs=(feature_ref, *missing),
                )
            )
            continue

        if spec.any_required_feature_refs and not any(
            ref in known for ref in spec.any_required_feature_refs
        ):
            issues.append(
                BuilderIssue(
                    code="optional_pool_final_feature_prerequisite_not_met",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="build.feature_refs",
                    message="A selected feature-pool option lost its required class feature.",
                    message_params={
                        "option_ref": feature_ref,
                        "any_required_feature_refs": list(spec.any_required_feature_refs),
                    },
                    related_refs=(feature_ref, *spec.any_required_feature_refs),
                )
            )

    return tuple(issues)


def validate_feature_grant_source_references(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> tuple[BuilderIssue, ...]:
    """Ensure Build-persistent feature provenance never points at missing content."""

    issues: list[BuilderIssue] = []
    for row in build.feature_grant_sources:
        missing = tuple(
            ref
            for ref in (row.feature_ref, row.source_ref)
            if registry.get_optional(ref) is None
        )
        if not missing:
            continue
        issues.append(
            BuilderIssue(
                code="feature_grant_provenance_reference_missing",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="build.feature_grant_sources",
                message="Feature grant provenance references content that is not installed.",
                message_params={
                    "feature_ref": row.feature_ref,
                    "source_ref": row.source_ref,
                },
                related_refs=missing,
            )
        )
    return tuple(issues)
