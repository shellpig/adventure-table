from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.content.identity import parse_stable_key, reference_to_stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild
from app.domain.character_builder import m01j_extension as _extension
from app.domain.character_builder.m01j_subclasses import m01j_choice_id
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderOptionKind,
    BuilderResolvedSummary,
)


@dataclass(frozen=True)
class ConditionalGrant:
    target: str
    refs: tuple[str, ...]


@dataclass(frozen=True)
class M01JSubclassRuntime:
    base: _extension.M01JSubclassRuntime
    registry: ContentRegistry
    choices: tuple[BuilderChoice, ...]
    issues: tuple[BuilderIssue, ...]
    conditional_grants: tuple[ConditionalGrant, ...]


def _issue(code: str, path: str, message: str, *refs: str) -> BuilderIssue:
    return BuilderIssue(
        code=code,
        severity=BuilderIssueSeverity.BLOCKING_ERROR,
        path=path,
        message=message,
        related_refs=tuple(refs),
    )


def _class_state(draft: BuilderDraft) -> tuple[Counter[str], dict[str, str]]:
    levels: Counter[str] = Counter()
    subclasses: dict[str, str] = {}
    for row in draft.draft_payload.level_choices:
        levels[row.class_ref] += 1
        if row.subclass_ref is not None:
            subclasses[row.class_ref] = row.subclass_ref
    return levels, subclasses


def _proficiency_to_skill(registry: ContentRegistry, ref: str) -> str | None:
    try:
        parsed = parse_stable_key(ref)
    except ValueError:
        return None
    if parsed.kind == "skill":
        return ref
    if parsed.kind != "proficiency" or not parsed.index.startswith("skill-"):
        return None
    candidate = f"{parsed.source}:skill:{parsed.index.removeprefix('skill-')}"
    return candidate if registry.get_optional(candidate) is not None else None


def _draft_skill_refs(draft: BuilderDraft, registry: ContentRegistry) -> set[str]:
    refs: set[str] = set()
    background = draft.draft_payload.background_selection
    if background is not None:
        entry = registry.get_optional(background.reference_id)
        raw = entry.data.get("starting_proficiencies") if entry is not None else None
        if isinstance(raw, list):
            for reference in raw:
                if not isinstance(reference, dict):
                    continue
                try:
                    key = reference_to_stable_key(reference)
                except ValueError:
                    key = None
                if key is not None and (skill := _proficiency_to_skill(registry, key)) is not None:
                    refs.add(skill)
    for selection in draft.draft_payload.choice_selections.values():
        for ref in selection.selected_option_ids:
            skill = _proficiency_to_skill(registry, ref)
            if skill is not None:
                refs.add(skill)
    return refs


def _starting_save_refs(draft: BuilderDraft, registry: ContentRegistry) -> set[str]:
    if not draft.draft_payload.level_choices:
        return set()
    class_entry = registry.get_optional(draft.draft_payload.level_choices[0].class_ref)
    raw = class_entry.data.get("saving_throws") if class_entry is not None else None
    if not isinstance(raw, list):
        return set()
    refs: set[str] = set()
    for reference in raw:
        if not isinstance(reference, dict):
            continue
        try:
            ref = reference_to_stable_key(reference, kinds={"ability"})
        except ValueError:
            ref = None
        if ref is not None:
            refs.add(ref)
    return refs


def _selection(draft: BuilderDraft, choice_id: str) -> tuple[str, ...]:
    value = draft.draft_payload.choice_selections.get(choice_id)
    return value.selected_option_ids if value is not None else ()


def _choice_options(registry: ContentRegistry, refs: tuple[str, ...], category: str) -> tuple[BuilderChoiceOption, ...]:
    return tuple(
        BuilderChoiceOption(
            option_id=ref,
            label=f"{registry.get(ref).name} · {registry.get(ref).source_label or registry.get(ref).source}",
            kind=BuilderOptionKind.REFERENCE,
            reference_id=ref,
            category=category,
        )
        for ref in refs
        if registry.get_optional(ref) is not None
    )


def _known_final_choice_ids() -> set[str]:
    return {
        m01j_choice_id("phb2014:subclass:totem-warrior", "tiger-aspect-skills"),
        m01j_choice_id("scag:subclass:purple-dragon-knight", "royal-envoy-fallback-skill"),
        m01j_choice_id("xge:subclass:samurai", "elegant-courtier-fallback-save"),
    }


def _draft_without_final_choices(draft: BuilderDraft) -> BuilderDraft:
    final_ids = _known_final_choice_ids()
    selections = {
        choice_id: value
        for choice_id, value in draft.draft_payload.choice_selections.items()
        if choice_id not in final_ids
    }
    if len(selections) == len(draft.draft_payload.choice_selections):
        return draft
    payload = draft.draft_payload.model_copy(update={"choice_selections": selections})
    return draft.model_copy(update={"draft_payload": payload})


def _active_totem_tiger(
    draft: BuilderDraft,
    registry: ContentRegistry,
    class_levels: Counter[str],
    selected_subclasses: dict[str, str],
) -> bool:
    class_ref = "srd5.1:class:barbarian"
    if selected_subclasses.get(class_ref) != "phb2014:subclass:totem-warrior":
        return False
    if class_levels[class_ref] < 6:
        return False
    choice_id = m01j_choice_id("phb2014:subclass:totem-warrior", "aspect-of-the-beast")
    selected = _selection(draft, choice_id)
    return len(selected) == 1 and registry.get_optional(selected[0]) is not None and registry.get(selected[0]).name == "Tiger"


def _compile_conditional_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[tuple[BuilderChoice, ...], tuple[BuilderIssue, ...], tuple[ConditionalGrant, ...], set[str]]:
    class_levels, selected_subclasses = _class_state(draft)
    known_skills = _draft_skill_refs(draft, registry)
    known_saves = _starting_save_refs(draft, registry)
    choices: list[BuilderChoice] = []
    issues: list[BuilderIssue] = []
    grants: list[ConditionalGrant] = []
    active_ids: set[str] = set()

    if _active_totem_tiger(draft, registry, class_levels, selected_subclasses):
        subclass_ref = "phb2014:subclass:totem-warrior"
        choice_id = m01j_choice_id(subclass_ref, "tiger-aspect-skills")
        active_ids.add(choice_id)
        refs = tuple(
            ref
            for ref in (
                "srd5.1:skill:athletics",
                "srd5.1:skill:acrobatics",
                "srd5.1:skill:stealth",
                "srd5.1:skill:survival",
            )
            if ref not in known_skills
        )
        selected = _selection(draft, choice_id)
        choices.append(
            BuilderChoice(
                choice_id=choice_id,
                label="Aspect of the Beast — Tiger skills",
                source_ref=subclass_ref,
                required=True,
                choose_count=2,
                option_source="content:m01-j-conditional-grant",
                options=_choice_options(registry, refs, "skill"),
                selected_option_ids=selected,
            )
        )
        if len(selected) != 2 or any(ref not in refs for ref in selected):
            issues.append(
                _issue(
                    "invalid_totem_tiger_skill_choice",
                    f"draft_payload.choice_selections.{choice_id}",
                    "Tiger Aspect requires two available skill proficiencies.",
                    *selected,
                )
            )
        else:
            grants.append(ConditionalGrant("skill", selected))

    pdk_class_ref = "srd5.1:class:fighter"
    pdk_ref = "scag:subclass:purple-dragon-knight"
    if selected_subclasses.get(pdk_class_ref) == pdk_ref and class_levels[pdk_class_ref] >= 7:
        persuasion = "srd5.1:skill:persuasion"
        if persuasion not in known_skills:
            grants.append(ConditionalGrant("skill", (persuasion,)))
        else:
            choice_id = m01j_choice_id(pdk_ref, "royal-envoy-fallback-skill")
            active_ids.add(choice_id)
            refs = tuple(
                ref
                for ref in (
                    "srd5.1:skill:animal-handling",
                    "srd5.1:skill:insight",
                    "srd5.1:skill:intimidation",
                    "srd5.1:skill:performance",
                )
                if ref not in known_skills
            )
            selected = _selection(draft, choice_id)
            choices.append(
                BuilderChoice(
                    choice_id=choice_id,
                    label="Royal Envoy — replacement proficiency",
                    source_ref=pdk_ref,
                    required=True,
                    choose_count=1,
                    option_source="content:m01-j-conditional-grant",
                    options=_choice_options(registry, refs, "skill"),
                    selected_option_ids=selected,
                )
            )
            if len(selected) != 1 or selected[0] not in refs:
                issues.append(
                    _issue(
                        "invalid_royal_envoy_skill_choice",
                        f"draft_payload.choice_selections.{choice_id}",
                        "Royal Envoy requires one replacement skill when Persuasion is already known.",
                        *selected,
                    )
                )
            else:
                grants.append(ConditionalGrant("skill", selected))

    samurai_ref = "xge:subclass:samurai"
    if selected_subclasses.get(pdk_class_ref) == samurai_ref and class_levels[pdk_class_ref] >= 7:
        wisdom = "srd5.1:ability:wis"
        if wisdom not in known_saves:
            grants.append(ConditionalGrant("saving_throw", (wisdom,)))
        else:
            choice_id = m01j_choice_id(samurai_ref, "elegant-courtier-fallback-save")
            active_ids.add(choice_id)
            refs = (
                "srd5.1:ability:int",
                "srd5.1:ability:cha",
            )
            selected = _selection(draft, choice_id)
            choices.append(
                BuilderChoice(
                    choice_id=choice_id,
                    label="Elegant Courtier — replacement saving throw",
                    source_ref=samurai_ref,
                    required=True,
                    choose_count=1,
                    option_source="content:m01-j-conditional-grant",
                    options=_choice_options(registry, refs, "saving_throw"),
                    selected_option_ids=selected,
                )
            )
            if len(selected) != 1 or selected[0] not in refs:
                issues.append(
                    _issue(
                        "invalid_samurai_save_choice",
                        f"draft_payload.choice_selections.{choice_id}",
                        "Elegant Courtier requires INT or CHA save proficiency when WIS is already known.",
                        *selected,
                    )
                )
            else:
                grants.append(ConditionalGrant("saving_throw", selected))

    return tuple(choices), tuple(issues), tuple(grants), active_ids


def prepare_m01j_subclasses(draft: BuilderDraft, registry: ContentRegistry) -> M01JSubclassRuntime:
    base = _extension.prepare_m01j_subclasses(_draft_without_final_choices(draft), registry)
    conditional_choices, conditional_issues, grants, active_final_ids = _compile_conditional_choices(
        draft,
        registry,
    )
    issues = list(base.issues)
    # The extension saw final-runtime selections removed, so it cannot identify
    # stale conditional selections. Own that validation here.
    for choice_id, selection in draft.draft_payload.choice_selections.items():
        if choice_id in _known_final_choice_ids() and choice_id not in active_final_ids:
            issues.append(
                _issue(
                    "stale_subclass_choice",
                    f"draft_payload.choice_selections.{choice_id}",
                    "A conditional subclass choice remains selected after its prerequisite is no longer active.",
                    *selection.selected_option_ids,
                )
            )
    issues.extend(conditional_issues)
    return M01JSubclassRuntime(
        base=base,
        registry=base.registry,
        choices=tuple((*base.choices, *conditional_choices)),
        issues=tuple(issues),
        conditional_grants=grants,
    )


def _apply_branch_progression(build: CharacterBuild, registry: ContentRegistry) -> tuple[str, ...]:
    class_levels = Counter(build.class_progression)
    refs = list(build.feature_refs)
    for feature_ref in tuple(build.feature_refs):
        feature = registry.get_optional(feature_ref)
        if feature is None:
            continue
        raw_progression = feature.data.get("branch_progression_refs")
        parent = feature.data.get("class")
        if not isinstance(raw_progression, dict) or not isinstance(parent, dict):
            continue
        try:
            class_ref = reference_to_stable_key(parent, kinds={"class"})
        except ValueError:
            class_ref = None
        if class_ref is None:
            continue
        class_level = class_levels[class_ref]
        for raw_level, ref in raw_progression.items():
            if not isinstance(ref, str):
                continue
            try:
                threshold = int(raw_level)
            except (TypeError, ValueError):
                continue
            if threshold <= class_level and registry.get_optional(ref) is not None:
                refs.append(ref)
    return tuple(dict.fromkeys(refs))


def apply_m01j_subclass_runtime(
    build: CharacterBuild,
    runtime: M01JSubclassRuntime,
) -> CharacterBuild:
    build = _extension.apply_m01j_subclass_runtime(build, runtime.base)
    skills = list(build.skill_choices)
    saves = list(build.saving_throw_proficiencies)
    for grant in runtime.conditional_grants:
        if grant.target == "skill":
            skills.extend(grant.refs)
        elif grant.target == "saving_throw":
            saves.extend(grant.refs)
    return build.model_copy(
        update={
            "feature_refs": _apply_branch_progression(build, runtime.registry),
            "skill_choices": tuple(dict.fromkeys(skills)),
            "saving_throw_proficiencies": tuple(dict.fromkeys(saves)),
        }
    )


def apply_m01j_spellcasting_summary(
    summary: BuilderResolvedSummary,
    runtime: M01JSubclassRuntime,
    build: CharacterBuild | None,
) -> BuilderResolvedSummary:
    return _extension.apply_m01j_spellcasting_summary(summary, runtime.base, build)


def apply_m01j_spellcasting_build(
    build: CharacterBuild,
    runtime: M01JSubclassRuntime,
) -> CharacterBuild:
    return _extension.apply_m01j_spellcasting_build(build, runtime.base)
