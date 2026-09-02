from __future__ import annotations

from app.content.identity import stable_key_is_kind
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, FeatureGrantSource, SpellAccessEntry
from app.domain.character_builder.optional_class_features import (
    OptionalFeatureRuntime,
    _pool_option_spec,
    _strategy_replacements,
    build_optional_nested_choices,
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


def prevent_duplicate_retraining_targets(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
) -> tuple[BuilderChoice, ...]:
    """Do not let a replacement choose another option the Build already has."""

    by_id = {choice.choice_id: choice for choice in choices}
    result: list[BuilderChoice] = []
    for choice in choices:
        if not choice.option_source.startswith("content:optional-feature:retraining-to:"):
            result.append(choice)
            continue
        if not choice.choice_id.endswith(":to"):
            result.append(choice)
            continue

        parent_id = choice.choice_id.removesuffix(":to")
        old_id = f"{parent_id}:from"
        old_choice = by_id.get(old_id)
        if old_choice is None:
            result.append(choice)
            continue

        selected_old = set(_selection(draft, old_id))
        already_owned = {
            option.reference_id
            for option in old_choice.options
            if option.reference_id is not None
        } - selected_old
        if not already_owned:
            result.append(choice)
            continue

        options = []
        for option in choice.options:
            if option.reference_id not in already_owned or option.disabled_reason is not None:
                options.append(option)
                continue
            options.append(
                option.model_copy(
                    update={
                        "disabled_reason": "This option is already known or selected.",
                        "disabled_reason_code": "retraining_duplicate_target",
                    }
                )
            )
        result.append(choice.model_copy(update={"options": tuple(options)}))
    return tuple(result)


def build_retraining_nested_choices(
    draft: BuilderDraft,
    runtime: OptionalFeatureRuntime,
    retraining_choices: tuple[BuilderChoice, ...],
    *,
    base_build: CharacterBuild | None,
) -> tuple[BuilderChoice, ...]:
    """Reuse the normal nested-choice resolver for a retrained feature-pool option."""

    parents = tuple(
        choice
        for choice in retraining_choices
        if choice.option_source == "content:optional-feature:retraining-to:feature_pool"
        and choice.disabled_reason is None
    )
    return build_optional_nested_choices(
        draft,
        runtime.registry,
        parents,
        base_build=base_build,
    )


def _choice_sources(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
    *,
    grant_kind: str,
) -> tuple[FeatureGrantSource, ...]:
    result: list[FeatureGrantSource] = []
    for choice in choices:
        if choice.source_ref is None or choice.disabled_reason is not None:
            continue
        option_map = {option.option_id: option for option in choice.options}
        for option_id in _selection(draft, choice.choice_id):
            option = option_map.get(option_id)
            reference_id = option.reference_id if option is not None else None
            if reference_id is None:
                continue
            try:
                is_feature = stable_key_is_kind(reference_id, "feature")
            except ValueError:
                is_feature = False
            if not is_feature:
                continue
            result.append(
                FeatureGrantSource(
                    feature_ref=reference_id,
                    source_ref=choice.source_ref,
                    grant_kind=grant_kind,
                )
            )
    return tuple(result)


def current_feature_grant_sources(
    draft: BuilderDraft,
    runtime: OptionalFeatureRuntime,
    *,
    core_choices: tuple[BuilderChoice, ...],
    nested_choices: tuple[BuilderChoice, ...],
    retraining_choices: tuple[BuilderChoice, ...],
) -> tuple[FeatureGrantSource, ...]:
    """Derive provenance for choices compiled in the current draft."""

    result: list[FeatureGrantSource] = []
    result.extend(_choice_sources(draft, core_choices, grant_kind="choice"))
    result.extend(_choice_sources(draft, nested_choices, grant_kind="nested_choice"))
    result.extend(
        _choice_sources(
            draft,
            tuple(
                choice
                for choice in retraining_choices
                if choice.option_source == "content:optional-feature:retraining-to:feature_pool"
            ),
            grant_kind="retraining",
        )
    )
    for feature_ref in runtime.active_feature_refs:
        spec = runtime.specs[feature_ref]
        if spec.mode == "expanded_choice":
            continue
        result.append(
            FeatureGrantSource(
                feature_ref=feature_ref,
                source_ref=spec.parent_class_ref,
                grant_kind="optional_feature",
            )
        )
    return tuple(result)


def reconcile_feature_pool_retraining(
    feature_refs: tuple[str, ...],
    spell_entries: tuple[SpellAccessEntry, ...],
    sources: tuple[FeatureGrantSource, ...],
    draft: BuilderDraft,
    retraining_choices: tuple[BuilderChoice, ...],
    registry: ContentRegistry,
) -> tuple[
    tuple[str, ...],
    tuple[SpellAccessEntry, ...],
    tuple[FeatureGrantSource, ...],
    tuple[BuilderIssue, ...],
]:
    """Remove dependencies owned by a replaced feature and move its provenance.

    Feature-sourced spells already carry source_key provenance. Nested feature
    grants (notably Superior Technique maneuvers) use FeatureGrantSource so a
    style replacement removes exactly the grant owned by that style rather than
    guessing from the entire maneuver pool.
    """

    refs = list(dict.fromkeys(feature_refs))
    spells = list(spell_entries)
    provenance = list(sources)
    issues: list[BuilderIssue] = []

    for old_ref, new_ref in _strategy_replacements(draft, retraining_choices, "feature_pool"):
        old_entry = registry.get_optional(old_ref)
        old_spec = _pool_option_spec(old_entry) if old_entry is not None else None
        nested = old_spec.nested if old_spec is not None else None

        if nested is not None and nested.kind == "cantrip":
            spells = [
                entry
                for entry in spells
                if not (
                    entry.source_type == "feature"
                    and entry.source_key == old_ref
                )
            ]

        if nested is not None and nested.kind == "feature_pool":
            owned = {
                row.feature_ref
                for row in provenance
                if row.source_ref == old_ref and row.grant_kind == "nested_choice"
            }
            if not owned:
                issues.append(
                    BuilderIssue(
                        code="optional_feature_retraining_provenance_missing",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path="build.feature_grant_sources",
                        message=(
                            f"{old_ref} has nested feature grants but their Build provenance is missing; "
                            "the retraining cannot safely decide which grant to remove."
                        ),
                        related_refs=(old_ref,),
                    )
                )
            refs = [ref for ref in refs if ref not in owned]
            provenance = [
                row
                for row in provenance
                if not (
                    row.source_ref == old_ref
                    and row.grant_kind == "nested_choice"
                )
            ]

        next_provenance: list[FeatureGrantSource] = []
        for row in provenance:
            if row.feature_ref == old_ref:
                next_provenance.append(row.model_copy(update={"feature_ref": new_ref}))
            else:
                next_provenance.append(row)
        provenance = next_provenance

    return (
        tuple(dict.fromkeys(refs)),
        tuple({entry.entry_id: entry for entry in spells}.values()),
        tuple(provenance),
        tuple(issues),
    )


def finalize_feature_grant_sources(
    feature_refs: tuple[str, ...],
    *,
    current_sources: tuple[FeatureGrantSource, ...],
    reconciled_base_sources: tuple[FeatureGrantSource, ...],
) -> tuple[FeatureGrantSource, ...]:
    """Carry old provenance forward, then fill new grants from the current draft."""

    allowed = set(feature_refs)
    by_feature: dict[str, FeatureGrantSource] = {}
    for row in reconciled_base_sources:
        if row.feature_ref in allowed:
            by_feature.setdefault(row.feature_ref, row)
    for row in current_sources:
        if row.feature_ref in allowed:
            by_feature.setdefault(row.feature_ref, row)
    return tuple(by_feature[key] for key in sorted(by_feature))
