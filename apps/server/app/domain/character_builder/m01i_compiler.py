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
    prevent_duplicate_retraining_targets,
    reconcile_feature_pool_retraining,
)
from app.domain.character_builder.m01i_runtime import prepare_optional_class_features_for_m01i
from app.domain.character_builder.m01i_validation import (
    active_retraining_choices,
    apply_cantrip_retraining_for_m01i,
    validate_feature_grant_source_references,
    validate_final_feature_pool_dependencies,
    validate_unique_feature_pool_selections,
)
from app.domain.character_builder.m01j_expertise import apply_m01j_skill_expertise
from app.domain.character_builder.m01j_runtime import (
    apply_m01j_spellcasting_build,
    apply_m01j_spellcasting_summary,
    apply_m01j_subclass_runtime,
    prepare_m01j_subclasses,
)
from app.domain.character_builder.m01k_integration import (
    apply_m01k_post_compile,
    prepare_m01k_core_registry,
)
from app.domain.character_builder.optional_class_features import (
    apply_feature_pool_retraining,
    apply_optional_feature_replacements,
    apply_optional_pool_eligibility,
    build_optional_nested_choices,
    build_optional_retraining_choices,
    compile_nested_feature_selections,
    compile_nested_spell_access,
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
    if choice_id.startswith("m01-j:"):
        return True
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


def _is_extension_spell_profile(profile_id: str) -> bool:
    return profile_id.startswith("subclass:phb2014:")


def _core_draft(draft: BuilderDraft, registry: ContentRegistry) -> BuilderDraft:
    """Hide extension-owned selections from the pre-M01-I/J compiler.

    The core compiler must still see parent choices such as the SRD Fighter
    Fighting Style selection; it must not see optional-feature toggles, nested
    children, retraining controls, M01-J subclass child choices, or M01-J
    subclass spell profiles that only the extension compilers understand.
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
    spell_choices = {
        profile_id: selection
        for profile_id, selection in draft.draft_payload.spell_choices.items()
        if not _is_extension_spell_profile(profile_id)
    }
    if (
        len(selections) == len(draft.draft_payload.choice_selections)
        and len(spell_choices) == len(draft.draft_payload.spell_choices)
    ):
        return draft
    payload = draft.draft_payload.model_copy(
        update={
            "choice_selections": selections,
            "spell_choices": spell_choices,
        }
    )
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
    """Extend the established compiler with M01-I, M01-J and M01-K rules.

    P0/P1 remains the core compiler. M01-K hardens PHB feat acquisition/spell
    semantics on that same path; M01-J contributes active-subclass spell overlays,
    permanent subclass grants/choices, conditional grants and PHB third-caster
    profiles; M01-I composes its optional class-feature overlay on top. Direct
    Create, Level Up and Multiclass therefore remain on one compiler path.
    """

    m01j = prepare_m01j_subclasses(draft, registry)
    runtime = prepare_optional_class_features_for_m01i(
        draft,
        m01j.registry,
        base_build=base_build,
    )
    # The old core structural gate only understands SRD's ability-only feat
    # prerequisites. K defers PHB feat gating to its level-ordered resolver so
    # armor proficiency, spellcasting and compound prerequisites are evaluated
    # against the exact point in the level rail rather than rejected early.
    core_registry = prepare_m01k_core_registry(runtime.registry)
    compiled = compile_core_builder_draft(
        _core_draft(draft, runtime.registry),
        core_registry,
        base_build=base_build,
    )
    compiled = apply_m01k_post_compile(
        draft,
        runtime.registry,
        compiled,
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
    retraining_choices = active_retraining_choices(retraining_choices, runtime)
    retraining_choices = prevent_duplicate_retraining_targets(draft, retraining_choices)
    retraining_nested_choices = build_retraining_nested_choices(
        draft,
        runtime,
        retraining_choices,
        base_build=base_build,
    )
    all_nested_choices = nested_choices + retraining_nested_choices

    optional_choices = runtime.choices + all_nested_choices + retraining_choices
    choices = core_choices + optional_choices + m01j.choices

    issues = [
        *compiled.validation.issues,
        *runtime.issues,
        *m01j.issues,
        *validate_optional_choices(draft, optional_choices),
        *validate_unique_feature_pool_selections(draft, choices, runtime.registry),
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
        spell_entries, cantrip_retraining_issues = apply_cantrip_retraining_for_m01i(
            spell_entries,
            draft,
            runtime,
        )
        issues.extend(cantrip_retraining_issues)

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
            current_sources=current_sources,
            reconciled_base_sources=reconciled_base_sources,
        )

        build = build.model_copy(
            update={
                "feature_refs": feature_refs,
                "feature_grant_sources": feature_grant_sources,
                "spell_access_entries": spell_entries,
            }
        )
        build = apply_m01j_subclass_runtime(build, m01j)
        build = apply_m01j_skill_expertise(build, draft)
        build = apply_m01j_spellcasting_build(build, m01j)
        build = _derive_sources(build)
        # Validate again after J has appended selected option provenance/grants.
        issues.extend(validate_feature_grant_source_references(build, runtime.registry))
        issues.extend(validate_final_feature_pool_dependencies(build, runtime.registry))

    resolved_summary = apply_m01j_spellcasting_summary(
        compiled.resolved_summary,
        m01j,
        build,
    )
    validation = make_validation_result(tuple(issues))
    return BuilderCompileResult(
        build_candidate=build,
        resolved_summary=resolved_summary,
        choices=choices,
        validation=validation,
        starting_equipment=compiled.starting_equipment,
        initial_prepared_spells=compiled.initial_prepared_spells,
    )
