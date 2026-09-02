from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlparse

from app.content.identity import (
    URL_ROUTE_TO_KIND,
    parse_stable_key,
    reference_to_stable_key,
    stable_key,
    stable_key_is_kind,
)
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import SubclassSelection
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.multiclass import (
    multiclass_failure_detail,
    multiclass_failure_reason,
    multiclass_option_failure_detail,
    multiclass_option_failure_reason,
    multiclass_proficiencies,
    multiclass_proficiency_choices,
)
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderGrantSummary,
    BuilderHPMethod,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderOptionKind,
    BuilderProgressionNodeSummary,
)


@dataclass(frozen=True)
class ProgressionCompilation:
    class_progression: tuple[str, ...]
    hp_progression: tuple[int, ...]
    subclasses: tuple[SubclassSelection, ...]
    proficiencies: tuple[str, ...]
    saving_throw_proficiencies: tuple[str, ...]
    skill_choices: tuple[str, ...]
    feature_refs: tuple[str, ...]


def _stable_key(reference: dict[str, object]) -> str | None:
    return reference_to_stable_key(reference)


def _entry_label(entry: ContentEntry) -> str:
    return f"{entry.name} · {entry.source_label or entry.source}"


def _class_hit_die(class_entry: ContentEntry) -> int:
    raw = class_entry.data.get("hit_die")
    return raw if isinstance(raw, int) and raw > 0 else 1


def fixed_hp_gain(class_entry: ContentEntry) -> int:
    return (_class_hit_die(class_entry) // 2) + 1


def _subclass_parent_ref(subclass_entry: ContentEntry) -> str | None:
    parent = subclass_entry.data.get("class")
    return _stable_key(parent) if isinstance(parent, dict) else None


def _class_subclass_refs(class_entry: ContentEntry) -> tuple[str, ...]:
    raw = class_entry.data.get("subclasses")
    if not isinstance(raw, list):
        return ()
    refs: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            key = _stable_key(item)
            if key is not None:
                refs.append(key)
    return tuple(refs)


def _selected_subclass_refs(draft: BuilderDraft) -> dict[str, str]:
    """Resolve each class's sparse subclass selection for later class levels.

    Builder level rows intentionally store ``subclass_ref`` only on the class
    level where the subclass is selected. Later class levels must still inherit
    that identity so their subclass progression rows can grant features and
    presentation metadata. Validation separately rejects duplicate, early, or
    wrong-parent selections; this helper only provides deterministic carry-forward.
    """

    selected: dict[str, str] = {}
    for level_choice in draft.draft_payload.level_choices:
        if level_choice.subclass_ref is not None:
            selected.setdefault(level_choice.class_ref, level_choice.subclass_ref)
    return selected


def _active_subclass_ref(
    class_entry: ContentEntry,
    class_level: int,
    selected_subclasses: dict[str, str],
    registry: ContentRegistry,
) -> str | None:
    subclass_ref = selected_subclasses.get(class_entry.key)
    if subclass_ref is None:
        return None
    timing = subclass_selection_level(class_entry, registry)
    if timing is None or class_level < timing:
        return None
    subclass_entry = registry.get_optional(subclass_ref)
    if (
        subclass_entry is None
        or not stable_key_is_kind(subclass_entry.key, "subclass")
        or _subclass_parent_ref(subclass_entry) != class_entry.key
    ):
        return None
    return subclass_ref


def _level_ref(source_ref: str, level: int) -> str:
    parsed = parse_stable_key(source_ref)
    return stable_key(parsed.source, "level", f"{parsed.index}-{level}")


def subclass_selection_level(class_entry: ContentEntry, registry: ContentRegistry) -> int | None:
    timings: list[int] = []
    for subclass_ref in _class_subclass_refs(class_entry):
        for level in range(1, 21):
            level_entry = registry.get_optional(_level_ref(subclass_ref, level))
            if level_entry is None:
                continue
            parent = level_entry.data.get("subclass")
            if not isinstance(parent, dict) or _stable_key(parent) != subclass_ref:
                continue
            timings.append(level)
            break
    return min(timings) if timings else None


def _level_features(
    registry: ContentRegistry,
    source_ref: str,
    level: int,
    *,
    subclass: bool = False,
) -> tuple[str, ...]:
    entry = registry.get_optional(_level_ref(source_ref, level))
    if entry is None:
        return ()
    parent_field = "subclass" if subclass else "class"
    parent = entry.data.get(parent_field)
    if not isinstance(parent, dict) or _stable_key(parent) != source_ref:
        return ()
    raw = entry.data.get("features")
    if not isinstance(raw, list):
        return ()
    result: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            key = _stable_key(item)
            if key is not None and stable_key_is_kind(key, "feature"):
                result.append(key)
    return tuple(result)


def _effective_abilities(draft: BuilderDraft, grants: tuple[BuilderGrantSummary, ...] = ()) -> dict[str, int] | None:
    generation = draft.draft_payload.ability_generation
    if generation is None:
        return None
    values = generation.scores.as_dict()
    override_map = {
        override.key.removeprefix("ability:"): int(override.value)
        for override in draft.draft_payload.numeric_overrides
        if override.key.startswith("ability:") and float(override.value).is_integer()
    }
    return {ability: override_map.get(ability, value) for ability, value in values.items()}


def _reference_options(rule: dict[str, object], registry: ContentRegistry) -> tuple[BuilderChoiceOption, ...]:
    source = rule.get("from")
    if not isinstance(source, dict):
        return ()
    source_type = source.get("option_set_type")
    if source_type == "resource_list":
        resource_url = source.get("resource_list_url")
        if not isinstance(resource_url, str):
            return ()
        parts = [part for part in urlparse(resource_url).path.split("/") if part]
        if len(parts) != 3 or parts[0:2] != ["api", "2014"]:
            return ()
        kind = URL_ROUTE_TO_KIND.get(parts[2])
        if kind is None:
            return ()
        return tuple(
            BuilderChoiceOption(
                option_id=entry.key,
                label=_entry_label(entry),
                kind=BuilderOptionKind.REFERENCE,
                reference_id=entry.key,
            )
            for entry in registry.list_kind(kind, source="srd5.1")
        )

    raw_options = source.get("options")
    if source_type != "options_array" or not isinstance(raw_options, list):
        return ()
    result: list[BuilderChoiceOption] = []
    for raw in raw_options:
        if not isinstance(raw, dict):
            continue
        option_type = raw.get("option_type")
        if option_type == "choice":
            nested = raw.get("choice")
            if not isinstance(nested, dict):
                continue
            nested_choose = nested.get("choose", 1)
            if nested_choose != 1:
                continue
            result.extend(_reference_options(nested, registry))
            continue
        if option_type != "reference":
            continue
        item = raw.get("item")
        if not isinstance(item, dict):
            continue
        key = _stable_key(item)
        name = item.get("name")
        if key is not None and isinstance(name, str):
            target = registry.get_optional(key)
            result.append(
                BuilderChoiceOption(
                    option_id=key,
                    label=_entry_label(target) if target is not None else name,
                    kind=BuilderOptionKind.REFERENCE,
                    reference_id=key,
                )
            )
    return tuple(dict.fromkeys((option.option_id, option) for option in result).values())


def _proficiency_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    class_entry: ContentEntry,
    character_level: int,
    rules: tuple[dict[str, object], ...],
    grant_kind: str,
) -> tuple[BuilderChoice, ...]:
    result: list[BuilderChoice] = []
    for occurrence, rule in enumerate(rules):
        choose = rule.get("choose")
        choose_count = choose if isinstance(choose, int) and choose >= 0 else 1
        choice_id = deterministic_choice_id(
            "level",
            str(character_level),
            class_entry.key,
            grant_kind,
            str(occurrence),
        )
        selection = draft.draft_payload.choice_selections.get(choice_id)
        desc = rule.get("desc")
        label = desc if isinstance(desc, str) and desc.strip() else "Proficiency choice"
        result.append(
            BuilderChoice(
                choice_id=choice_id,
                label=f"{class_entry.name} — {label}",
                source_ref=class_entry.key,
                required=True,
                choose_count=choose_count,
                option_source="content:class-proficiency",
                options=_reference_options(rule, registry),
                selected_option_ids=selection.selected_option_ids if selection is not None else (),
            )
        )
    return tuple(result)


def build_progression_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[BuilderChoice, ...]:
    payload = draft.draft_payload
    if payload.target_level is None:
        return ()

    effective = _effective_abilities(draft)
    class_entries = registry.list_kind("class")
    choices: list[BuilderChoice] = []
    acquired: list[ContentEntry] = []
    class_counts: Counter[str] = Counter()
    first_acquisition_level: dict[str, int] = {}

    for character_level in range(1, payload.target_level + 1):
        saved = payload.level_choices[character_level - 1] if character_level <= len(payload.level_choices) else None
        options: list[BuilderChoiceOption] = []
        acquired_unique = tuple(dict.fromkeys(entry.key for entry in acquired))
        acquired_entries = tuple(registry.get(key) for key in acquired_unique)
        for class_entry in class_entries:
            disabled_reason = None
            disabled_reason_code = None
            disabled_reason_params: dict[str, object] = {}
            if character_level > 1:
                detail = multiclass_option_failure_detail(
                    class_entry,
                    acquired_entries,
                    effective,
                )
                if detail is not None:
                    disabled_reason_code = detail.code
                    disabled_reason_params = detail.params
                    disabled_reason = multiclass_option_failure_reason(
                        class_entry,
                        acquired_entries,
                        effective,
                    )
            options.append(
                BuilderChoiceOption(
                    option_id=class_entry.key,
                    label=_entry_label(class_entry),
                    kind=BuilderOptionKind.REFERENCE,
                    reference_id=class_entry.key,
                    disabled_reason=disabled_reason,
                    disabled_reason_code=disabled_reason_code,
                    disabled_reason_params=disabled_reason_params,
                    hit_die_size=_class_hit_die(class_entry),
                    fixed_hp_gain=fixed_hp_gain(class_entry),
                )
            )
        choices.append(
            BuilderChoice(
                choice_id=deterministic_choice_id("level", str(character_level), "class-selection"),
                label=f"Level {character_level} class",
                required=True,
                choose_count=1,
                option_source="content:class",
                options=tuple(options),
                selected_option_ids=((saved.class_ref,) if saved is not None else ()),
            )
        )

        if saved is None:
            continue
        class_entry = registry.get_optional(saved.class_ref)
        if class_entry is None or not stable_key_is_kind(class_entry.key, "class"):
            continue
        class_counts[class_entry.key] += 1
        class_level = class_counts[class_entry.key]
        first_for_class = class_entry.key not in first_acquisition_level
        if first_for_class:
            first_acquisition_level[class_entry.key] = character_level

        timing = subclass_selection_level(class_entry, registry)
        if timing is not None and class_level == timing:
            subclass_options = tuple(
                BuilderChoiceOption(
                    option_id=key,
                    label=_entry_label(registry.get(key)),
                    kind=BuilderOptionKind.REFERENCE,
                    reference_id=key,
                )
                for key in _class_subclass_refs(class_entry)
                if registry.get_optional(key) is not None
            )
            choices.append(
                BuilderChoice(
                    choice_id=deterministic_choice_id("level", str(character_level), "subclass-selection"),
                    label=f"{class_entry.name} subclass",
                    source_ref=class_entry.key,
                    required=True,
                    choose_count=1,
                    option_source="content:subclass",
                    options=subclass_options,
                    selected_option_ids=((saved.subclass_ref,) if saved.subclass_ref is not None else ()),
                )
            )

        if character_level == 1:
            raw = class_entry.data.get("proficiency_choices")
            rules = tuple(item for item in raw if isinstance(item, dict)) if isinstance(raw, list) else ()
            choices.extend(
                _proficiency_choices(
                    draft,
                    registry,
                    class_entry=class_entry,
                    character_level=character_level,
                    rules=rules,
                    grant_kind="starting-proficiency",
                )
            )
        elif first_for_class:
            choices.extend(
                _proficiency_choices(
                    draft,
                    registry,
                    class_entry=class_entry,
                    character_level=character_level,
                    rules=multiclass_proficiency_choices(class_entry),
                    grant_kind="multiclass-proficiency",
                )
            )
        acquired.append(class_entry)

    return tuple(choices)


def validate_progression(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    effective_abilities: dict[str, int] | None,
) -> tuple[BuilderIssue, ...]:
    payload = draft.draft_payload
    issues: list[BuilderIssue] = []
    if payload.target_level is None:
        return ()
    if len(payload.level_choices) != payload.target_level:
        return (
            BuilderIssue(
                code="incomplete_level_progression",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="draft_payload.level_choices",
                message=(
                    "Level choices must contain one ordered entry per target level "
                    f"(expected {payload.target_level}, got {len(payload.level_choices)})."
                ),
                message_params={
                    "expected_level_count": payload.target_level,
                    "actual_level_count": len(payload.level_choices),
                },
            ),
        )

    class_counts: Counter[str] = Counter()
    distinct_class_entries: list[ContentEntry] = []
    seen_classes: set[str] = set()
    subclass_records: dict[str, list[tuple[int, int, str]]] = {}

    for index, level_choice in enumerate(payload.level_choices):
        expected_character_level = index + 1
        path = f"draft_payload.level_choices.{index}"
        if level_choice.character_level != expected_character_level:
            issues.append(
                BuilderIssue(
                    code="unordered_character_level",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"{path}.character_level",
                    message=f"Progression node {index + 1} must represent Character Level {expected_character_level}.",
                    message_params={
                        "progression_index": index + 1,
                        "expected_character_level": expected_character_level,
                        "actual_character_level": level_choice.character_level,
                    },
                )
            )
        class_entry = registry.get_optional(level_choice.class_ref)
        if class_entry is None or not stable_key_is_kind(class_entry.key, "class"):
            issues.append(
                BuilderIssue(
                    code="invalid_class_reference",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"{path}.class_ref",
                    message=f"Unknown class reference: {level_choice.class_ref}",
                    message_params={"class_ref": level_choice.class_ref},
                    related_refs=(level_choice.class_ref,),
                )
            )
            continue
        if class_entry.key not in seen_classes:
            seen_classes.add(class_entry.key)
            distinct_class_entries.append(class_entry)
        class_counts[class_entry.key] += 1
        class_level = class_counts[class_entry.key]
        hit_die = _class_hit_die(class_entry)

        if expected_character_level == 1:
            if level_choice.hp_method is not BuilderHPMethod.FIRST_LEVEL or level_choice.hp_base_gain != hit_die:
                issues.append(
                    BuilderIssue(
                        code="invalid_first_level_hp",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path=f"{path}.hp_method",
                        message=f"Character Level 1 must use the starting class maximum hit die ({hit_die}).",
                        message_params={"class_ref": class_entry.key, "hit_die_size": hit_die},
                        related_refs=(class_entry.key,),
                    )
                )
        elif level_choice.hp_method is BuilderHPMethod.FIRST_LEVEL:
            issues.append(
                BuilderIssue(
                    code="first_level_hp_only_at_character_level_one",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"{path}.hp_method",
                    message="The first-level maximum HP rule only applies at Character Level 1.",
                    message_params={"class_ref": class_entry.key, "character_level": expected_character_level},
                    related_refs=(class_entry.key,),
                )
            )
        elif level_choice.hp_method is BuilderHPMethod.FIXED_AVERAGE:
            expected = fixed_hp_gain(class_entry)
            if level_choice.hp_base_gain != expected:
                issues.append(
                    BuilderIssue(
                        code="invalid_fixed_hp_gain",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path=f"{path}.hp_base_gain",
                        message=f"{class_entry.name} fixed HP gain must be {expected}.",
                        message_params={"class_ref": class_entry.key, "expected_hp_gain": expected},
                        related_refs=(class_entry.key,),
                    )
                )
        elif level_choice.hp_method is BuilderHPMethod.MANUAL_ROLLED:
            if level_choice.hp_base_gain > hit_die:
                issues.append(
                    BuilderIssue(
                        code="invalid_manual_hp_roll",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path=f"{path}.hp_base_gain",
                        message=f"Manual HP for {class_entry.name} must be between 1 and {hit_die}.",
                        message_params={"class_ref": class_entry.key, "minimum": 1, "maximum": hit_die},
                        related_refs=(class_entry.key,),
                    )
                )

        if level_choice.subclass_ref is not None:
            subclass_entry = registry.get_optional(level_choice.subclass_ref)
            if subclass_entry is None or not stable_key_is_kind(subclass_entry.key, "subclass"):
                issues.append(
                    BuilderIssue(
                        code="invalid_subclass_reference",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path=f"{path}.subclass_ref",
                        message=f"Unknown subclass reference: {level_choice.subclass_ref}",
                        message_params={"subclass_ref": level_choice.subclass_ref},
                        related_refs=(level_choice.subclass_ref,),
                    )
                )
            elif _subclass_parent_ref(subclass_entry) != class_entry.key:
                issues.append(
                    BuilderIssue(
                        code="subclass_class_mismatch",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path=f"{path}.subclass_ref",
                        message=f"{subclass_entry.name} does not belong to {class_entry.name}.",
                        message_params={
                            "class_ref": class_entry.key,
                            "subclass_ref": subclass_entry.key,
                        },
                        related_refs=(class_entry.key, subclass_entry.key),
                    )
                )
            else:
                subclass_records.setdefault(class_entry.key, []).append(
                    (expected_character_level, class_level, subclass_entry.key)
                )

    if len(distinct_class_entries) > 1:
        for class_entry in distinct_class_entries:
            detail = multiclass_failure_detail(class_entry, effective_abilities)
            if detail is not None:
                reason = multiclass_failure_reason(class_entry, effective_abilities)
                issues.append(
                    BuilderIssue(
                        code="multiclass_prerequisite_not_met",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path="draft_payload.level_choices",
                        message=f"{class_entry.name}: {reason}",
                        message_params=detail.params,
                        related_refs=(class_entry.key,),
                    )
                )

    for class_entry in distinct_class_entries:
        timing = subclass_selection_level(class_entry, registry)
        if timing is None:
            continue
        reached_level = class_counts[class_entry.key]
        records = subclass_records.get(class_entry.key, [])
        if reached_level < timing:
            if records:
                issues.append(
                    BuilderIssue(
                        code="subclass_selected_too_early",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path="draft_payload.level_choices",
                        message=f"{class_entry.name} subclass cannot be selected before class level {timing}.",
                        message_params={"class_ref": class_entry.key, "required_class_level": timing},
                        related_refs=(class_entry.key,),
                    )
                )
            continue
        if not records:
            issues.append(
                BuilderIssue(
                    code="missing_subclass_at_timing",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="draft_payload.level_choices",
                    message=f"{class_entry.name} requires a subclass selection at class level {timing}.",
                    message_params={"class_ref": class_entry.key, "required_class_level": timing},
                    related_refs=(class_entry.key,),
                )
            )
            continue
        selected_refs = {record[2] for record in records}
        if len(selected_refs) != 1 or len(records) != 1:
            issues.append(
                BuilderIssue(
                    code="duplicate_subclass_selection",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="draft_payload.level_choices",
                    message=f"{class_entry.name} must have exactly one subclass selection.",
                    message_params={"class_ref": class_entry.key, "subclass_refs": sorted(selected_refs)},
                    related_refs=tuple(sorted(selected_refs)),
                )
            )
        elif records[0][1] != timing:
            issues.append(
                BuilderIssue(
                    code="subclass_selected_at_wrong_level",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="draft_payload.level_choices",
                    message=f"{class_entry.name} subclass must be selected at class level {timing}.",
                    message_params={
                        "class_ref": class_entry.key,
                        "subclass_ref": records[0][2],
                        "required_class_level": timing,
                        "actual_class_level": records[0][1],
                    },
                    related_refs=(records[0][2],),
                )
            )

    return tuple(issues)


def progression_summary(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[BuilderProgressionNodeSummary, ...]:
    class_counts: Counter[str] = Counter()
    first_acquired: set[str] = set()
    selected_subclasses = _selected_subclass_refs(draft)
    result: list[BuilderProgressionNodeSummary] = []
    for index, level_choice in enumerate(draft.draft_payload.level_choices):
        class_entry = registry.get_optional(level_choice.class_ref)
        if class_entry is None or not stable_key_is_kind(class_entry.key, "class"):
            continue
        class_counts[class_entry.key] += 1
        class_level = class_counts[class_entry.key]
        first_for_class = class_entry.key not in first_acquired
        first_acquired.add(class_entry.key)
        timing = subclass_selection_level(class_entry, registry)
        active_subclass_ref = _active_subclass_ref(
            class_entry,
            class_level,
            selected_subclasses,
            registry,
        )
        subclass_name = None
        if active_subclass_ref is not None:
            subclass = registry.get_optional(active_subclass_ref)
            subclass_name = subclass.name if subclass is not None else None
        features = list(_level_features(registry, class_entry.key, class_level))
        if active_subclass_ref is not None:
            features.extend(
                _level_features(
                    registry,
                    active_subclass_ref,
                    class_level,
                    subclass=True,
                )
            )
        result.append(
            BuilderProgressionNodeSummary(
                character_level=index + 1,
                class_ref=class_entry.key,
                class_name=class_entry.name,
                class_level=class_level,
                starting_class=index == 0,
                multiclass_entry=index > 0 and first_for_class,
                hit_die_size=_class_hit_die(class_entry),
                fixed_hp_gain=fixed_hp_gain(class_entry),
                hp_method=level_choice.hp_method,
                hp_base_gain=level_choice.hp_base_gain,
                subclass_required=timing is not None and class_level == timing,
                subclass_ref=active_subclass_ref,
                subclass_name=subclass_name,
                automatic_feature_refs=tuple(dict.fromkeys(features)),
            )
        )
    return tuple(result)


def class_summary(nodes: tuple[BuilderProgressionNodeSummary, ...]) -> str | None:
    if not nodes:
        return None
    counts = Counter(node.class_ref for node in nodes)
    names = {node.class_ref: node.class_name for node in nodes}
    order = tuple(dict.fromkeys(node.class_ref for node in nodes))
    return " / ".join(f"{names[key]} {counts[key]}" for key in order)


def _skill_key_from_proficiency(key: str, registry: ContentRegistry) -> str | None:
    parsed = parse_stable_key(key)
    if parsed.kind != "proficiency" or not parsed.index.startswith("skill-"):
        return None
    skill_key = stable_key(parsed.source, "skill", parsed.index.removeprefix("skill-"))
    return skill_key if registry.get_optional(skill_key) is not None else None


def _append_reference(
    reference: dict[str, object],
    *,
    proficiencies: list[str],
    skills: list[str],
    registry: ContentRegistry,
) -> None:
    key = _stable_key(reference)
    if key is None or not stable_key_is_kind(key, "proficiency"):
        return
    skill_key = _skill_key_from_proficiency(key, registry)
    if skill_key is not None:
        skills.append(skill_key)
        return
    proficiencies.append(key)


def compile_progression(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    grants: tuple[BuilderGrantSummary, ...],
    choices: tuple[BuilderChoice, ...],
) -> ProgressionCompilation:
    payload = draft.draft_payload
    class_progression = tuple(level.class_ref for level in payload.level_choices)
    hp_progression = tuple(level.hp_base_gain for level in payload.level_choices)
    proficiencies: list[str] = []
    skills: list[str] = []
    saves: list[str] = []
    features: list[str] = []
    subclasses: list[SubclassSelection] = []

    for grant in grants:
        if grant.reference_id is None or not stable_key_is_kind(grant.reference_id, "proficiency"):
            continue
        skill_key = _skill_key_from_proficiency(grant.reference_id, registry)
        if skill_key is not None:
            skills.append(skill_key)
            continue
        proficiencies.append(grant.reference_id)

    class_counts: Counter[str] = Counter()
    acquired_classes: set[str] = set()
    selected_subclasses = _selected_subclass_refs(draft)
    for index, level_choice in enumerate(payload.level_choices):
        class_entry = registry.get(level_choice.class_ref)
        class_counts[class_entry.key] += 1
        class_level = class_counts[class_entry.key]
        first_for_class = class_entry.key not in acquired_classes

        if index == 0:
            raw_saves = class_entry.data.get("saving_throws")
            save_indexes: set[str] = set()
            if isinstance(raw_saves, list):
                for reference in raw_saves:
                    if not isinstance(reference, dict):
                        continue
                    key = _stable_key(reference)
                    if key is not None and stable_key_is_kind(key, "ability"):
                        saves.append(key)
                        parsed = parse_stable_key(key)
                        save_indexes.add(parsed.index)
            raw_proficiencies = class_entry.data.get("proficiencies")
            if isinstance(raw_proficiencies, list):
                for reference in raw_proficiencies:
                    if not isinstance(reference, dict):
                        continue
                    proficiency_index = reference.get("index")
                    if isinstance(proficiency_index, str) and any(
                        proficiency_index == f"saving-throw-{save_index}" for save_index in save_indexes
                    ):
                        continue
                    _append_reference(
                        reference,
                        proficiencies=proficiencies,
                        skills=skills,
                        registry=registry,
                    )
        elif first_for_class:
            for reference in multiclass_proficiencies(class_entry):
                _append_reference(
                    reference,
                    proficiencies=proficiencies,
                    skills=skills,
                    registry=registry,
                )

        features.extend(_level_features(registry, class_entry.key, class_level))
        active_subclass_ref = _active_subclass_ref(
            class_entry,
            class_level,
            selected_subclasses,
            registry,
        )
        if active_subclass_ref is not None:
            features.extend(
                _level_features(
                    registry,
                    active_subclass_ref,
                    class_level,
                    subclass=True,
                )
            )
            timing = subclass_selection_level(class_entry, registry)
            if timing == class_level:
                subclasses.append(
                    SubclassSelection(
                        class_ref=class_entry.key,
                        subclass_ref=active_subclass_ref,
                    )
                )
        acquired_classes.add(class_entry.key)

    choice_by_id = {choice.choice_id: choice for choice in choices}
    for choice_id, selection in payload.choice_selections.items():
        choice = choice_by_id.get(choice_id)
        if choice is None or choice.option_source != "content:class-proficiency":
            continue
        option_by_id = {option.option_id: option for option in choice.options}
        for selected_id in selection.selected_option_ids:
            option = option_by_id.get(selected_id)
            if option is None or option.reference_id is None:
                continue
            reference_id = option.reference_id
            if not stable_key_is_kind(reference_id, "proficiency"):
                continue
            skill_key = _skill_key_from_proficiency(reference_id, registry)
            if skill_key is not None:
                skills.append(skill_key)
                continue
            proficiencies.append(reference_id)

    return ProgressionCompilation(
        class_progression=class_progression,
        hp_progression=hp_progression,
        subclasses=tuple(dict.fromkeys(subclasses)),
        proficiencies=tuple(dict.fromkeys(proficiencies)),
        saving_throw_proficiencies=tuple(dict.fromkeys(saves)),
        skill_choices=tuple(dict.fromkeys(skills)),
        feature_refs=tuple(dict.fromkeys(features)),
    )
