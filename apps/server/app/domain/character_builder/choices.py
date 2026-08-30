from __future__ import annotations

import re
from urllib.parse import urlparse

from app.content.identity import (
    URL_ROUTE_TO_KIND,
    reference_to_stable_key,
    stable_key_is_kind,
)
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderOptionKind,
)


_CHOICE_PART = re.compile(r"[^a-z0-9:._-]+")


def deterministic_choice_id(*parts: str) -> str:
    normalized: list[str] = []
    for part in parts:
        value = _CHOICE_PART.sub("-", part.strip().lower()).strip("-")
        if not value:
            raise ValueError("choice id parts cannot be blank")
        normalized.append(value)
    return ":".join(normalized)


def _stable_key(reference: dict[str, object]) -> str | None:
    return reference_to_stable_key(reference)


def _entry_label(entry: ContentEntry) -> str:
    source_label = entry.source_label or entry.source
    return f"{entry.name} · {source_label}"


def _reference_option(
    reference: dict[str, object],
    registry: ContentRegistry,
) -> BuilderChoiceOption | None:
    key = _stable_key(reference)
    name = reference.get("name")
    if key is None or not isinstance(name, str):
        return None
    target = registry.get_optional(key)
    return BuilderChoiceOption(
        option_id=key,
        label=_entry_label(target) if target is not None else name,
        kind=BuilderOptionKind.REFERENCE,
        reference_id=key,
    )


def _rule_options(rule: dict[str, object], registry: ContentRegistry) -> tuple[BuilderChoiceOption, ...]:
    source = rule.get("from")
    if not isinstance(source, dict):
        return ()
    source_type = source.get("option_set_type")
    result: list[BuilderChoiceOption] = []

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
        # A legacy /api/2014 resource list explicitly denotes the SRD source.
        return tuple(
            BuilderChoiceOption(
                option_id=entry.key,
                label=_entry_label(entry),
                kind=BuilderOptionKind.REFERENCE,
                reference_id=entry.key,
            )
            for entry in registry.list_kind(kind, source="srd5.1")
        )

    options = source.get("options")
    if source_type != "options_array" or not isinstance(options, list):
        return ()

    for raw in options:
        if not isinstance(raw, dict):
            continue
        option_type = raw.get("option_type")
        if option_type == "reference" and isinstance(raw.get("item"), dict):
            option = _reference_option(raw["item"], registry)
            if option is not None:
                result.append(option)
        elif option_type in {"ability_bonus", "bonus"} and isinstance(raw.get("ability_score"), dict):
            ability_ref = raw["ability_score"]
            key = _stable_key(ability_ref)
            name = ability_ref.get("name")
            bonus = raw.get("bonus")
            if key is not None and isinstance(name, str) and isinstance(bonus, int) and bonus > 0:
                result.append(
                    BuilderChoiceOption(
                        option_id=f"{key}@+{bonus}",
                        label=f"{name} +{bonus}",
                        kind=BuilderOptionKind.COUNTED_REFERENCE,
                        reference_id=key,
                        count=bonus,
                        category="ability_bonus",
                    )
                )
    return tuple(result)


def _selection_for(draft: BuilderDraft, choice_id: str) -> tuple[str, ...]:
    selection = draft.draft_payload.choice_selections.get(choice_id)
    return selection.selected_option_ids if selection is not None else ()


def _rule_choice(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    source_ref: str,
    field: str,
    label: str,
    rule: dict[str, object],
    occurrence: int = 0,
    disabled_reason: str | None = None,
) -> BuilderChoice:
    choose = rule.get("choose")
    choose_count = int(choose) if isinstance(choose, int) and choose >= 0 else 1
    choice_id = deterministic_choice_id(source_ref, field, str(occurrence))
    options = () if disabled_reason else _rule_options(rule, registry)
    return BuilderChoice(
        choice_id=choice_id,
        label=label,
        source_ref=source_ref,
        required=True,
        choose_count=choose_count,
        option_source=f"content:{field}",
        options=options,
        selected_option_ids=_selection_for(draft, choice_id),
        disabled_reason=disabled_reason,
    )


def _entry_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    entry: ContentEntry,
) -> list[BuilderChoice]:
    result: list[BuilderChoice] = []
    fields = (
        ("ability_bonus_options", "Ability score bonuses", None),
        ("language_options", "Languages", None),
        ("starting_proficiency_options", "Starting proficiencies", None),
        ("proficiency_choices", "Proficiencies", None),
        ("spell_options", "Spell choice", "Spell choices are completed in P1-E."),
        ("starting_equipment_options", "Starting equipment", "Starting equipment choices are completed in P1-F."),
    )
    for field, label, disabled_reason in fields:
        rule = entry.data.get(field)
        if isinstance(rule, dict):
            result.append(
                _rule_choice(
                    draft,
                    registry,
                    source_ref=entry.key,
                    field=field,
                    label=f"{entry.name} — {label}",
                    rule=rule,
                    disabled_reason=disabled_reason,
                )
            )

    subtraits = entry.data.get("subtraits")
    if isinstance(subtraits, list) and subtraits:
        options = tuple(
            option
            for reference in subtraits
            if isinstance(reference, dict)
            for option in [_reference_option(reference, registry)]
            if option is not None
        )
        choice_id = deterministic_choice_id(entry.key, "subtrait", "0")
        result.append(
            BuilderChoice(
                choice_id=choice_id,
                label=f"{entry.name} — Choice",
                source_ref=entry.key,
                required=True,
                choose_count=1,
                option_source="content:subtraits",
                options=options,
                selected_option_ids=_selection_for(draft, choice_id),
            )
        )
    return result


def _trait_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    references: object,
) -> list[BuilderChoice]:
    if not isinstance(references, list):
        return []
    result: list[BuilderChoice] = []
    for reference in references:
        if not isinstance(reference, dict):
            continue
        key = _stable_key(reference)
        if key is None:
            continue
        trait = registry.get_optional(key)
        if trait is not None:
            result.extend(_entry_choices(draft, registry, trait))
    return result


def _reference_options(registry: ContentRegistry, kind: str) -> tuple[BuilderChoiceOption, ...]:
    return tuple(
        BuilderChoiceOption(
            option_id=entry.key,
            label=_entry_label(entry),
            kind=BuilderOptionKind.REFERENCE,
            reference_id=entry.key,
        )
        for entry in registry.list_kind(kind)
    )


def build_foundation_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[BuilderChoice, ...]:
    payload = draft.draft_payload
    choices: list[BuilderChoice] = [
        BuilderChoice(
            choice_id=deterministic_choice_id("draft", "race-selection"),
            label="Race",
            required=True,
            choose_count=1,
            option_source="content:race",
            options=_reference_options(registry, "race"),
            selected_option_ids=(
                (payload.race_selection.reference_id,) if payload.race_selection is not None else ()
            ),
        ),
        BuilderChoice(
            choice_id=deterministic_choice_id("draft", "background-selection"),
            label="Background",
            required=True,
            choose_count=1,
            option_source="content:background",
            options=_reference_options(registry, "background"),
            selected_option_ids=(
                (payload.background_selection.reference_id,)
                if payload.background_selection is not None
                else ()
            ),
        ),
        BuilderChoice(
            choice_id=deterministic_choice_id("draft", "alignment-selection"),
            label="Alignment (optional)",
            required=False,
            choose_count=1,
            option_source="content:alignment",
            options=_reference_options(registry, "alignment"),
            selected_option_ids=(
                (payload.alignment_selection.reference_id,)
                if payload.alignment_selection is not None
                else ()
            ),
        ),
        BuilderChoice(
            choice_id=deterministic_choice_id("draft", "ability-generation"),
            label="Ability generation",
            required=True,
            choose_count=1,
            option_source="builder:ability-generation",
            options=(
                BuilderChoiceOption(option_id="standard_array", label="Standard Array", kind=BuilderOptionKind.BRANCH, branch_key="standard_array"),
                BuilderChoiceOption(option_id="point_buy", label="Point Buy", kind=BuilderOptionKind.BRANCH, branch_key="point_buy"),
                BuilderChoiceOption(option_id="manual", label="Manual Input", kind=BuilderOptionKind.BRANCH, branch_key="manual"),
            ),
            selected_option_ids=((payload.ability_generation.method.value,) if payload.ability_generation else ()),
        ),
    ]

    race_entry: ContentEntry | None = None
    if payload.race_selection is not None:
        race_entry = registry.get_optional(payload.race_selection.reference_id)
        if race_entry is not None and stable_key_is_kind(race_entry.key, "race"):
            subraces = race_entry.data.get("subraces")
            if isinstance(subraces, list) and subraces:
                options = tuple(
                    option
                    for reference in subraces
                    if isinstance(reference, dict)
                    for option in [_reference_option(reference, registry)]
                    if option is not None
                )
                choices.append(
                    BuilderChoice(
                        choice_id=deterministic_choice_id(race_entry.key, "subrace-selection"),
                        label=f"{race_entry.name} — Subrace",
                        source_ref=race_entry.key,
                        required=True,
                        choose_count=1,
                        option_source="content:subrace",
                        options=options,
                        selected_option_ids=(
                            (payload.subrace_selection.reference_id,)
                            if payload.subrace_selection is not None
                            else ()
                        ),
                    )
                )
            choices.extend(_entry_choices(draft, registry, race_entry))
            choices.extend(_trait_choices(draft, registry, race_entry.data.get("traits")))

    if payload.subrace_selection is not None:
        subrace_entry = registry.get_optional(payload.subrace_selection.reference_id)
        if subrace_entry is not None and stable_key_is_kind(subrace_entry.key, "subrace"):
            choices.extend(_entry_choices(draft, registry, subrace_entry))
            choices.extend(_trait_choices(draft, registry, subrace_entry.data.get("racial_traits")))

    if payload.background_selection is not None:
        background = registry.get_optional(payload.background_selection.reference_id)
        if background is not None and stable_key_is_kind(background.key, "background"):
            choices.extend(_entry_choices(draft, registry, background))

    if payload.target_level is not None:
        for level in range(1, payload.target_level + 1):
            choices.append(
                BuilderChoice(
                    choice_id=deterministic_choice_id("level", str(level), "class-selection"),
                    label=f"Level {level} class",
                    required=True,
                    choose_count=1,
                    option_source="content:class",
                    disabled_reason="Class progression is implemented in P1-C.",
                )
            )

    known_ids = {choice.choice_id for choice in choices}
    for key in sorted(payload.choice_selections):
        selection = payload.choice_selections[key]
        if key in known_ids:
            continue
        choices.append(
            BuilderChoice(
                choice_id=selection.choice_id,
                label=selection.choice_id,
                source_ref=selection.source_ref,
                required=False,
                choose_count=len(selection.selected_option_ids),
                option_source="draft:selection",
                selected_option_ids=selection.selected_option_ids,
            )
        )

    return tuple(choices)
