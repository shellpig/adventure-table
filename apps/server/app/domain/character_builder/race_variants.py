from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.content.identity import parse_stable_key, reference_to_stable_key, stable_key_is_kind
from app.content.m01m_models import (
    ConditionalMovementGrantData,
    M01MRaceVariantData,
    M01MRaceVariantReplacementOption,
)
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import RaceVariantGroupSelection, SpellAccessEntry
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderGrantSummary,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderOptionKind,
    BuilderResolvedSummary,
)
from app.domain.rules.spellcasting import spell_is_on_class_list


RACE_VARIANT_OPTION_SOURCE = "content:race-variant"
RACE_VARIANT_REPLACEMENT_OPTION_SOURCE = "content:race-variant-replacement"
RACE_VARIANT_SPELL_OPTION_SOURCE = "content:race-variant-spell"
_RACE_VARIANT_CHOICE_PREFIX = "race-variant:"
_ABILITY_INDEX_TO_NAME = {
    "str": "strength",
    "dex": "dexterity",
    "con": "constitution",
    "int": "intelligence",
    "wis": "wisdom",
    "cha": "charisma",
}


@dataclass(frozen=True)
class RaceVariantCompilation:
    race_variant_ref: str | None = None
    group_selections: tuple[RaceVariantGroupSelection, ...] = ()
    walking_speed: int | None = None
    swim_speed: int | None = None
    climb_speed: int | None = None
    fly_speed: int | None = None
    spell_access_entries: tuple[SpellAccessEntry, ...] = ()


def _reference_key(reference: object, *, kinds: set[str] | None = None) -> str | None:
    if hasattr(reference, "model_dump"):
        reference = reference.model_dump(exclude_none=True)
    if not isinstance(reference, dict):
        return None
    try:
        return reference_to_stable_key(reference, kinds=kinds)
    except ValueError:
        return None


def _variant_entry(draft: BuilderDraft, registry: ContentRegistry) -> ContentEntry | None:
    selection = draft.draft_payload.race_variant_selection
    if selection is None:
        return None
    entry = registry.get_optional(selection.reference_id)
    if entry is None or not stable_key_is_kind(entry.key, "race-variant"):
        return None
    return entry


def _variant_data(entry: ContentEntry) -> M01MRaceVariantData:
    return M01MRaceVariantData.model_validate(entry.data)


def _base_race_ref(data: M01MRaceVariantData) -> str | None:
    return _reference_key(data.base_race_ref, kinds={"race"})


def _eligible_variant_entries(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[ContentEntry, ...]:
    race = draft.draft_payload.race_selection
    if race is None:
        return ()
    result: list[ContentEntry] = []
    for entry in registry.list_kind("race-variant"):
        data = _variant_data(entry)
        if _base_race_ref(data) == race.reference_id:
            result.append(entry)
    return tuple(result)


def _replacement_choice_id(variant_ref: str, group_id: str) -> str:
    return deterministic_choice_id("race-variant", variant_ref, group_id)


def _spell_choice_id(variant_ref: str, group_id: str, option_id: str) -> str:
    return deterministic_choice_id(
        "race-variant", variant_ref, group_id, option_id, "spell"
    )


def is_race_variant_choice_id(choice_id: str) -> bool:
    return choice_id.startswith(_RACE_VARIANT_CHOICE_PREFIX)


def _selected_options(
    draft: BuilderDraft,
    variant: ContentEntry,
) -> tuple[tuple[str, M01MRaceVariantReplacementOption], ...]:
    """Return every valid selected replacement group in declaration order.

    M01-E only needed one group and historically stopped at the first match.
    M01-M deliberately removes that implicit singleton assumption so SCAG
    Tiefling can persist Feral and Legacy replacement groups independently.
    """

    selected: list[tuple[str, M01MRaceVariantReplacementOption]] = []
    data = _variant_data(variant)
    for group in data.replacement_groups:
        choice_id = _replacement_choice_id(variant.key, group.id)
        selection = draft.draft_payload.choice_selections.get(choice_id)
        if selection is None or len(selection.selected_option_ids) != 1:
            continue
        selected_id = selection.selected_option_ids[0]
        option = next((item for item in group.options if item.id == selected_id), None)
        if option is not None:
            selected.append((group.id, option))
    return tuple(selected)


def _spell_choice_options(
    registry: ContentRegistry,
    option: M01MRaceVariantReplacementOption,
) -> tuple[BuilderChoiceOption, ...]:
    spell_choice = option.spell_choice
    if spell_choice is None:
        return ()
    class_ref = _reference_key(spell_choice.class_, kinds={"class"})
    if class_ref is None:
        return ()
    result: list[BuilderChoiceOption] = []
    for spell in registry.list_kind("spell"):
        if spell.data.get("level") != spell_choice.level:
            continue
        if not spell_is_on_class_list(spell.key, class_ref, registry):
            continue
        source_label = spell.source_label or spell.source
        result.append(
            BuilderChoiceOption(
                option_id=spell.key,
                label=f"{spell.name} · {source_label}",
                kind=BuilderOptionKind.REFERENCE,
                reference_id=spell.key,
            )
        )
    return tuple(result)


def build_race_variant_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[BuilderChoice, ...]:
    eligible = _eligible_variant_entries(draft, registry)
    if not eligible:
        return ()

    selected_ref = (
        draft.draft_payload.race_variant_selection.reference_id
        if draft.draft_payload.race_variant_selection is not None
        else None
    )
    choices: list[BuilderChoice] = [
        BuilderChoice(
            choice_id=deterministic_choice_id("draft", "race-variant-selection"),
            label="Ancestry variant (optional)",
            required=False,
            choose_count=1,
            option_source=RACE_VARIANT_OPTION_SOURCE,
            options=tuple(
                BuilderChoiceOption(
                    option_id=entry.key,
                    label=f"{entry.name} · {entry.source_label or entry.source}",
                    kind=BuilderOptionKind.REFERENCE,
                    reference_id=entry.key,
                )
                for entry in eligible
            ),
            selected_option_ids=((selected_ref,) if selected_ref is not None else ()),
        )
    ]

    variant = _variant_entry(draft, registry)
    if variant is None:
        return tuple(choices)
    data = _variant_data(variant)
    for group in data.replacement_groups:
        choice_id = _replacement_choice_id(variant.key, group.id)
        selection = draft.draft_payload.choice_selections.get(choice_id)
        selected_ids = selection.selected_option_ids if selection is not None else ()
        choices.append(
            BuilderChoice(
                choice_id=choice_id,
                label=group.label,
                source_ref=variant.key,
                required=True,
                choose_count=group.choose,
                option_source=RACE_VARIANT_REPLACEMENT_OPTION_SOURCE,
                options=tuple(
                    BuilderChoiceOption(
                        option_id=option.id,
                        label=option.label,
                        kind=BuilderOptionKind.BRANCH,
                        branch_key=option.id,
                    )
                    for option in group.options
                ),
                selected_option_ids=selected_ids,
            )
        )

        if len(selected_ids) != 1:
            continue
        active = next(
            (option for option in group.options if option.id == selected_ids[0]),
            None,
        )
        if active is None or active.spell_choice is None:
            continue
        spell_choice_id = _spell_choice_id(variant.key, group.id, active.id)
        spell_selection = draft.draft_payload.choice_selections.get(spell_choice_id)
        choices.append(
            BuilderChoice(
                choice_id=spell_choice_id,
                label=active.spell_choice.label,
                source_ref=variant.key,
                required=True,
                choose_count=active.spell_choice.choose,
                option_source=RACE_VARIANT_SPELL_OPTION_SOURCE,
                options=_spell_choice_options(registry, active),
                selected_option_ids=(
                    spell_selection.selected_option_ids
                    if spell_selection is not None
                    else ()
                ),
            )
        )
    return tuple(choices)


def suppress_replaced_foundation_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
) -> tuple[BuilderChoice, ...]:
    variant = _variant_entry(draft, registry)
    if variant is None:
        return choices
    selected = _selected_options(draft, variant)
    if not selected:
        return choices

    data = _variant_data(variant)
    active_groups = {group_id for group_id, option in selected if not option.keep_target}
    target_refs = {
        _reference_key(rule.target_reference)
        for rule in data.replacement_rules
        if rule.replacement_group_id in active_groups and rule.action == "remove"
    }
    target_refs.discard(None)
    if not target_refs:
        return choices
    return tuple(
        choice
        for choice in choices
        if not (
            choice.source_ref in target_refs
            or any(choice.choice_id.startswith(f"{target_ref}:") for target_ref in target_refs)
        )
    )


def _grant_identity(grant: BuilderGrantSummary) -> str | None:
    if grant.reference_id is None:
        return None
    try:
        index = parse_stable_key(grant.reference_id).index
    except ValueError:
        return None
    return f"grant:{grant.source_ref}:{index}"


def _grant_from_reference(
    variant: ContentEntry,
    reference: object,
    registry: ContentRegistry,
) -> BuilderGrantSummary | None:
    key = _reference_key(reference)
    if key is None:
        return None
    target = registry.get_optional(key)
    if target is None:
        return None
    return BuilderGrantSummary(
        label=target.name,
        kind=parse_stable_key(key).kind,
        source_ref=variant.key,
        reference_id=key,
    )


def _selected_spell_grant(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
    variant: ContentEntry,
    group_id: str,
    option: M01MRaceVariantReplacementOption,
) -> BuilderGrantSummary | None:
    if option.spell_choice is None:
        return None
    choice_id = _spell_choice_id(variant.key, group_id, option.id)
    active_choice = next((choice for choice in choices if choice.choice_id == choice_id), None)
    selection = draft.draft_payload.choice_selections.get(choice_id)
    if active_choice is None or selection is None or len(selection.selected_option_ids) != 1:
        return None
    selected_id = selection.selected_option_ids[0]
    option_by_id = {item.option_id: item for item in active_choice.options}
    selected = option_by_id.get(selected_id)
    if selected is None or selected.reference_id is None:
        return None
    spell = registry.get_optional(selected.reference_id)
    if spell is None:
        return None
    return BuilderGrantSummary(
        label=spell.name,
        kind="spell",
        source_ref=variant.key,
        reference_id=spell.key,
    )


def _ability_index(raw_bonus: object) -> str | None:
    if not isinstance(raw_bonus, dict):
        return None
    raw_ability = raw_bonus.get("ability_score")
    if not isinstance(raw_ability, dict):
        return None
    key = raw_ability.get("key")
    if isinstance(key, str):
        try:
            return parse_stable_key(key).index
        except ValueError:
            pass
    index = raw_ability.get("index")
    return index if isinstance(index, str) else None


def _base_racial_ability_bonuses(
    variant: ContentEntry,
    registry: ContentRegistry,
) -> dict[str, int]:
    base_ref = _base_race_ref(_variant_data(variant))
    race = registry.get_optional(base_ref or "")
    if race is None:
        return {}
    result: dict[str, int] = {}
    raw_bonuses = race.data.get("ability_bonuses")
    if not isinstance(raw_bonuses, list):
        return result
    for raw in raw_bonuses:
        if not isinstance(raw, dict) or not isinstance(raw.get("bonus"), int):
            continue
        ability = _ABILITY_INDEX_TO_NAME.get(_ability_index(raw) or "")
        if ability is not None:
            result[ability] = int(raw["bonus"])
    return result


def _apply_replacement_ability_bonuses(
    summary: BuilderResolvedSummary,
    variant: ContentEntry,
    option: M01MRaceVariantReplacementOption,
    registry: ContentRegistry,
) -> BuilderResolvedSummary:
    replacement = option.replacement_ability_bonuses
    if replacement is None or not summary.ability_scores:
        return summary
    base = _base_racial_ability_bonuses(variant, registry)
    next_bonus = {entry.ability: entry.bonus for entry in replacement}
    scores = []
    for score in summary.ability_scores:
        delta = next_bonus.get(score.ability, 0) - base.get(score.ability, 0)
        resolved = score.resolved + delta
        scores.append(
            score.model_copy(
                update={
                    "permanent_bonus": score.permanent_bonus + delta,
                    "resolved": resolved,
                    "effective": score.effective if score.overridden else resolved,
                }
            )
        )
    return summary.model_copy(update={"ability_scores": tuple(scores)})


def apply_race_variant_summary(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
    summary: BuilderResolvedSummary,
) -> BuilderResolvedSummary:
    variant = _variant_entry(draft, registry)
    if variant is None:
        return summary

    result = summary.model_copy(
        update={
            "race_variant_name": variant.name,
            "selected_reference_count": summary.selected_reference_count + 1,
        }
    )
    selected = _selected_options(draft, variant)
    if not selected:
        return result

    data = _variant_data(variant)
    grants = list(result.grants)
    for group_id, option in selected:
        result = _apply_replacement_ability_bonuses(result, variant, option, registry)
        if option.keep_target:
            continue
        target_grant_ids = {
            rule.target_grant_id
            for rule in data.replacement_rules
            if rule.replacement_group_id == group_id and rule.action == "remove"
        }
        grants = [grant for grant in grants if _grant_identity(grant) not in target_grant_ids]
        for reference in option.grants:
            grant = _grant_from_reference(variant, reference, registry)
            if grant is not None:
                grants.append(grant)
        spell_grant = _selected_spell_grant(
            draft, registry, choices, variant, group_id, option
        )
        if spell_grant is not None:
            grants.append(spell_grant)

    deduped: list[BuilderGrantSummary] = []
    seen: set[tuple[str, str | None]] = set()
    for grant in grants:
        identity = (grant.kind, grant.reference_id)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(grant)
    return result.model_copy(update={"grants": tuple(deduped)})


def validate_race_variant(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[BuilderIssue, ...]:
    selection = draft.draft_payload.race_variant_selection
    if selection is None:
        return ()
    entry = registry.get_optional(selection.reference_id)
    if entry is None:
        return (
            BuilderIssue(
                code="unknown_reference",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="draft_payload.race_variant_selection.reference_id",
                message=f"Unknown race-variant reference: {selection.reference_id}",
                related_refs=(selection.reference_id,),
            ),
        )
    if not stable_key_is_kind(entry.key, "race-variant"):
        return (
            BuilderIssue(
                code="wrong_reference_kind",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="draft_payload.race_variant_selection.reference_id",
                message=(
                    "Expected a race-variant reference, got "
                    f"{selection.reference_id}"
                ),
                related_refs=(selection.reference_id,),
            ),
        )
    race = draft.draft_payload.race_selection
    expected_race = _base_race_ref(_variant_data(entry))
    if race is None or expected_race != race.reference_id:
        related = tuple(
            ref for ref in (race.reference_id if race is not None else None, entry.key) if ref
        )
        return (
            BuilderIssue(
                code="race_variant_race_mismatch",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path="draft_payload.race_variant_selection.reference_id",
                message="Selected ancestry variant does not belong to the selected race.",
                related_refs=related,
            ),
        )
    return ()


def _spell_entry_id(feature_ref: str, spell_ref: str) -> str:
    digest = sha256(f"{feature_ref}|{spell_ref}".encode("utf-8")).hexdigest()[:20]
    return f"race-variant:{digest}:granted"


def _apply_movement_grants(
    speeds: dict[str, int | None], raw_grants: object
) -> None:
    if not isinstance(raw_grants, list):
        return
    # Only unconditional speeds belong in the immutable Build. A conditional
    # grant is not true for every Current State, so it stays typed content
    # metadata and is resolved by effective_movement() at read time.
    for raw in raw_grants:
        movement = ConditionalMovementGrantData.model_validate(raw)
        if movement.condition is not None:
            continue
        speeds[movement.mode] = movement.speed


def _base_origin_speeds(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> dict[str, int | None]:
    speeds: dict[str, int | None] = {
        "walk": None,
        "swim": None,
        "climb": None,
        "fly": None,
    }
    race_selection = draft.draft_payload.race_selection
    race = (
        registry.get_optional(race_selection.reference_id)
        if race_selection is not None
        else None
    )
    if race is None or not stable_key_is_kind(race.key, "race"):
        return speeds

    base_speed = race.data.get("speed")
    if isinstance(base_speed, int) and base_speed > 0:
        speeds["walk"] = base_speed
    _apply_movement_grants(speeds, race.data.get("movement_grants"))

    subrace_selection = draft.draft_payload.subrace_selection
    subrace = (
        registry.get_optional(subrace_selection.reference_id)
        if subrace_selection is not None
        else None
    )
    if subrace is None or not stable_key_is_kind(subrace.key, "subrace"):
        return speeds
    parent = subrace.data.get("race")
    try:
        parent_ref = (
            reference_to_stable_key(parent, kinds={"race"})
            if isinstance(parent, dict)
            else None
        )
    except ValueError:
        parent_ref = None
    if parent_ref == race.key:
        _apply_movement_grants(speeds, subrace.data.get("movement_grants"))
    return speeds


def compile_race_variant(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
) -> RaceVariantCompilation:
    # Base race -> subrace -> every selected race-variant replacement group.
    # Conditions remain typed content metadata; the Character Sheet resolves
    # equipment-dependent effective movement from live Current State.
    speeds = _base_origin_speeds(draft, registry)
    variant = _variant_entry(draft, registry)
    if variant is None:
        return RaceVariantCompilation(
            walking_speed=speeds["walk"],
            swim_speed=speeds["swim"],
            climb_speed=speeds["climb"],
            fly_speed=speeds["fly"],
        )

    selected = _selected_options(draft, variant)
    group_selections = tuple(
        RaceVariantGroupSelection(
            race_variant_ref=variant.key,
            replacement_group_id=group_id,
            selected_option_id=option.id,
        )
        for group_id, option in selected
    )
    spell_entries: list[SpellAccessEntry] = []
    for group_id, option in selected:
        if option.keep_target:
            continue
        for movement in option.movement:
            if movement.condition is not None:
                continue
            speeds[movement.mode] = movement.speed
        if option.spell_choice is None:
            continue
        spell_choice_id = _spell_choice_id(variant.key, group_id, option.id)
        active_choice = next(
            (choice for choice in choices if choice.choice_id == spell_choice_id),
            None,
        )
        selection = draft.draft_payload.choice_selections.get(spell_choice_id)
        if active_choice is None or selection is None:
            continue
        option_by_id = {item.option_id: item for item in active_choice.options}
        for selected_id in selection.selected_option_ids:
            selected_spell = option_by_id.get(selected_id)
            if selected_spell is None or selected_spell.reference_id is None:
                continue
            feature_ref = _reference_key(option.spell_choice.feature, kinds={"feature"})
            if feature_ref is None:
                continue
            spell_entries.append(
                SpellAccessEntry(
                    entry_id=_spell_entry_id(feature_ref, selected_spell.reference_id),
                    spell_key=selected_spell.reference_id,
                    source_type="race",
                    source_key=feature_ref,
                    access_type="granted",
                    casting_ability=option.spell_choice.casting_ability,
                )
            )

    return RaceVariantCompilation(
        race_variant_ref=variant.key,
        group_selections=group_selections,
        walking_speed=speeds["walk"],
        swim_speed=speeds["swim"],
        climb_speed=speeds["climb"],
        fly_speed=speeds["fly"],
        spell_access_entries=tuple(spell_entries),
    )
