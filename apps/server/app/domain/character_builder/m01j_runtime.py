from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha1
from typing import Any

from app.content.identity import parse_stable_key, reference_to_stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, SpellAccessEntry
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
    source_ref: str | None = None
    access_type: str | None = None


@dataclass(frozen=True)
class SpellReplacement:
    subclass_ref: str
    original_spell_ref: str
    replacement_spell_ref: str
    access_type: str
    minimum_class_level: int


@dataclass(frozen=True)
class M01JSubclassRuntime:
    base: _extension.M01JSubclassRuntime
    registry: ContentRegistry
    choices: tuple[BuilderChoice, ...]
    issues: tuple[BuilderIssue, ...]
    conditional_grants: tuple[ConditionalGrant, ...]
    spell_replacements: tuple[SpellReplacement, ...]


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


def _draft_spell_refs(draft: BuilderDraft, registry: ContentRegistry) -> set[str]:
    refs: set[str] = set()
    for selection in draft.draft_payload.spell_choices.values():
        for ref in (
            *selection.cantrip_keys,
            *selection.known_spell_keys,
            *selection.spellbook_spell_keys,
            *selection.prepared_spell_keys,
        ):
            if registry.get_optional(ref) is not None and stable_key_is_kind(ref, "spell"):
                refs.add(ref)
    for selection in draft.draft_payload.choice_selections.values():
        for ref in selection.selected_option_ids:
            if registry.get_optional(ref) is not None and stable_key_is_kind(ref, "spell"):
                refs.add(ref)
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


def _choice_options(
    registry: ContentRegistry,
    refs: tuple[str, ...],
    category: str,
) -> tuple[BuilderChoiceOption, ...]:
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


def _record_minimum_level(record: dict[str, Any]) -> int:
    prerequisites = record.get("prerequisites")
    if not isinstance(prerequisites, list):
        return 1
    minimum = 1
    for prerequisite in prerequisites:
        if not isinstance(prerequisite, dict) or prerequisite.get("type") != "level":
            continue
        index = prerequisite.get("index")
        if not isinstance(index, str):
            continue
        parts = index.rsplit("-", 1)
        if len(parts) != 2:
            continue
        try:
            minimum = max(minimum, int(parts[1]))
        except ValueError:
            continue
    return minimum


def _spell_on_class_list(registry: ContentRegistry, spell: Any, class_ref: str) -> bool:
    raw_classes = spell.data.get("classes")
    if isinstance(raw_classes, list):
        for reference in raw_classes:
            if not isinstance(reference, dict):
                continue
            try:
                if reference_to_stable_key(reference, kinds={"class"}) == class_ref:
                    return True
            except ValueError:
                continue
    class_entry = registry.get_optional(class_ref)
    dedicated = class_entry.data.get("spell_list") if class_entry is not None else None
    if isinstance(dedicated, list):
        for reference in dedicated:
            if not isinstance(reference, dict):
                continue
            try:
                if reference_to_stable_key(reference, kinds={"spell"}) == spell.key:
                    return True
            except ValueError:
                continue
    return False


def _spell_school_index(spell: Any) -> str | None:
    raw = spell.data.get("school")
    if not isinstance(raw, dict):
        return None
    try:
        key = reference_to_stable_key(raw, kinds={"magic-school"})
    except ValueError:
        key = None
    if key is not None:
        return parse_stable_key(key).index
    index = raw.get("index")
    return index if isinstance(index, str) else None


def _replacement_choice_key(original_spell_ref: str, minimum_level: int) -> str:
    parsed = parse_stable_key(original_spell_ref, kinds={"spell"})
    return f"subclass-spell-replacement-{minimum_level}-{parsed.source}-{parsed.index}"


def _active_spell_replacement_rows(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[tuple[str, str, int, dict[str, Any], dict[str, Any], str, int], ...]:
    class_levels, selected_subclasses = _class_state(draft)
    result: list[tuple[str, str, int, dict[str, Any], dict[str, Any], str, int]] = []
    for class_ref, subclass_ref in selected_subclasses.items():
        subclass = registry.get_optional(subclass_ref)
        if subclass is None:
            continue
        spec = subclass.data.get("subclass_spell_replacement")
        rows = subclass.data.get("spells")
        if not isinstance(spec, dict) or not isinstance(rows, list):
            continue
        class_level = class_levels[class_ref]
        for row in rows:
            if not isinstance(row, dict):
                continue
            minimum = _record_minimum_level(row)
            if minimum > class_level:
                continue
            raw_spell = row.get("spell")
            if not isinstance(raw_spell, dict):
                continue
            try:
                spell_ref = reference_to_stable_key(raw_spell, kinds={"spell"})
            except ValueError:
                spell_ref = None
            if spell_ref is None or registry.get_optional(spell_ref) is None:
                continue
            result.append(
                (
                    class_ref,
                    subclass_ref,
                    class_level,
                    spec,
                    row,
                    spell_ref,
                    minimum,
                )
            )
    return tuple(result)


def _active_spell_replacement_choice_ids(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> set[str]:
    return {
        m01j_choice_id(
            subclass_ref,
            _replacement_choice_key(original_spell_ref, minimum),
        )
        for _class_ref, subclass_ref, _class_level, _spec, _row, original_spell_ref, minimum
        in _active_spell_replacement_rows(draft, registry)
    }


def _replacement_spell_options(
    registry: ContentRegistry,
    original_spell_ref: str,
    spec: dict[str, Any],
) -> tuple[str, ...]:
    original = registry.get(original_spell_ref)
    spell_level = original.data.get("level")
    eligible_classes = tuple(
        ref for ref in spec.get("eligible_class_refs", ()) if isinstance(ref, str)
    )
    allowed_schools = {
        value for value in spec.get("school_indices", ()) if isinstance(value, str)
    }
    if not isinstance(spell_level, int) or not eligible_classes or not allowed_schools:
        return (original_spell_ref,)
    refs = [original_spell_ref]
    for spell in registry.list_kind("spell"):
        if spell.key == original_spell_ref or spell.data.get("level") != spell_level:
            continue
        if _spell_school_index(spell) not in allowed_schools:
            continue
        if not any(_spell_on_class_list(registry, spell, class_ref) for class_ref in eligible_classes):
            continue
        refs.append(spell.key)
    return tuple(dict.fromkeys(refs))


def _compile_spell_replacement_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[
    tuple[BuilderChoice, ...],
    tuple[BuilderIssue, ...],
    tuple[SpellReplacement, ...],
    set[str],
]:
    choices: list[BuilderChoice] = []
    issues: list[BuilderIssue] = []
    replacements: list[SpellReplacement] = []
    active_ids: set[str] = set()
    final_by_subclass: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    class_level_by_subclass: dict[str, int] = {}

    for (
        _class_ref,
        subclass_ref,
        class_level,
        spec,
        row,
        original_spell_ref,
        minimum,
    ) in _active_spell_replacement_rows(draft, registry):
        class_level_by_subclass[subclass_ref] = class_level
        choice_key = _replacement_choice_key(original_spell_ref, minimum)
        choice_id = m01j_choice_id(subclass_ref, choice_key)
        active_ids.add(choice_id)
        refs = _replacement_spell_options(registry, original_spell_ref, spec)
        selection = draft.draft_payload.choice_selections.get(choice_id)
        selected = selection.selected_option_ids if selection is not None else ()
        choices.append(
            BuilderChoice(
                choice_id=choice_id,
                label=f"{registry.get(subclass_ref).name} — replace {registry.get(original_spell_ref).name}",
                source_ref=subclass_ref,
                required=False,
                choose_count=1,
                option_source="content:m01-j-subclass-spell-replacement",
                options=_choice_options(registry, refs, "spell"),
                selected_option_ids=selected,
            )
        )

        final_ref = original_spell_ref
        if selection is not None:
            if len(selected) != 1:
                issues.append(
                    _issue(
                        "invalid_subclass_spell_replacement_count",
                        f"draft_payload.choice_selections.{choice_id}",
                        "A subclass spell replacement must select exactly one final spell.",
                        subclass_ref,
                    )
                )
            elif selected[0] not in refs:
                issues.append(
                    _issue(
                        "illegal_subclass_spell_replacement",
                        f"draft_payload.choice_selections.{choice_id}",
                        "The replacement spell must have the same spell level and match the feature's class/school restrictions.",
                        subclass_ref,
                        selected[0],
                    )
                )
            else:
                final_ref = selected[0]

        final_by_subclass[subclass_ref].append((final_ref, minimum, original_spell_ref))
        if final_ref != original_spell_ref:
            replacements.append(
                SpellReplacement(
                    subclass_ref=subclass_ref,
                    original_spell_ref=original_spell_ref,
                    replacement_spell_ref=final_ref,
                    access_type=str(row.get("access_type") or "granted"),
                    minimum_class_level=minimum,
                )
            )

    for subclass_ref, final_rows in final_by_subclass.items():
        final_refs = [ref for ref, _minimum, _original in final_rows]
        duplicates = sorted(ref for ref, count in Counter(final_refs).items() if count > 1)
        if duplicates:
            issues.append(
                _issue(
                    "duplicate_subclass_replacement_spell",
                    "draft_payload.choice_selections",
                    "A replaceable subclass spell list cannot contain the same final spell more than once.",
                    subclass_ref,
                    *duplicates,
                )
            )

        class_level = class_level_by_subclass[subclass_ref]
        changed = [
            replacement
            for replacement in replacements
            if replacement.subclass_ref == subclass_ref
        ]
        for threshold in sorted(
            {replacement.minimum_class_level for replacement in changed},
            reverse=True,
        ):
            needed = sum(
                1 for replacement in changed if replacement.minimum_class_level >= threshold
            )
            available_level_ups = class_level - threshold + 1
            if needed > available_level_ups:
                issues.append(
                    _issue(
                        "subclass_spell_replacement_timing_exceeded",
                        "draft_payload.choice_selections",
                        "The final subclass spell list requires more replacements than the level-by-level feature permits.",
                        subclass_ref,
                    )
                )
                break

    return tuple(choices), tuple(issues), tuple(replacements), active_ids


def _known_final_choice_ids() -> set[str]:
    return {
        m01j_choice_id("phb2014:subclass:totem-warrior", "tiger-aspect-skills"),
        m01j_choice_id("scag:subclass:purple-dragon-knight", "royal-envoy-fallback-skill"),
        m01j_choice_id("xge:subclass:samurai", "elegant-courtier-fallback-save"),
        m01j_choice_id("phb2014:subclass:illusion", "improved-minor-illusion-fallback-cantrip"),
    }


def _draft_without_final_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> BuilderDraft:
    final_ids = _known_final_choice_ids() | _active_spell_replacement_choice_ids(draft, registry)
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
    return (
        len(selected) == 1
        and registry.get_optional(selected[0]) is not None
        and registry.get(selected[0]).name == "Tiger"
    )


def _compile_conditional_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[tuple[BuilderChoice, ...], tuple[BuilderIssue, ...], tuple[ConditionalGrant, ...], set[str]]:
    class_levels, selected_subclasses = _class_state(draft)
    known_skills = _draft_skill_refs(draft, registry)
    known_spells = _draft_spell_refs(draft, registry)
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

    illusion_class_ref = "srd5.1:class:wizard"
    illusion_ref = "phb2014:subclass:illusion"
    if (
        selected_subclasses.get(illusion_class_ref) == illusion_ref
        and class_levels[illusion_class_ref] >= 2
    ):
        minor_illusion = "srd5.1:spell:minor-illusion"
        if minor_illusion not in known_spells:
            grants.append(
                ConditionalGrant(
                    "spell",
                    (minor_illusion,),
                    source_ref=illusion_ref,
                    access_type="granted",
                )
            )
        else:
            choice_id = m01j_choice_id(
                illusion_ref,
                "improved-minor-illusion-fallback-cantrip",
            )
            active_ids.add(choice_id)
            refs = tuple(
                spell.key
                for spell in registry.list_kind("spell")
                if spell.data.get("level") == 0
                and spell.key not in known_spells
                and _spell_on_class_list(registry, spell, illusion_class_ref)
            )
            refs = tuple(sorted(dict.fromkeys(refs)))
            selected = _selection(draft, choice_id)
            choices.append(
                BuilderChoice(
                    choice_id=choice_id,
                    label="Improved Minor Illusion — bonus Wizard cantrip",
                    source_ref=illusion_ref,
                    required=True,
                    choose_count=1,
                    option_source="content:m01-j-conditional-grant",
                    options=_choice_options(registry, refs, "spell"),
                    selected_option_ids=selected,
                )
            )
            if len(selected) != 1 or selected[0] not in refs:
                issues.append(
                    _issue(
                        "invalid_improved_minor_illusion_cantrip",
                        f"draft_payload.choice_selections.{choice_id}",
                        "Improved Minor Illusion requires one different Wizard cantrip when Minor Illusion is already known.",
                        *selected,
                    )
                )
            else:
                grants.append(
                    ConditionalGrant(
                        "spell",
                        selected,
                        source_ref=illusion_ref,
                        access_type="granted",
                    )
                )

    return tuple(choices), tuple(issues), tuple(grants), active_ids


def prepare_m01j_subclasses(draft: BuilderDraft, registry: ContentRegistry) -> M01JSubclassRuntime:
    base = _extension.prepare_m01j_subclasses(
        _draft_without_final_choices(draft, registry),
        registry,
    )
    conditional_choices, conditional_issues, grants, active_final_ids = _compile_conditional_choices(
        draft,
        registry,
    )
    replacement_choices, replacement_issues, replacements, active_replacement_ids = (
        _compile_spell_replacement_choices(draft, registry)
    )
    issues = list(base.issues)
    # The extension saw final-runtime selections removed, so it cannot identify
    # stale static conditional selections. Dynamic replacement selections that
    # are inactive are intentionally left visible to the extension so its
    # generic stale-M01-J validation catches them.
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
    issues.extend(replacement_issues)
    return M01JSubclassRuntime(
        base=base,
        registry=base.registry,
        choices=tuple((*base.choices, *conditional_choices, *replacement_choices)),
        issues=tuple(issues),
        conditional_grants=grants,
        spell_replacements=replacements,
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


def _conditional_spell_entry_id(
    subclass_ref: str,
    spell_ref: str,
    access_type: str,
) -> str:
    subclass = parse_stable_key(subclass_ref, kinds={"subclass"})
    spell = parse_stable_key(spell_ref, kinds={"spell"})
    digest = sha1(
        f"conditional|{subclass_ref}|{spell_ref}|{access_type}".encode("utf-8")
    ).hexdigest()[:10]
    return f"m01j:{subclass.source}:{subclass.index}:{access_type}:{spell.index}:{digest}"[:120]


def _append_conditional_spell(
    spell_entries: dict[str, SpellAccessEntry],
    *,
    subclass_ref: str,
    spell_ref: str,
    access_type: str,
) -> None:
    entry = SpellAccessEntry(
        entry_id=_conditional_spell_entry_id(subclass_ref, spell_ref, access_type),
        spell_key=spell_ref,
        source_type="subclass",
        source_key=subclass_ref,
        access_type=access_type,
    )
    spell_entries[entry.entry_id] = entry


def apply_m01j_subclass_runtime(
    build: CharacterBuild,
    runtime: M01JSubclassRuntime,
) -> CharacterBuild:
    build = _extension.apply_m01j_subclass_runtime(build, runtime.base)
    skills = list(build.skill_choices)
    saves = list(build.saving_throw_proficiencies)
    spell_entries = {entry.entry_id: entry for entry in build.spell_access_entries}
    for grant in runtime.conditional_grants:
        if grant.target == "skill":
            skills.extend(grant.refs)
        elif grant.target == "saving_throw":
            saves.extend(grant.refs)
        elif grant.target == "spell" and grant.source_ref is not None:
            for spell_ref in grant.refs:
                _append_conditional_spell(
                    spell_entries,
                    subclass_ref=grant.source_ref,
                    spell_ref=spell_ref,
                    access_type=grant.access_type or "granted",
                )

    for replacement in runtime.spell_replacements:
        remove_ids = [
            entry_id
            for entry_id, entry in spell_entries.items()
            if entry.source_type == "subclass"
            and entry.source_key == replacement.subclass_ref
            and entry.spell_key == replacement.original_spell_ref
            and entry.access_type == replacement.access_type
        ]
        for entry_id in remove_ids:
            spell_entries.pop(entry_id, None)
        _append_conditional_spell(
            spell_entries,
            subclass_ref=replacement.subclass_ref,
            spell_ref=replacement.replacement_spell_ref,
            access_type=replacement.access_type,
        )

    return build.model_copy(
        update={
            "feature_refs": _apply_branch_progression(build, runtime.registry),
            "skill_choices": tuple(dict.fromkeys(skills)),
            "saving_throw_proficiencies": tuple(dict.fromkeys(saves)),
            "spell_access_entries": tuple(spell_entries.values()),
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
