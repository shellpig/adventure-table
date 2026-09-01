from __future__ import annotations

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.schemas import (
    BuilderArtificerResourceSummary,
    BuilderArtificerSummary,
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderMode,
    BuilderOptionKind,
)
from app.domain.rules.artificer import (
    ARMOR_MODELS,
    ARTIFICER_REF,
    advanced_feature_resource_rules,
    artificer_level,
    attunement_capacity,
    attunement_requirement_exceptions,
    infused_item_capacity,
    known_infusion_count,
    selected_artificer_subclass,
    spell_storing_item_capacity,
    subclass_runtime_metadata,
)


def _draft_artificer_level(draft: BuilderDraft) -> int:
    return sum(1 for level in draft.draft_payload.level_choices if level.class_ref == ARTIFICER_REF)


def _anchor_character_level(draft: BuilderDraft) -> int | None:
    levels = [
        level.character_level
        for level in draft.draft_payload.level_choices
        if level.class_ref == ARTIFICER_REF
    ]
    return max(levels) if levels else None


def infusion_choice_id(draft: BuilderDraft) -> str | None:
    anchor = _anchor_character_level(draft)
    if anchor is None or _draft_artificer_level(draft) < 2:
        return None
    return deterministic_choice_id("level", str(anchor), "artificer", "infusions-known")


def _eligible_options(
    registry: ContentRegistry,
    level: int,
) -> tuple[BuilderChoiceOption, ...]:
    options: list[BuilderChoiceOption] = []
    for entry in registry.list_kind("infusion", source="tce"):
        minimum = entry.data.get("minimum_artificer_level")
        if not isinstance(minimum, int) or minimum > level:
            continue
        source_label = entry.source_label or entry.source
        options.append(
            BuilderChoiceOption(
                option_id=entry.key,
                label=f"{entry.name} · {source_label}",
                kind=BuilderOptionKind.REFERENCE,
                reference_id=entry.key,
            )
        )
    return tuple(options)


def build_artificer_infusion_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    base_build: CharacterBuild | None,
) -> tuple[BuilderChoice, ...]:
    level = _draft_artificer_level(draft)
    choice_id = infusion_choice_id(draft)
    if choice_id is None:
        return ()

    target_count = known_infusion_count(level)
    base_count = len(base_build.infusion_refs) if base_build is not None else 0
    choose_count = target_count
    if draft.mode is BuilderMode.LEVEL_UP:
        choose_count = max(0, target_count - base_count)
        if choose_count == 0:
            return ()

    selection = draft.draft_payload.choice_selections.get(choice_id)
    if selection is not None:
        selected = selection.selected_option_ids
    elif draft.mode in {BuilderMode.BUILD_EDIT, BuilderMode.CORRECTION} and base_build is not None:
        selected = base_build.infusion_refs
    else:
        selected = ()

    return (
        BuilderChoice(
            choice_id=choice_id,
            label="Artificer Infusions Known",
            source_ref="tce:feature:infuse-item",
            required=True,
            choose_count=choose_count,
            option_source="content:infusion",
            options=_eligible_options(registry, level),
            selected_option_ids=tuple(selected),
        ),
    )


def compile_artificer_infusion_refs(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
    *,
    base_build: CharacterBuild | None,
) -> tuple[str, ...]:
    if _draft_artificer_level(draft) < 2:
        return ()

    choice = next((item for item in choices if item.option_source == "content:infusion"), None)
    selected = choice.selected_option_ids if choice is not None else ()
    if draft.mode is BuilderMode.LEVEL_UP:
        base_refs = base_build.infusion_refs if base_build is not None else ()
        return tuple(dict.fromkeys((*base_refs, *selected)))
    if selected:
        return tuple(dict.fromkeys(selected))
    if base_build is not None and draft.mode in {BuilderMode.BUILD_EDIT, BuilderMode.CORRECTION}:
        return base_build.infusion_refs
    return ()


def build_artificer_summary(build: CharacterBuild | None) -> BuilderArtificerSummary | None:
    if build is None:
        return None
    level = artificer_level(build)
    if level <= 0:
        return None
    exceptions = attunement_requirement_exceptions(build)
    bypasses = tuple(
        name.removeprefix("ignore_").removesuffix("_requirement")
        for name, enabled in exceptions.items()
        if enabled
    )
    runtime = subclass_runtime_metadata(build)
    resources = tuple(
        BuilderArtificerResourceSummary(
            resource_id=rule.resource_id,
            feature_ref=rule.feature_ref,
            capacity=rule.capacity,
            recharge=rule.recharge,
        )
        for rule in advanced_feature_resource_rules(build)
    )
    return BuilderArtificerSummary(
        artificer_level=level,
        known_infusion_refs=build.infusion_refs,
        known_infusion_limit=known_infusion_count(level),
        infused_item_capacity=infused_item_capacity(level),
        attunement_capacity=attunement_capacity(build),
        attunement_requirement_bypasses=bypasses,
        resources=resources,
        spell_storing_item_capacity=spell_storing_item_capacity(build),
        armor_model_options=ARMOR_MODELS if selected_artificer_subclass(build) == "tce:subclass:armorer" else (),
        subclass_runtime_feature_ref=(
            runtime.get("feature_ref") if isinstance(runtime.get("feature_ref"), str) else None
        ),
        subclass_runtime_kind=(
            runtime.get("runtime_kind") if isinstance(runtime.get("runtime_kind"), str) else None
        ),
    )
