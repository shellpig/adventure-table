from __future__ import annotations

from dataclasses import dataclass

from app.content.identity import parse_stable_key, reference_to_stable_key, stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import AncestralLegacySelection, CharacterBuild
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderMode,
    BuilderOptionKind,
)


LINEAGE_SELECTION_CHOICE_ID = "lineage:selection"
LINEAGE_ASI_PATTERN_CHOICE_ID = "lineage:asi-pattern"
LINEAGE_ASI_PLUS_TWO_CHOICE_ID = "lineage:asi-plus-two"
LINEAGE_ASI_PLUS_ONE_CHOICE_ID = "lineage:asi-plus-one"
LINEAGE_ASI_TRIPLE_CHOICE_ID = "lineage:asi-triple"
LINEAGE_SIZE_CHOICE_ID = "lineage:size"
LINEAGE_LANGUAGE_CHOICE_ID = "lineage:language"
LINEAGE_SKILL_CHOICE_ID = "lineage:ancestral-skills"
LINEAGE_MOVEMENT_CHOICE_ID = "lineage:ancestral-movement"
ASI_PATTERN_2_1 = "lineage-asi:2-1"
ASI_PATTERN_1_1_1 = "lineage-asi:1-1-1"
ABILITY_INDEXES = ("str", "dex", "con", "int", "wis", "cha")
ABILITY_LABELS = {
    "str": "STR",
    "dex": "DEX",
    "con": "CON",
    "int": "INT",
    "wis": "WIS",
    "cha": "CHA",
}
MOVEMENT_LABELS = {"climb": "Climb", "fly": "Fly", "swim": "Swim"}


@dataclass(frozen=True)
class LineageCompilation:
    lineage_ref: str | None = None
    ancestral_origin_ref: str | None = None
    ancestral_legacy: AncestralLegacySelection | None = None
    size: str | None = None
    language_refs: tuple[str, ...] = ()
    skill_refs: tuple[str, ...] = ()
    feature_refs: tuple[str, ...] = ()
    walking_speed: int | None = None
    climb_speed: int | None = None
    fly_speed: int | None = None
    swim_speed: int | None = None
    issues: tuple[BuilderIssue, ...] = ()


def selected_lineage_ref(draft: BuilderDraft) -> str | None:
    if draft.draft_payload.lineage_selection is not None:
        return draft.draft_payload.lineage_selection.reference_id
    selection = draft.draft_payload.choice_selections.get(LINEAGE_SELECTION_CHOICE_ID)
    if selection is None or len(selection.selected_option_ids) != 1:
        return None
    candidate = selection.selected_option_ids[0]
    return candidate if stable_key_is_kind(candidate, "lineage") else None


def _selected(draft: BuilderDraft, choice_id: str) -> tuple[str, ...]:
    record = draft.draft_payload.choice_selections.get(choice_id)
    return record.selected_option_ids if record is not None else ()


def _reference_key(reference: object) -> str | None:
    if not isinstance(reference, dict):
        return None
    try:
        return reference_to_stable_key(reference)
    except ValueError:
        return None


def _skill_from_reference(reference_id: str, registry: ContentRegistry) -> str | None:
    try:
        parsed = parse_stable_key(reference_id)
    except ValueError:
        return None
    if parsed.kind == "skill":
        return reference_id if registry.get_optional(reference_id) is not None else None
    if parsed.kind != "proficiency" or not parsed.index.startswith("skill-"):
        return None
    skill_ref = stable_key(parsed.source, "skill", parsed.index.removeprefix("skill-"))
    return skill_ref if registry.get_optional(skill_ref) is not None else None


def _ancestry_source_refs(draft: BuilderDraft, registry: ContentRegistry, base_build: CharacterBuild | None) -> set[str]:
    refs: set[str] = set()
    for value in (
        base_build.race_ref if base_build is not None else None,
        base_build.subrace_ref if base_build is not None else None,
        base_build.race_variant_ref if base_build is not None else None,
        draft.draft_payload.race_selection.reference_id if draft.draft_payload.race_selection else None,
        draft.draft_payload.subrace_selection.reference_id if draft.draft_payload.subrace_selection else None,
        draft.draft_payload.race_variant_selection.reference_id if draft.draft_payload.race_variant_selection else None,
    ):
        if value:
            refs.add(value)

    queue = list(refs)
    while queue:
        source_ref = queue.pop()
        entry = registry.get_optional(source_ref)
        if entry is None:
            continue
        for field in ("traits", "racial_traits", "features"):
            raw = entry.data.get(field)
            if not isinstance(raw, list):
                continue
            for reference in raw:
                key = _reference_key(reference)
                if key is not None and key not in refs:
                    refs.add(key)
                    queue.append(key)
    return refs


def eligible_ancestral_skills(draft: BuilderDraft, registry: ContentRegistry, base_build: CharacterBuild | None) -> tuple[str, ...]:
    if base_build is None or draft.mode is BuilderMode.CREATE:
        return ()
    ancestry_refs = _ancestry_source_refs(draft, registry, base_build)
    candidates: list[str] = []

    # Explicit Builder provenance is the strongest evidence. The seeded Build
    # Edit draft retains the source payload from version N, so class/background
    # choices cannot be mistaken for race-origin choices merely because the
    # same skill appears in the final Build.
    for selection in draft.draft_payload.choice_selections.values():
        if selection.source_ref not in ancestry_refs:
            continue
        for option_id in selection.selected_option_ids:
            skill_ref = _skill_from_reference(option_id, registry)
            if skill_ref is not None:
                candidates.append(skill_ref)

    # Fixed racial/trait skill proficiencies have no choice record; derive only
    # from ancestry content and intersect with the persisted Build.
    build_skills = set(base_build.skill_choices)
    for source_ref in ancestry_refs:
        entry = registry.get_optional(source_ref)
        if entry is None:
            continue
        for field in ("starting_proficiencies", "proficiencies"):
            raw = entry.data.get(field)
            if not isinstance(raw, list):
                continue
            for reference in raw:
                key = _reference_key(reference)
                if key is None:
                    continue
                skill_ref = _skill_from_reference(key, registry)
                if skill_ref is not None and skill_ref in build_skills:
                    candidates.append(skill_ref)
    return tuple(dict.fromkeys(candidates))


def eligible_ancestral_movements(base_build: CharacterBuild | None) -> tuple[str, ...]:
    if base_build is None:
        return ()
    result = []
    if base_build.climb_speed is not None:
        result.append("climb")
    if base_build.fly_speed is not None:
        result.append("fly")
    if base_build.swim_speed is not None:
        result.append("swim")
    return tuple(result)


def _ability_options(*, bonus: int, disabled: set[str] | None = None) -> tuple[BuilderChoiceOption, ...]:
    disabled = disabled or set()
    return tuple(
        BuilderChoiceOption(
            option_id=f"lineage-ability:{index}:{bonus}",
            label=f"{ABILITY_LABELS[index]} +{bonus}",
            kind=BuilderOptionKind.COUNTED_REFERENCE,
            reference_id=f"srd5.1:ability:{index}",
            count=bonus,
            category="ability_bonus",
            disabled_reason=("Choose a different ability." if index in disabled else None),
            disabled_reason_code=("lineage_asi_ability_must_be_distinct" if index in disabled else None),
        )
        for index in ABILITY_INDEXES
    )


def build_lineage_choices(draft: BuilderDraft, registry: ContentRegistry, *, base_build: CharacterBuild | None = None) -> tuple[BuilderChoice, ...]:
    lineage_ref = selected_lineage_ref(draft)
    lineages = registry.list_kind("lineage")
    selector = BuilderChoice(
        choice_id=LINEAGE_SELECTION_CHOICE_ID,
        label="Lineage",
        required=False,
        choose_count=1,
        option_source="content:lineage",
        options=tuple(
            BuilderChoiceOption(
                option_id=entry.key,
                label=entry.name,
                kind=BuilderOptionKind.REFERENCE,
                reference_id=entry.key,
                category="lineage",
            )
            for entry in lineages
        ),
        selected_option_ids=((lineage_ref,) if lineage_ref is not None else ()),
    )
    if lineage_ref is None:
        return (selector,)

    lineage = registry.get_optional(lineage_ref)
    if lineage is None or not stable_key_is_kind(lineage.key, "lineage"):
        return (selector,)
    result: list[BuilderChoice] = [selector]

    pattern_selection = _selected(draft, LINEAGE_ASI_PATTERN_CHOICE_ID)
    result.append(
        BuilderChoice(
            choice_id=LINEAGE_ASI_PATTERN_CHOICE_ID,
            label=f"{lineage.name} — Ability Score Increase",
            source_ref=lineage.key,
            required=True,
            choose_count=1,
            option_source="content:lineage-asi-pattern",
            options=(
                BuilderChoiceOption(option_id=ASI_PATTERN_2_1, label="+2 / +1", kind=BuilderOptionKind.BRANCH, branch_key="2-1"),
                BuilderChoiceOption(option_id=ASI_PATTERN_1_1_1, label="+1 / +1 / +1", kind=BuilderOptionKind.BRANCH, branch_key="1-1-1"),
            ),
            selected_option_ids=pattern_selection,
        )
    )
    if pattern_selection == (ASI_PATTERN_2_1,):
        plus_two_selected = _selected(draft, LINEAGE_ASI_PLUS_TWO_CHOICE_ID)
        selected_indexes = {
            option_id.split(":")[1]
            for option_id in plus_two_selected
            if option_id.startswith("lineage-ability:") and len(option_id.split(":")) == 3
        }
        result.extend(
            (
                BuilderChoice(
                    choice_id=LINEAGE_ASI_PLUS_TWO_CHOICE_ID,
                    label=f"{lineage.name} — +2 Ability",
                    source_ref=lineage.key,
                    required=True,
                    choose_count=1,
                    option_source="content:lineage-asi-ability",
                    options=_ability_options(bonus=2),
                    selected_option_ids=plus_two_selected,
                ),
                BuilderChoice(
                    choice_id=LINEAGE_ASI_PLUS_ONE_CHOICE_ID,
                    label=f"{lineage.name} — +1 Ability",
                    source_ref=lineage.key,
                    required=True,
                    choose_count=1,
                    option_source="content:lineage-asi-ability",
                    options=_ability_options(bonus=1, disabled=selected_indexes),
                    selected_option_ids=_selected(draft, LINEAGE_ASI_PLUS_ONE_CHOICE_ID),
                ),
            )
        )
    elif pattern_selection == (ASI_PATTERN_1_1_1,):
        result.append(
            BuilderChoice(
                choice_id=LINEAGE_ASI_TRIPLE_CHOICE_ID,
                label=f"{lineage.name} — Three +1 Abilities",
                source_ref=lineage.key,
                required=True,
                choose_count=3,
                option_source="content:lineage-asi-ability",
                options=_ability_options(bonus=1),
                selected_option_ids=_selected(draft, LINEAGE_ASI_TRIPLE_CHOICE_ID),
            )
        )

    sizes = lineage.data.get("sizes")
    if isinstance(sizes, list):
        result.append(
            BuilderChoice(
                choice_id=LINEAGE_SIZE_CHOICE_ID,
                label=f"{lineage.name} — Size",
                source_ref=lineage.key,
                required=True,
                choose_count=1,
                option_source="content:lineage-size",
                options=tuple(
                    BuilderChoiceOption(
                        option_id=f"lineage-size:{size}",
                        label=str(size).title(),
                        kind=BuilderOptionKind.BRANCH,
                        branch_key=str(size),
                    )
                    for size in sizes
                ),
                selected_option_ids=_selected(draft, LINEAGE_SIZE_CHOICE_ID),
            )
        )

    if draft.mode is BuilderMode.CREATE or base_build is None:
        count = lineage.data.get("direct_create_additional_language_count", 0)
        if isinstance(count, int) and count > 0:
            fixed_languages = {
                key for raw in lineage.data.get("direct_create_languages", [])
                if (key := _reference_key(raw)) is not None
            }
            result.append(
                BuilderChoice(
                    choice_id=LINEAGE_LANGUAGE_CHOICE_ID,
                    label=f"{lineage.name} — Language",
                    source_ref=lineage.key,
                    required=True,
                    choose_count=count,
                    option_source="content:lineage-language",
                    options=tuple(
                        BuilderChoiceOption(
                            option_id=entry.key,
                            label=entry.name,
                            kind=BuilderOptionKind.REFERENCE,
                            reference_id=entry.key,
                            category="language",
                        )
                        for entry in registry.list_kind("language")
                        if entry.key not in fixed_languages
                    ),
                    selected_option_ids=_selected(draft, LINEAGE_LANGUAGE_CHOICE_ID),
                )
            )
        skill_count = lineage.data.get("direct_legacy_skill_count", 0)
        if isinstance(skill_count, int) and skill_count > 0:
            result.append(
                BuilderChoice(
                    choice_id=LINEAGE_SKILL_CHOICE_ID,
                    label=f"{lineage.name} — Ancestral Legacy Skills",
                    source_ref=lineage.key,
                    required=True,
                    choose_count=skill_count,
                    option_source="content:lineage-legacy-skill",
                    options=tuple(
                        BuilderChoiceOption(
                            option_id=entry.key,
                            label=entry.name,
                            kind=BuilderOptionKind.REFERENCE,
                            reference_id=entry.key,
                            category="skill",
                        )
                        for entry in registry.list_kind("skill")
                    ),
                    selected_option_ids=_selected(draft, LINEAGE_SKILL_CHOICE_ID),
                )
            )
    else:
        eligible_skills = eligible_ancestral_skills(draft, registry, base_build)
        if eligible_skills:
            result.append(
                BuilderChoice(
                    choice_id=LINEAGE_SKILL_CHOICE_ID,
                    label=f"{lineage.name} — Retain Ancestral Skills",
                    source_ref=lineage.key,
                    required=False,
                    choose_count=len(eligible_skills),
                    option_source="content:lineage-legacy-skill",
                    options=tuple(
                        BuilderChoiceOption(
                            option_id=skill_ref,
                            label=(registry.get_optional(skill_ref).name if registry.get_optional(skill_ref) is not None else skill_ref),
                            kind=BuilderOptionKind.REFERENCE,
                            reference_id=skill_ref,
                            category="skill",
                        )
                        for skill_ref in eligible_skills
                    ),
                    selected_option_ids=_selected(draft, LINEAGE_SKILL_CHOICE_ID),
                )
            )
        eligible_movement = eligible_ancestral_movements(base_build)
        if eligible_movement:
            result.append(
                BuilderChoice(
                    choice_id=LINEAGE_MOVEMENT_CHOICE_ID,
                    label=f"{lineage.name} — Retain Ancestral Movement",
                    source_ref=lineage.key,
                    required=False,
                    choose_count=len(eligible_movement),
                    option_source="content:lineage-legacy-movement",
                    options=tuple(
                        BuilderChoiceOption(
                            option_id=f"lineage-movement:{mode}",
                            label=MOVEMENT_LABELS[mode],
                            kind=BuilderOptionKind.BRANCH,
                            branch_key=mode,
                        )
                        for mode in eligible_movement
                    ),
                    selected_option_ids=_selected(draft, LINEAGE_MOVEMENT_CHOICE_ID),
                )
            )
    return tuple(result)


def suppress_replaced_origin_choices(draft: BuilderDraft, choices: tuple[BuilderChoice, ...]) -> tuple[BuilderChoice, ...]:
    if selected_lineage_ref(draft) is None:
        return choices
    background_ref = draft.draft_payload.background_selection.reference_id if draft.draft_payload.background_selection else None
    keep_sources = {background_ref} if background_ref else set()
    keep_option_sources = {
        "content:race",
        "content:background",
        "content:alignment",
        "builder:ability-generation",
    }
    return tuple(
        choice
        for choice in choices
        if choice.option_source in keep_option_sources or choice.source_ref in keep_sources
    )


def _feature_refs(lineage: ContentEntry, registry: ContentRegistry, target_level: int) -> tuple[str, ...]:
    result: list[str] = []
    raw = lineage.data.get("features")
    if not isinstance(raw, list):
        return ()
    for reference in raw:
        key = _reference_key(reference)
        if key is None:
            continue
        feature = registry.get_optional(key)
        if feature is None:
            continue
        minimum = feature.data.get("minimum_character_level", 1)
        if isinstance(minimum, int) and target_level >= minimum:
            result.append(key)
    return tuple(dict.fromkeys(result))


def compile_lineage(draft: BuilderDraft, registry: ContentRegistry, *, base_build: CharacterBuild | None = None) -> LineageCompilation:
    lineage_ref = selected_lineage_ref(draft)
    if lineage_ref is None:
        return LineageCompilation()
    lineage = registry.get_optional(lineage_ref)
    if lineage is None or not stable_key_is_kind(lineage.key, "lineage"):
        return LineageCompilation(
            lineage_ref=lineage_ref,
            issues=(BuilderIssue(
                code="unknown_lineage",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="draft_payload.lineage_selection",
                message="Selected lineage is not available.",
                related_refs=(lineage_ref,),
            ),),
        )

    issues: list[BuilderIssue] = []
    size_selection = _selected(draft, LINEAGE_SIZE_CHOICE_ID)
    size = size_selection[0].removeprefix("lineage-size:") if len(size_selection) == 1 else None
    if size not in set(lineage.data.get("sizes", [])):
        size = None

    selected_skills = tuple(
        option_id for option_id in _selected(draft, LINEAGE_SKILL_CHOICE_ID)
        if stable_key_is_kind(option_id, "skill")
    )
    if draft.mode is BuilderMode.CREATE or base_build is None:
        eligible_skills = {entry.key for entry in registry.list_kind("skill")}
        expected_skill_count = lineage.data.get("direct_legacy_skill_count", 0)
        if len(selected_skills) != expected_skill_count or not set(selected_skills).issubset(eligible_skills):
            issues.append(BuilderIssue(
                code="invalid_lineage_legacy_skills",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path=f"draft_payload.choice_selections.{LINEAGE_SKILL_CHOICE_ID}",
                message="Direct-create Ancestral Legacy skill selection is incomplete or invalid.",
                related_refs=selected_skills,
            ))
        fixed_languages = tuple(
            key for raw in lineage.data.get("direct_create_languages", [])
            if (key := _reference_key(raw)) is not None
        )
        extra_languages = tuple(
            option_id for option_id in _selected(draft, LINEAGE_LANGUAGE_CHOICE_ID)
            if stable_key_is_kind(option_id, "language")
        )
        language_refs = tuple(dict.fromkeys((*fixed_languages, *extra_languages)))
        ancestral_origin_ref = None
    else:
        allowed = set(eligible_ancestral_skills(draft, registry, base_build))
        illegal = tuple(skill for skill in selected_skills if skill not in allowed)
        if illegal:
            issues.append(BuilderIssue(
                code="illegal_ancestral_legacy_skill",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path=f"draft_payload.choice_selections.{LINEAGE_SKILL_CHOICE_ID}",
                message="Ancestral Legacy can retain only race-origin skill proficiencies.",
                related_refs=illegal,
            ))
        language_refs = base_build.language_refs
        ancestral_origin_ref = base_build.race_ref

    selected_movements = tuple(
        option_id.removeprefix("lineage-movement:")
        for option_id in _selected(draft, LINEAGE_MOVEMENT_CHOICE_ID)
        if option_id.startswith("lineage-movement:")
    )
    allowed_movements = set(eligible_ancestral_movements(base_build)) if base_build is not None else set()
    illegal_movements = tuple(mode for mode in selected_movements if mode not in allowed_movements)
    if illegal_movements:
        issues.append(BuilderIssue(
            code="illegal_ancestral_legacy_movement",
            severity=BuilderIssueSeverity.BLOCKING_ERROR,
            path=f"draft_payload.choice_selections.{LINEAGE_MOVEMENT_CHOICE_ID}",
            message="Ancestral Legacy can retain only an existing climb, fly, or swim speed.",
        ))

    climb_speed = lineage.data.get("climb_speed") if isinstance(lineage.data.get("climb_speed"), int) else None
    fly_speed = None
    swim_speed = None
    if base_build is not None:
        if "climb" in selected_movements and base_build.climb_speed is not None:
            climb_speed = max(climb_speed or 0, base_build.climb_speed)
        if "fly" in selected_movements:
            fly_speed = base_build.fly_speed
        if "swim" in selected_movements:
            swim_speed = base_build.swim_speed

    walking_speed = lineage.data.get("walking_speed")
    return LineageCompilation(
        lineage_ref=lineage.key,
        ancestral_origin_ref=ancestral_origin_ref,
        ancestral_legacy=AncestralLegacySelection(
            retained_skill_refs=selected_skills,
            retained_movement_modes=tuple(mode for mode in selected_movements if mode in {"climb", "fly", "swim"}),
        ),
        size=size,
        language_refs=language_refs,
        skill_refs=selected_skills,
        feature_refs=_feature_refs(lineage, registry, draft.draft_payload.target_level or 0),
        walking_speed=walking_speed if isinstance(walking_speed, int) else None,
        climb_speed=climb_speed,
        fly_speed=fly_speed,
        swim_speed=swim_speed,
        issues=tuple(issues),
    )
