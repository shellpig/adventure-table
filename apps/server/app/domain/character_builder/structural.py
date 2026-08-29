from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlparse

from app.content.registry import ContentRegistry, URL_ROUTE_TO_KIND
from app.content.schemas import ContentEntry
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.progression import progression_summary
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderOptionKind,
)


ABILITY_INDEX_TO_NAME = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}
ABILITY_NAME_TO_INDEX = {value: key for key, value in ABILITY_INDEX_TO_NAME.items()}
ABILITY_LABELS = {
    "strength": "STR",
    "dexterity": "DEX",
    "constitution": "CON",
    "intelligence": "INT",
    "wisdom": "WIS",
    "charisma": "CHA",
}
ASI_CAP = 20

# The imported 5e SRD level feed contains one known cumulative-counter anomaly:
# Rogue 10 is 3, Rogue 11 is shipped as 2, and Rogue 12 continues at 4. P1-D
# consumes ability_score_bonuses as a cumulative counter, so normalize that
# upstream row explicitly. Every other decrease still fails fast below.
KNOWN_ASI_SOURCE_CORRECTIONS: dict[str, tuple[int, int]] = {
    "srd5.1:level:rogue-11": (2, 3),
}


@dataclass(frozen=True)
class StructuralCompilation:
    ability_bonuses: dict[str, int]
    feat_refs: tuple[str, ...]
    feature_refs: tuple[str, ...]
    proficiencies: tuple[str, ...]
    skill_choices: tuple[str, ...]


def _stable_key(reference: dict[str, object]) -> str | None:
    index = reference.get("index")
    url = reference.get("url")
    if not isinstance(index, str) or not isinstance(url, str):
        return None
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) != 4 or parts[0:2] != ["api", "2014"]:
        return None
    kind = URL_ROUTE_TO_KIND.get(parts[2])
    if kind is None or parts[3] != index:
        return None
    return f"srd5.1:{kind}:{index}"


def _class_level_entry(
    registry: ContentRegistry,
    class_entry: ContentEntry,
    class_level: int,
) -> ContentEntry:
    class_index = class_entry.key.rsplit(":", 1)[-1]
    entry = registry.get_optional(f"srd5.1:level:{class_index}-{class_level}")
    if entry is None:
        raise ValueError(f"Missing level rules for {class_entry.key} class level {class_level}")
    parent = entry.data.get("class")
    if not isinstance(parent, dict) or parent.get("index") != class_index:
        raise ValueError(f"Invalid level rules parent for {class_entry.key} class level {class_level}")
    return entry


def _cumulative_asi(entry: ContentEntry) -> int:
    value = entry.data.get("ability_score_bonuses")
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"Invalid ability_score_bonuses in {entry.key}")
    correction = KNOWN_ASI_SOURCE_CORRECTIONS.get(entry.key)
    if correction is None:
        return value
    source_value, normalized_value = correction
    if value == normalized_value:
        return value
    if value != source_value:
        raise ValueError(
            f"Known ASI source correction no longer matches {entry.key}: {value}"
        )
    return normalized_value


def _asi_feature_markers(entry: ContentEntry) -> int:
    raw = entry.data.get("features")
    if not isinstance(raw, list):
        return 0
    count = 0
    for reference in raw:
        if not isinstance(reference, dict):
            continue
        index = reference.get("index")
        name = reference.get("name")
        normalized_index = index.lower() if isinstance(index, str) else ""
        normalized_name = name.lower() if isinstance(name, str) else ""
        if (
            "ability-score-improvement" in normalized_index
            or normalized_name == "ability score improvement"
        ):
            count += 1
    return count


def asi_occurrences_at_class_level(
    registry: ContentRegistry,
    class_ref: str,
    class_level: int,
) -> int:
    class_entry = registry.get_optional(class_ref)
    if class_entry is None or not class_entry.key.startswith("srd5.1:class:"):
        raise ValueError(f"Unknown class reference: {class_ref}")
    current_entry = _class_level_entry(registry, class_entry, class_level)
    current = _cumulative_asi(current_entry)
    previous = 0
    if class_level > 1:
        previous = _cumulative_asi(
            _class_level_entry(registry, class_entry, class_level - 1)
        )
    delta = current - previous
    if delta < 0:
        raise ValueError(
            f"ability_score_bonuses decreased for {class_ref} at class level {class_level}"
        )

    markers = _asi_feature_markers(current_entry)
    if markers and markers != delta:
        raise ValueError(
            "ASI feature markers disagree with cumulative delta for "
            f"{class_ref} class level {class_level}"
        )
    return delta


def _numeric_override_map(draft: BuilderDraft) -> dict[str, int]:
    result: dict[str, int] = {}
    for override in draft.draft_payload.numeric_overrides:
        if not override.key.startswith("ability:") or not float(override.value).is_integer():
            continue
        ability = override.key.removeprefix("ability:")
        if ability in ABILITY_NAME_TO_INDEX:
            result[ability] = int(override.value)
    return result


def _effective_abilities(
    resolved: dict[str, int] | None,
    overrides: dict[str, int],
) -> dict[str, int] | None:
    if resolved is None:
        return None
    return {ability: overrides.get(ability, score) for ability, score in resolved.items()}


def feat_failure_reason(
    feat_entry: ContentEntry,
    effective_abilities: dict[str, int] | None,
) -> str | None:
    prerequisites = feat_entry.data.get("prerequisites")
    if not isinstance(prerequisites, list) or not prerequisites:
        return None
    if effective_abilities is None:
        return "Complete ability scores before choosing this feat."

    failures: list[str] = []
    for prerequisite in prerequisites:
        if not isinstance(prerequisite, dict):
            return "This feat has an unsupported prerequisite shape."
        ability_score = prerequisite.get("ability_score")
        minimum = prerequisite.get("minimum_score")
        if not isinstance(ability_score, dict) or not isinstance(minimum, int):
            return "This feat has an unsupported prerequisite shape."
        index = ability_score.get("index")
        ability = ABILITY_INDEX_TO_NAME.get(index) if isinstance(index, str) else None
        if ability is None:
            return "This feat has an unsupported ability prerequisite."
        if effective_abilities.get(ability, 0) < minimum:
            failures.append(f"{ABILITY_LABELS[ability]} {minimum}+")
    return None if not failures else "Requires " + " and ".join(failures) + "."


def _selection(draft: BuilderDraft, choice_id: str) -> tuple[str, ...]:
    record = draft.draft_payload.choice_selections.get(choice_id)
    return record.selected_option_ids if record is not None else ()


def _asi_option_id(branch_id: str) -> str:
    return deterministic_choice_id(branch_id, "asi")


def _ability_option_id(ability: str) -> str:
    return f"ability:{ability}"


def _ability_from_option_id(option_id: str) -> str | None:
    if not option_id.startswith("ability:"):
        return None
    ability = option_id.removeprefix("ability:")
    return ability if ability in ABILITY_NAME_TO_INDEX else None


def _reference_option(
    raw: dict[str, object],
    *,
    kind: BuilderOptionKind = BuilderOptionKind.REFERENCE,
    count: int | None = None,
) -> BuilderChoiceOption | None:
    key = _stable_key(raw)
    name = raw.get("name")
    if key is None or not isinstance(name, str):
        return None
    return BuilderChoiceOption(
        option_id=(f"{key}@{count}" if count is not None else key),
        label=(f"{count} × {name}" if count is not None else name),
        kind=kind,
        reference_id=key,
        count=count,
    )


def _resource_list_options(
    source: dict[str, object],
    registry: ContentRegistry,
) -> tuple[BuilderChoiceOption, ...]:
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
            label=entry.name,
            kind=BuilderOptionKind.CATEGORY_FILTER,
            reference_id=entry.key,
            category=kind,
        )
        for entry in registry.list_kind(kind)
    )


def _canonical_rule_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    source_ref: str,
    choice_id: str,
    label: str,
    rule: dict[str, object],
    option_source: str,
) -> tuple[BuilderChoice, ...]:
    choose = rule.get("choose")
    choose_count = choose if isinstance(choose, int) and choose >= 0 else 1
    source = rule.get("from")
    if not isinstance(source, dict):
        return ()

    if source.get("option_set_type") == "resource_list":
        options = _resource_list_options(source, registry)
        return (
            BuilderChoice(
                choice_id=choice_id,
                label=label,
                source_ref=source_ref,
                required=True,
                choose_count=choose_count,
                option_source=option_source,
                options=options,
                selected_option_ids=_selection(draft, choice_id),
            ),
        )

    raw_options = source.get("options")
    if source.get("option_set_type") != "options_array" or not isinstance(raw_options, list):
        return ()

    options: list[BuilderChoiceOption] = []
    nested_choices: list[BuilderChoice] = []
    selected_parent = _selection(draft, choice_id)
    for index, raw in enumerate(raw_options):
        if not isinstance(raw, dict):
            continue
        option_type = raw.get("option_type")
        if option_type == "reference" and isinstance(raw.get("item"), dict):
            option = _reference_option(raw["item"])
            if option is not None:
                options.append(option)
        elif option_type == "counted_reference":
            reference = raw.get("of") if isinstance(raw.get("of"), dict) else raw.get("item")
            count = raw.get("count")
            if isinstance(reference, dict) and isinstance(count, int) and count > 0:
                option = _reference_option(
                    reference,
                    kind=BuilderOptionKind.COUNTED_REFERENCE,
                    count=count,
                )
                if option is not None:
                    options.append(option)
        elif option_type == "string" and isinstance(raw.get("string"), str):
            text = raw["string"]
            option_id = deterministic_choice_id(choice_id, "option", str(index), text)
            options.append(
                BuilderChoiceOption(
                    option_id=option_id,
                    label=text,
                    kind=BuilderOptionKind.BRANCH,
                    branch_key=option_id,
                )
            )
        elif option_type == "choice" and isinstance(raw.get("choice"), dict):
            nested_id = deterministic_choice_id(choice_id, "nested", str(index))
            option_id = deterministic_choice_id(choice_id, "branch", str(index))
            nested_rule = raw["choice"]
            nested_label = nested_rule.get("desc")
            if not isinstance(nested_label, str) or not nested_label.strip():
                nested_label = f"{label} — nested choice"
            options.append(
                BuilderChoiceOption(
                    option_id=option_id,
                    label=nested_label,
                    kind=BuilderOptionKind.NESTED_CHOICE,
                    nested_choice_id=nested_id,
                    branch_key=option_id,
                )
            )
            children = _canonical_rule_choices(
                draft,
                registry,
                source_ref=source_ref,
                choice_id=nested_id,
                label=nested_label,
                rule=nested_rule,
                option_source=f"{option_source}:nested",
            )
            active = option_id in selected_parent
            nested_choices.extend(
                child.model_copy(
                    update={
                        "disabled_reason": (
                            child.disabled_reason
                            if active
                            else f"Choose {nested_label} first."
                        )
                    }
                )
                for child in children
            )

    if not options:
        return ()
    return (
        BuilderChoice(
            choice_id=choice_id,
            label=label,
            source_ref=source_ref,
            required=True,
            choose_count=choose_count,
            option_source=option_source,
            options=tuple(options),
            selected_option_ids=selected_parent,
        ),
        *nested_choices,
    )


def _feature_specific_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    feature: ContentEntry,
    character_level: int,
) -> tuple[BuilderChoice, ...]:
    root = feature.data.get("feature_specific")
    if not isinstance(root, dict):
        return ()
    result: list[BuilderChoice] = []

    def walk(value: object, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("choose"), int) and isinstance(value.get("from"), dict):
                field = "-".join(path) if path else "feature-choice"
                desc = value.get("desc")
                label = (
                    desc
                    if isinstance(desc, str) and desc.strip()
                    else f"{feature.name} — choice"
                )
                choice_id = deterministic_choice_id(
                    "level", str(character_level), feature.key, field
                )
                result.extend(
                    _canonical_rule_choices(
                        draft,
                        registry,
                        source_ref=feature.key,
                        choice_id=choice_id,
                        label=label,
                        rule=value,
                        option_source=f"content:feature:{field}",
                    )
                )
                return
            for key, child in value.items():
                walk(child, (*path, str(key)))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, (*path, str(index)))

    walk(root, ("feature-specific",))
    return tuple(result)


def build_structural_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    starting_abilities: dict[str, int] | None,
) -> tuple[BuilderChoice, ...]:
    class_counts: Counter[str] = Counter()
    resolved = dict(starting_abilities) if starting_abilities is not None else None
    overrides = _numeric_override_map(draft)
    feats = registry.list_kind("feat")
    choices: list[BuilderChoice] = []
    nodes = {
        node.character_level: node for node in progression_summary(draft, registry)
    }

    for character_level, level_choice in enumerate(
        draft.draft_payload.level_choices,
        start=1,
    ):
        class_entry = registry.get_optional(level_choice.class_ref)
        if class_entry is None or not class_entry.key.startswith("srd5.1:class:"):
            continue
        class_counts[class_entry.key] += 1
        class_level = class_counts[class_entry.key]
        occurrences = asi_occurrences_at_class_level(
            registry,
            class_entry.key,
            class_level,
        )

        for occurrence in range(occurrences):
            branch_id = deterministic_choice_id(
                "level", str(character_level), "asi-feat", str(occurrence)
            )
            asi_option_id = _asi_option_id(branch_id)
            effective = _effective_abilities(resolved, overrides)
            feat_options = tuple(
                BuilderChoiceOption(
                    option_id=feat.key,
                    label=feat.name,
                    kind=BuilderOptionKind.REFERENCE,
                    reference_id=feat.key,
                    category="feat",
                    disabled_reason=feat_failure_reason(feat, effective),
                )
                for feat in feats
            )
            branch_selection = _selection(draft, branch_id)
            choices.append(
                BuilderChoice(
                    choice_id=branch_id,
                    label=f"{class_entry.name} {class_level} — ASI or Feat",
                    source_ref=class_entry.key,
                    required=True,
                    choose_count=1,
                    option_source="content:asi-feat",
                    options=(
                        BuilderChoiceOption(
                            option_id=asi_option_id,
                            label="Ability Score Improvement",
                            kind=BuilderOptionKind.BRANCH,
                            branch_key="asi",
                        ),
                        *feat_options,
                    ),
                    selected_option_ids=branch_selection,
                )
            )

            ability_id = deterministic_choice_id(
                "level", str(character_level), "asi-abilities", str(occurrence)
            )
            selected_abilities = _selection(draft, ability_id)
            selected_counts = Counter(selected_abilities)
            ability_options: list[BuilderChoiceOption] = []
            for ability in ABILITY_NAME_TO_INDEX:
                current = resolved.get(ability, 0) if resolved is not None else 0
                already_selected = selected_counts[_ability_option_id(ability)]
                disabled_reason = None
                if resolved is None:
                    disabled_reason = "Complete ability scores before assigning an ASI."
                elif current >= ASI_CAP or current + already_selected > ASI_CAP:
                    disabled_reason = f"{ABILITY_LABELS[ability]} cannot exceed {ASI_CAP}."
                ability_options.append(
                    BuilderChoiceOption(
                        option_id=_ability_option_id(ability),
                        label=f"{ABILITY_LABELS[ability]} +1",
                        kind=BuilderOptionKind.COUNTED_REFERENCE,
                        count=1,
                        category="asi_ability",
                        disabled_reason=disabled_reason,
                    )
                )

            # Keep the dependent choice deterministic even after switching to a
            # feat. Saved ASI allocations become harmless stale draft state and
            # become active again if the branch is switched back to ASI.
            ability_choice_active = branch_selection in ((), (asi_option_id,))
            choices.append(
                BuilderChoice(
                    choice_id=ability_id,
                    label="Assign 2 ability score points",
                    source_ref=class_entry.key,
                    required=True,
                    choose_count=2,
                    option_source="content:asi-ability",
                    options=tuple(ability_options),
                    selected_option_ids=selected_abilities,
                    disabled_reason=(
                        None
                        if ability_choice_active
                        else "Choose Ability Score Improvement to assign ability points."
                    ),
                    allow_duplicates=True,
                )
            )

            if (
                branch_selection == (asi_option_id,)
                and resolved is not None
                and len(selected_abilities) == 2
            ):
                parsed = [
                    _ability_from_option_id(option_id)
                    for option_id in selected_abilities
                ]
                if all(ability is not None for ability in parsed):
                    candidate = dict(resolved)
                    for ability in parsed:
                        assert ability is not None
                        candidate[ability] += 1
                    if all(value <= ASI_CAP for value in candidate.values()):
                        resolved = candidate

        node = nodes.get(character_level)
        if node is None:
            continue
        for feature_ref in node.automatic_feature_refs:
            feature = registry.get_optional(feature_ref)
            if feature is not None and feature.key.startswith("srd5.1:feature:"):
                choices.extend(
                    _feature_specific_choices(
                        draft,
                        registry,
                        feature=feature,
                        character_level=character_level,
                    )
                )

    return tuple(choices)


def validate_structural_choice_integrity(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
) -> tuple[BuilderIssue, ...]:
    issues: list[BuilderIssue] = []
    for choice in choices:
        if choice.disabled_reason is not None:
            continue
        selection = draft.draft_payload.choice_selections.get(choice.choice_id)
        selected = selection.selected_option_ids if selection is not None else ()
        path = f"draft_payload.choice_selections.{choice.choice_id}"
        if not choice.allow_duplicates and len(selected) != len(set(selected)):
            issues.append(
                BuilderIssue(
                    code="duplicate_choice_option",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=path,
                    message=(
                        f"{choice.label} does not allow the same option to be selected twice."
                    ),
                    related_refs=tuple(selected),
                )
            )
        option_by_id = {option.option_id: option for option in choice.options}
        disabled = [
            option_id
            for option_id in selected
            if option_id in option_by_id
            and option_by_id[option_id].disabled_reason is not None
        ]
        if disabled:
            issues.append(
                BuilderIssue(
                    code="disabled_choice_option_selected",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=path,
                    message=(
                        f"{choice.label} contains a selection whose prerequisite is not satisfied."
                    ),
                    related_refs=tuple(disabled),
                )
            )
    return tuple(issues)


def _asi_branch_id_for_ability_choice(choice_id: str) -> str | None:
    parts = choice_id.split(":")
    if (
        len(parts) != 4
        or parts[0] != "level"
        or not parts[1].isdigit()
        or parts[2] != "asi-abilities"
        or not parts[3].isdigit()
    ):
        return None
    return deterministic_choice_id("level", parts[1], "asi-feat", parts[3])


def compile_structural_selections(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
) -> StructuralCompilation:
    choice_by_id = {choice.choice_id: choice for choice in choices}
    ability_bonuses: Counter[str] = Counter()
    feats: list[str] = []
    features: list[str] = []
    proficiencies: list[str] = []
    skills: list[str] = []

    for choice_id, selection in draft.draft_payload.choice_selections.items():
        choice = choice_by_id.get(choice_id)
        if choice is None:
            continue
        option_by_id = {option.option_id: option for option in choice.options}

        if choice.option_source == "content:asi-ability":
            branch_id = _asi_branch_id_for_ability_choice(choice.choice_id)
            branch_selection = (
                draft.draft_payload.choice_selections.get(branch_id)
                if branch_id is not None
                else None
            )
            if (
                branch_id is None
                or branch_selection is None
                or branch_selection.selected_option_ids != (_asi_option_id(branch_id),)
                or len(selection.selected_option_ids) != 2
            ):
                continue
            for option_id in selection.selected_option_ids:
                ability = _ability_from_option_id(option_id)
                option = option_by_id.get(option_id)
                if (
                    ability is not None
                    and option is not None
                    and option.disabled_reason is None
                ):
                    ability_bonuses[ability] += 1
            continue

        if choice.option_source == "content:asi-feat":
            if len(selection.selected_option_ids) != 1:
                continue
            option = option_by_id.get(selection.selected_option_ids[0])
            if (
                option is not None
                and option.disabled_reason is None
                and option.reference_id is not None
                and option.reference_id.startswith("srd5.1:feat:")
            ):
                feats.append(option.reference_id)
            continue

        if not (choice.option_source or "").startswith("content:feature:"):
            continue
        for option_id in selection.selected_option_ids:
            option = option_by_id.get(option_id)
            if (
                option is None
                or option.disabled_reason is not None
                or option.reference_id is None
            ):
                continue
            reference_id = option.reference_id
            if reference_id.startswith("srd5.1:feature:"):
                features.append(reference_id)
            elif reference_id.startswith("srd5.1:proficiency:"):
                proficiency_index = reference_id.rsplit(":", 1)[-1]
                if proficiency_index.startswith("skill-"):
                    skill_ref = (
                        "srd5.1:skill:"
                        f"{proficiency_index.removeprefix('skill-')}"
                    )
                    if registry.get_optional(skill_ref) is not None:
                        skills.append(skill_ref)
                        continue
                proficiencies.append(reference_id)
            elif reference_id.startswith("srd5.1:skill:"):
                skills.append(reference_id)

    return StructuralCompilation(
        ability_bonuses=dict(ability_bonuses),
        feat_refs=tuple(dict.fromkeys(feats)),
        feature_refs=tuple(dict.fromkeys(features)),
        proficiencies=tuple(dict.fromkeys(proficiencies)),
        skill_choices=tuple(dict.fromkeys(skills)),
    )