from __future__ import annotations

from app.content.identity import collect_stable_key_sources
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild
from app.domain.character_builder import compiler as core_compiler
from app.domain.character_builder.compiler import BuilderCompileResult
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


_CORE_COMPILE = getattr(
    core_compiler,
    "_m01_i_core_compile_builder_draft",
    core_compiler.compile_builder_draft,
)


def _derive_sources(build: CharacterBuild) -> CharacterBuild:
    payload = build.model_dump()
    payload.pop("content_sources", None)
    payload["content_sources"] = collect_stable_key_sources(payload)
    return CharacterBuild.model_validate(payload)


def compile_builder_draft(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    base_build: CharacterBuild | None = None,
) -> BuilderCompileResult:
    """Extend the established compiler with the data-driven M01-I rules."""

    runtime = prepare_optional_class_features(
        draft,
        registry,
        base_build=base_build,
    )
    compiled = _CORE_COMPILE(
        draft,
        runtime.registry,
        base_build=base_build,
    )

    runtime_ids = {choice.choice_id for choice in runtime.choices}
    core_choices = tuple(
        choice
        for choice in compiled.choices
        if not (
            choice.option_source == "draft:selection"
            and choice.choice_id in runtime_ids
        )
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

    optional_choices = runtime.choices + nested_choices + retraining_choices
    live_optional_ids = {choice.choice_id for choice in optional_choices}
    core_choices = tuple(
        choice
        for choice in core_choices
        if not (
            choice.option_source == "draft:selection"
            and choice.choice_id in live_optional_ids
        )
    )
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
            nested_choices,
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
            nested_choices,
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

        build = _derive_sources(
            build.model_copy(
                update={
                    "feature_refs": feature_refs,
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


def install_m01_i_compiler_extension() -> None:
    """Install once so direct compiler imports and service imports agree."""

    if getattr(core_compiler, "_m01_i_extension_installed", False):
        return
    core_compiler._m01_i_core_compile_builder_draft = _CORE_COMPILE
    core_compiler.compile_builder_draft = compile_builder_draft
    core_compiler._m01_i_extension_installed = True
