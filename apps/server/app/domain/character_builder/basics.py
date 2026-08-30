from __future__ import annotations

from collections import defaultdict

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character_builder.schemas import (
    BuilderAbilityScoreSummary,
    BuilderChoice,
    BuilderDraft,
    BuilderGrantSummary,
    BuilderResolvedSummary,
)


ABILITY_INDEX_TO_NAME = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}


def _stable_key(reference: dict[str, object]) -> str | None:
    return reference_to_stable_key(reference)


def _entry_name(registry: ContentRegistry, key: str | None) -> str | None:
    if key is None:
        return None
    entry = registry.get_optional(key)
    return entry.name if entry is not None else None


def _grant_from_reference(
    source_ref: str,
    reference: dict[str, object],
    *,
    kind_override: str | None = None,
) -> BuilderGrantSummary | None:
    key = _stable_key(reference)
    label = reference.get("name")
    if key is None or not isinstance(label, str):
        return None
    kind = kind_override or parse_stable_key(key).kind
    return BuilderGrantSummary(
        label=label,
        kind=kind,
        source_ref=source_ref,
        reference_id=key,
    )


def _append_reference_grants(
    grants: list[BuilderGrantSummary],
    entry: ContentEntry,
    field: str,
    *,
    kind_override: str | None = None,
) -> None:
    raw = entry.data.get(field)
    if not isinstance(raw, list):
        return
    for reference in raw:
        if isinstance(reference, dict):
            grant = _grant_from_reference(entry.key, reference, kind_override=kind_override)
            if grant is not None:
                grants.append(grant)


def _append_trait_grants(
    grants: list[BuilderGrantSummary],
    registry: ContentRegistry,
    source_entry: ContentEntry,
    field: str,
) -> None:
    references = source_entry.data.get(field)
    if not isinstance(references, list):
        return
    for reference in references:
        if not isinstance(reference, dict):
            continue
        grant = _grant_from_reference(source_entry.key, reference, kind_override="trait")
        if grant is not None:
            grants.append(grant)
            trait = registry.get_optional(grant.reference_id or "")
            if trait is not None:
                _append_reference_grants(grants, trait, "proficiencies", kind_override="proficiency")


def _append_entry_grants(
    grants: list[BuilderGrantSummary],
    registry: ContentRegistry,
    entry: ContentEntry,
) -> None:
    _append_reference_grants(grants, entry, "languages", kind_override="language")
    _append_reference_grants(grants, entry, "starting_proficiencies", kind_override="proficiency")
    _append_reference_grants(grants, entry, "proficiencies", kind_override="proficiency")
    _append_trait_grants(grants, registry, entry, "traits")
    _append_trait_grants(grants, registry, entry, "racial_traits")

    feature = entry.data.get("feature")
    if isinstance(feature, dict):
        name = feature.get("name")
        if isinstance(name, str) and name.strip():
            grants.append(
                BuilderGrantSummary(
                    label=name,
                    kind="background_feature",
                    source_ref=entry.key,
                )
            )


def _selected_choice_grants(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
) -> list[BuilderGrantSummary]:
    grants: list[BuilderGrantSummary] = []
    selection_by_id = draft.draft_payload.choice_selections
    for choice in choices:
        selection = selection_by_id.get(choice.choice_id)
        if selection is None:
            continue
        option_by_id = {option.option_id: option for option in choice.options}
        for option_id in selection.selected_option_ids:
            option = option_by_id.get(option_id)
            if option is None or option.reference_id is None or option.category == "ability_bonus":
                continue
            try:
                kind = parse_stable_key(option.reference_id).kind
            except ValueError:
                kind = "choice"
            grants.append(
                BuilderGrantSummary(
                    label=option.label,
                    kind=kind,
                    source_ref=choice.source_ref or choice.choice_id,
                    reference_id=option.reference_id,
                )
            )
    return grants


def _ability_bonuses_from_entry(entry: ContentEntry | None) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    if entry is None:
        return result
    bonuses = entry.data.get("ability_bonuses")
    if not isinstance(bonuses, list):
        return result
    for raw in bonuses:
        if not isinstance(raw, dict):
            continue
        reference = raw.get("ability_score")
        bonus = raw.get("bonus")
        if not isinstance(reference, dict) or not isinstance(bonus, int):
            continue
        index = reference.get("index")
        if isinstance(index, str) and index in ABILITY_INDEX_TO_NAME:
            result[ABILITY_INDEX_TO_NAME[index]] += bonus
    return result


def _selected_ability_bonuses(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for choice in choices:
        selection = draft.draft_payload.choice_selections.get(choice.choice_id)
        if selection is None:
            continue
        option_by_id = {option.option_id: option for option in choice.options}
        for option_id in selection.selected_option_ids:
            option = option_by_id.get(option_id)
            if option is None or option.category != "ability_bonus" or option.reference_id is None:
                continue
            ability_index = option.reference_id.rsplit(":", 1)[-1]
            ability_name = ABILITY_INDEX_TO_NAME.get(ability_index)
            if ability_name is not None:
                result[ability_name] += option.count or 0
    return result


def resolve_creation_summary(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
) -> BuilderResolvedSummary:
    payload = draft.draft_payload
    race = registry.get_optional(payload.race_selection.reference_id) if payload.race_selection else None
    subrace = registry.get_optional(payload.subrace_selection.reference_id) if payload.subrace_selection else None
    background = registry.get_optional(payload.background_selection.reference_id) if payload.background_selection else None

    grants: list[BuilderGrantSummary] = []
    for entry in (race, subrace, background):
        if entry is not None:
            _append_entry_grants(grants, registry, entry)
    grants.extend(_selected_choice_grants(draft, choices))

    deduped_grants: list[BuilderGrantSummary] = []
    seen_grants: set[tuple[str, str, str | None]] = set()
    for grant in grants:
        identity = (grant.kind, grant.label, grant.reference_id)
        if identity in seen_grants:
            continue
        seen_grants.add(identity)
        deduped_grants.append(grant)

    ability_summaries: list[BuilderAbilityScoreSummary] = []
    if payload.ability_generation is not None:
        bonuses: dict[str, int] = defaultdict(int)
        for source in (
            _ability_bonuses_from_entry(race),
            _ability_bonuses_from_entry(subrace),
            _selected_ability_bonuses(draft, choices),
        ):
            for ability, bonus in source.items():
                bonuses[ability] += bonus
        override_map = {
            override.key.removeprefix("ability:"): int(override.value)
            for override in payload.numeric_overrides
            if override.key.startswith("ability:") and float(override.value).is_integer()
        }
        for ability, base in payload.ability_generation.scores.as_dict().items():
            resolved = base + bonuses.get(ability, 0)
            effective = override_map.get(ability, resolved)
            ability_summaries.append(
                BuilderAbilityScoreSummary(
                    ability=ability,
                    base=base,
                    permanent_bonus=bonuses.get(ability, 0),
                    resolved=resolved,
                    effective=effective,
                    overridden=ability in override_map,
                )
            )

    selected_reference_count = sum(
        selection is not None
        for selection in (
            payload.race_selection,
            payload.subrace_selection,
            payload.background_selection,
            payload.alignment_selection,
        )
    )
    return BuilderResolvedSummary(
        name=payload.basic.name if payload.basic is not None else None,
        target_level=payload.target_level,
        race_name=_entry_name(registry, payload.race_selection.reference_id if payload.race_selection else None),
        subrace_name=_entry_name(registry, payload.subrace_selection.reference_id if payload.subrace_selection else None),
        background_name=_entry_name(registry, payload.background_selection.reference_id if payload.background_selection else None),
        alignment_name=_entry_name(registry, payload.alignment_selection.reference_id if payload.alignment_selection else None),
        selected_reference_count=selected_reference_count,
        choice_selection_count=len(payload.choice_selections),
        grants=tuple(deduped_grants),
        ability_scores=tuple(ability_summaries),
    )
