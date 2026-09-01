from __future__ import annotations

from app.content.identity import collect_stable_key_sources
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild
from app.domain.character_builder.compiler import (
    BuilderCompileResult,
    compile_builder_draft as compile_core_builder_draft,
)
from app.domain.character_builder.m01i_provenance import (
    build_retraining_nested_choices,
    current_feature_grant_sources,
    finalize_feature_grant_sources,
    reconcile_feature_pool_retraining,
)
from app.domain.character_builder.optional_class_features import (
    apply_cantrip_retraining,
    apply_feature_pool_retraining,
    apply_optional_feature_replacements,
    apply_optional_pool_eligibility,
    build_optional_nested_choices,
    build_optional_retraining_choices,
    compile_nested_feature_selections,
    compile_nested_spell_access,
    prepare_optional_class_features,
    suppress_replaced_choices,
    validate_optional_choices,
)
from app.domain.character_builder.schemas import BuilderDraft
from app.domain.character_builder.validation import make_validation_result


def _derive_sources(build: CharacterBuild) -> CharacterBuild:
    payload = build.model_dump()
    payload.pop("content_sources", None)
    payload["content_sources"] = collect_stable_key_sources(payload)
    return CharacterBuild.model_validate(payload)


def _is_extension_selection(
    choice_id: str,
    source_ref: str | None,
    registry: ContentRegistry,
) -> bool:
    parts = choice_id.split(":")
    if choice_id.startswith("m01-i:"):
        return True
    if len(parts) >= 3 and parts[0] == "level" and parts[1].isdigit() and parts[2] == "m01-i":
        return True
    if source_ref is None:
        return False
    source = registry.get_optional(source_ref)
    if source is None:
        return False
    return isinstance(source.data.get("optional_class_feature"), dict) or isinstance(
        source.data.get("choice_pool_option"),
        dict,
    )


def _core_draft(draft: BuilderDraft, registry: ContentRegistry) -> BuilderDraft:
    """Hide M01-I-owned selections from the pre-M01-I compiler.

    The core compiler must still see parent choices such as the SRD Fighter
    Fighting Style selection; it must not see optional-feature toggles, nested
    children or retraining controls that only this extension understands.
    Otherwise the legacy draft-selection fallback correctly—but undesirably for
    an extension-owned choice—flags them as unknown/illegal.
    """

    selections = {
        choice_id: selection
        for choice_id, selection in draft.draft_payload.choice_selections.items()
        if not _is_extension_selection(
            choice_id,
            selection.source_ref,
            registry,
        )
    }
    if len(selections) == len(draft.draft_payload.choice_selections):
        return draft
    payload = draft.draft_payload.model_copy(update={"choice_selections": selections})
    return draft.model_copy(update={"draft_payload": payload})


def _is_extension_draft_fallback(choice, registry: ContentRegistry) -> bool:
    return choice.option_source == "draft:selection" and _is_extension_selection(
        choice.choice_id,
        choice.source_ref,
        registry,
    )


def compile_builder_draft(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    base_build: CharacterBuild | None = None,
) -> BuilderCompileResult:
    """Extend the established compiler with the data-driven M01-I rules.

    The P0/P1/M01-G/H compiler remains the core pipeline. M01-I wraps it
    explicitly from the service layer so importing this package has no hidden
    monkey-patching or import-order dependency.
    """

    runtime = prepare_optional_class_features(
        draft,
        registry,
        base_build=base_build,
    )
    compiled = compile_core_builder_draft(
        _core_draft(draft, runtime.registry),
        runtime.registry,
        base_build=base_build,
    )

    core_choices = tuple(
        choice
        for choice in compiled.choices
        if not _is_extension_draft_fallback(choice, runtime.registry)
    )
    core_choices = apply_optional_pool_eligibility(
        draft,
        runtime.registry,
        core_choices,
        base_build=base_build,
    )
    core_choices = suppress_replaced_choices(core_choices, runtime)

    nested_choices = build_optional_nested_choices(
        draft,
        runtime.registry,
        core_choices,
        base_build=base_build,
    )
    retraining_choices = build_optional_retraining_choices(
        draft,
        runtime,
        base_build=base_build,
    )
    retraining_nested_choices = build_retraining_nested_choices(
        draft,
        runtime,
        retraining_choices,
        base_build=base_build,
    )
    all_nested_choices = nested_choices + retraining_nested_choices

    optional_choices = runtime.choices + all_nested_choices + retraining_choices
    choices = core_choices + optional_choices

    issues = [
        *compiled.validation.issues,
        *runtime.issues,
        *validate_optional_choices(draft, optional_choices),
    ]

    build = compiled.build_candidate
    if build is not None:
        feature_refs, replacement_issues = apply_optional_feature_replacements(
            build.feature_refs,
            runtime,
        )
        issues.extend(replacement_issues)

        nested_structural = compile_nested_feature_selections(
            draft,
            runtime.registry,
            all_nested_choices,
        )
        feature_refs = tuple(
            dict.fromkeys((*feature_refs, *nested_structural.feature_refs))
        )
        feature_refs = apply_feature_pool_retraining(
            feature_refs,
            draft,
            retraining_choices,
        )

        nested_spell_entries = compile_nested_spell_access(
            draft,
            runtime.registry,
            all_nested_choices,
        )
        spell_entries = tuple(
            {
                entry.entry_id: entry
                for entry in (*build.spell_access_entries, *nested_spell_entries)
            }.values()
        )
        spell_entries = apply_cantrip_retraining(
            spell_entries,
            draft,
            retraining_choices,
            runtime.registry,
        )

        base_sources = base_build.feature_grant_sources if base_build is not None else ()
        feature_refs, spell_entries, reconciled_base_sources, provenance_issues = (
            reconcile_feature_pool_retraining(
                feature_refs,
                spell_entries,
                base_sources,
                draft,
                retraining_choices,
                runtime.registry,
            )
        )
        issues.extend(provenance_issues)

        current_sources = current_feature_grant_sources(
            draft,
            runtime,
            core_choices=core_choices,
            nested_choices=all_nested_choices,
            retraining_choices=retraining_choices,
        )
        feature_grant_sources = finalize_feature_grant_sources(
            feature_refs,
            base_build=base_build,
            current_sources=current_sources,
            reconciled_base_sources=reconciled_base_sources,
        )

        build = _derive_sources(
            build.model_copy(
                update={
                    "feature_refs": feature_refs,
                    "feature_grant_sources": feature_grant_sources,
                    "spell_access_entries": spell_entries,
                }
            )
        )

    validation = make_validation_result(tuple(issues))
    return BuilderCompileResult(
        build_candidate=build,
        resolved_summary=compiled.resolved_summary,
        choices=choices,
        validation=validation,
        starting_equipment=compiled.starting_equipment,
        initial_prepared_spells=compiled.initial_prepared_spells,
    )