from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from hashlib import sha1
from typing import Any, Iterable

from app.content.identity import parse_stable_key, reference_to_stable_key, stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry
from app.domain.character.schemas import (
    CharacterBuild,
    FeatureGrantSource,
    SpellAccessEntry,
    SpellResourcePool,
    SpellSlotCapacity,
    SpellcastingProfile,
)
from app.domain.character_builder.m01j_subclasses import (
    M01JSubclassRuntime as BaseM01JSubclassRuntime,
    apply_m01j_subclass_runtime as apply_base_m01j_subclass_runtime,
    m01j_choice_id,
    prepare_m01j_subclasses as prepare_base_m01j_subclasses,
)
from app.domain.character_builder.rules import caster_level_contribution, load_spellcasting_rules
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderOptionKind,
    BuilderResolvedSummary,
    BuilderSpellAccessModel,
    BuilderSpellChoiceInput,
    BuilderSpellOptionSummary,
    BuilderSpellResourcePoolSummary,
    BuilderSpellResourcePoolType,
    BuilderSpellSlotCapacity,
    BuilderSpellcastingProfileSummary,
)


@dataclass(frozen=True)
class GrantSelection:
    subclass_ref: str
    source_ref: str
    grant_target: str
    access_type: str | None
    refs: tuple[str, ...]


@dataclass(frozen=True)
class ThirdCasterCompilation:
    profiles: tuple[BuilderSpellcastingProfileSummary, ...]
    spell_access_entries: tuple[SpellAccessEntry, ...]
    issues: tuple[BuilderIssue, ...]
    contributions: tuple[tuple[str, int], ...]
    local_slot_rows: tuple[tuple[str, tuple[int, ...]], ...]


@dataclass(frozen=True)
class M01JSubclassRuntime:
    base: BaseM01JSubclassRuntime
    registry: ContentRegistry
    choices: tuple[BuilderChoice, ...]
    issues: tuple[BuilderIssue, ...]
    grant_selections: tuple[GrantSelection, ...]
    fixed_grants: tuple[tuple[str, dict[str, tuple[str, ...]]], ...]
    fixed_feature_refs: tuple[str, ...]
    third_casters: ThirdCasterCompilation


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
    selected: dict[str, str] = {}
    for level in draft.draft_payload.level_choices:
        levels[level.class_ref] += 1
        if level.subclass_ref is not None:
            selected[level.class_ref] = level.subclass_ref
    return levels, selected


def _choice_total(raw: dict[str, Any], class_level: int) -> int:
    value = raw.get("choose_total")
    result = value if isinstance(value, int) and value >= 1 else 1
    progression = raw.get("progression")
    if isinstance(progression, (list, tuple)):
        for step in progression:
            if not isinstance(step, dict):
                continue
            threshold = step.get("class_level")
            total = step.get("choose_total")
            if isinstance(threshold, int) and isinstance(total, int) and threshold <= class_level:
                result = total
    return result


def _entry_label(entry: Any) -> str:
    return f"{entry.name} · {entry.source_label or entry.source}"


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
    value = raw.get("index")
    return value if isinstance(value, str) else None


def _proficiency_weapon(registry: ContentRegistry, entry: Any) -> Any | None:
    if not stable_key_is_kind(entry.key, "proficiency") or entry.data.get("type") != "Weapons":
        return None
    reference = entry.data.get("reference")
    if not isinstance(reference, dict):
        return None
    try:
        target = reference_to_stable_key(reference, kinds={"equipment"})
    except ValueError:
        return None
    return registry.get_optional(target) if target is not None else None


def _weapon_property_indices(equipment: Any) -> set[str]:
    raw = equipment.data.get("properties")
    if not isinstance(raw, list):
        return set()
    result: set[str] = set()
    for reference in raw:
        if not isinstance(reference, dict):
            continue
        key = reference.get("key")
        index = reference.get("index")
        if isinstance(key, str):
            try:
                result.add(parse_stable_key(key).index)
            except ValueError:
                pass
        elif isinstance(index, str):
            result.add(index)
    return result


def _weapon_options(registry: ContentRegistry, pool: str) -> tuple[Any, ...]:
    result: list[Any] = []
    seen_targets: set[str] = set()
    for proficiency in registry.list_kind("proficiency"):
        equipment = _proficiency_weapon(registry, proficiency)
        if equipment is None:
            continue
        category = equipment.data.get("weapon_category")
        if category not in {"Simple", "Martial"}:
            continue
        weapon_range = equipment.data.get("weapon_range")
        properties = _weapon_property_indices(equipment)
        is_longbow = equipment.index == "longbow"
        if pool.startswith("kensei_") and (("Heavy" in properties or "heavy" in properties) and not is_longbow):
            continue
        if pool.startswith("kensei_") and ("Special" in properties or "special" in properties):
            continue
        if pool == "kensei_melee_weapons" and weapon_range != "Melee":
            continue
        if pool == "kensei_ranged_weapons" and weapon_range != "Ranged":
            continue
        if pool == "one_handed_melee_weapons":
            if weapon_range != "Melee":
                continue
            if "Two-Handed" in properties or "two-handed" in properties:
                continue
        target_identity = equipment.key
        if target_identity in seen_targets:
            continue
        seen_targets.add(target_identity)
        result.append(proficiency)
    return tuple(sorted(result, key=lambda entry: (entry.name, entry.key)))


def _pool_entries(registry: ContentRegistry, pool: str) -> tuple[Any, ...]:
    if pool == "all_languages":
        return registry.list_kind("language")
    if pool == "artisans_tools":
        return tuple(
            entry
            for entry in registry.list_kind("proficiency")
            if entry.data.get("type") == "Artisan's Tools"
        )
    if pool == "gaming_sets":
        return tuple(
            entry
            for entry in registry.list_kind("proficiency")
            if entry.data.get("type") == "Gaming Sets"
        )
    if pool in {"kensei_melee_weapons", "kensei_ranged_weapons", "kensei_any_weapons", "one_handed_melee_weapons"}:
        return _weapon_options(registry, pool)
    if pool in {"wizard_cantrips", "druid_cantrips"}:
        class_ref = (
            "srd5.1:class:wizard" if pool == "wizard_cantrips" else "srd5.1:class:druid"
        )
        return tuple(
            spell
            for spell in registry.list_kind("spell")
            if spell.data.get("level") == 0 and _spell_on_class_list(registry, spell, class_ref)
        )
    return ()


def _grant_choice_options(
    registry: ContentRegistry,
    raw: dict[str, Any],
) -> tuple[BuilderChoiceOption, ...]:
    refs: list[str] = [
        ref for ref in raw.get("option_refs", ()) if isinstance(ref, str)
    ]
    pool = raw.get("option_pool")
    if isinstance(pool, str):
        refs.extend(entry.key for entry in _pool_entries(registry, pool))
    result: list[BuilderChoiceOption] = []
    for ref in dict.fromkeys(refs):
        entry = registry.get_optional(ref)
        if entry is None:
            continue
        result.append(
            BuilderChoiceOption(
                option_id=ref,
                label=_entry_label(entry),
                kind=BuilderOptionKind.REFERENCE,
                reference_id=ref,
                category=str(raw.get("grant_target") or "subclass_grant"),
            )
        )
    return tuple(result)


def _active_grant_choice_specs(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[tuple[str, str, int, dict[str, Any]], ...]:
    class_levels, selected = _class_state(draft)
    result: list[tuple[str, str, int, dict[str, Any]]] = []
    for class_ref, subclass_ref in selected.items():
        subclass = registry.get_optional(subclass_ref)
        if subclass is None:
            continue
        class_level = class_levels[class_ref]
        raw_choices = subclass.data.get("grant_choices", [])
        if not isinstance(raw_choices, list):
            continue
        for raw in raw_choices:
            if not isinstance(raw, dict):
                continue
            minimum = raw.get("minimum_class_level")
            choice_key = raw.get("choice_key")
            if not isinstance(minimum, int) or minimum > class_level or not isinstance(choice_key, str):
                continue
            result.append((subclass_ref, choice_key, class_level, raw))
    return tuple(result)


def _without_grant_choice_selections(
    draft: BuilderDraft,
    grant_choice_ids: set[str],
) -> BuilderDraft:
    if not grant_choice_ids:
        return draft
    selections = {
        key: value
        for key, value in draft.draft_payload.choice_selections.items()
        if key not in grant_choice_ids
    }
    if len(selections) == len(draft.draft_payload.choice_selections):
        return draft
    payload = draft.draft_payload.model_copy(update={"choice_selections": selections})
    return draft.model_copy(update={"draft_payload": payload})


def _legalize_base_feature_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    base: BaseM01JSubclassRuntime,
    class_levels: Counter[str],
    selected_subclasses: dict[str, str],
) -> tuple[BaseM01JSubclassRuntime, tuple[BuilderChoice, ...], tuple[BuilderIssue, ...]]:
    raw_by_choice_id: dict[str, tuple[int, dict[str, Any]]] = {}
    for class_ref, subclass_ref in selected_subclasses.items():
        subclass = registry.get_optional(subclass_ref)
        if subclass is None:
            continue
        raw_choices = subclass.data.get("persistent_choices", [])
        if not isinstance(raw_choices, list):
            continue
        for raw in raw_choices:
            if not isinstance(raw, dict) or not isinstance(raw.get("choice_key"), str):
                continue
            raw_by_choice_id[m01j_choice_id(subclass_ref, raw["choice_key"])] = (
                class_levels[class_ref],
                raw,
            )

    legal_selected_refs: set[str] = set()
    next_choices: list[BuilderChoice] = []
    issues: list[BuilderIssue] = []
    for choice in base.choices:
        detail = raw_by_choice_id.get(choice.choice_id)
        if detail is None:
            next_choices.append(choice)
            continue
        class_level, raw = detail
        raw_minimums = raw.get("option_minimum_levels", {})
        minimums = raw_minimums if isinstance(raw_minimums, dict) else {}
        options: list[BuilderChoiceOption] = []
        for option in choice.options:
            required = minimums.get(option.option_id, 1)
            if isinstance(required, int) and required > class_level:
                options.append(
                    option.model_copy(
                        update={
                            "disabled_reason": f"Requires class level {required}.",
                            "disabled_reason_code": "subclass_option_class_level_required",
                            "disabled_reason_params": {"required_class_level": required},
                        }
                    )
                )
                if option.option_id in choice.selected_option_ids:
                    issues.append(
                        _issue(
                            "subclass_option_class_level_not_met",
                            f"draft_payload.choice_selections.{choice.choice_id}",
                            f"A selected subclass option requires class level {required}.",
                            option.option_id,
                        )
                    )
                continue
            options.append(option)
            if option.option_id in choice.selected_option_ids:
                legal_selected_refs.add(option.option_id)
        next_choices.append(choice.model_copy(update={"options": tuple(options)}))

    filtered_refs = tuple(
        ref for ref in base.selected_option_feature_refs if ref in legal_selected_refs
    )
    filtered_sources = tuple(
        row for row in base.selected_feature_sources if row[0] in legal_selected_refs
    )
    return (
        replace(
            base,
            choices=tuple(next_choices),
            selected_option_feature_refs=filtered_refs,
            selected_feature_sources=filtered_sources,
        ),
        tuple(next_choices),
        tuple(issues),
    )


def _third_profile_id(subclass_ref: str) -> str:
    parsed = parse_stable_key(subclass_ref, kinds={"subclass"})
    return f"subclass:{parsed.source}:{parsed.index}"


def _max_slot_level(slots: tuple[int, ...]) -> int:
    return max((index for index, count in enumerate(slots, start=1) if count > 0), default=0)


def _third_caster_available_spells(
    registry: ContentRegistry,
    *,
    spell_class_ref: str,
    max_level: int,
) -> tuple[Any, ...]:
    return tuple(
        spell
        for spell in registry.list_kind("spell")
        if isinstance(spell.data.get("level"), int)
        and 0 <= int(spell.data["level"]) <= max_level
        and _spell_on_class_list(registry, spell, spell_class_ref)
    )


def _third_acquisition_opportunities(rows: dict[int, dict[str, Any]], class_level: int) -> list[int]:
    opportunities: list[int] = []
    previous_known = 0
    started = False
    for level in range(1, class_level + 1):
        row = rows.get(level)
        if row is None:
            continue
        known = int(row.get("spells_known", 0))
        slots = tuple(int(value) for value in row.get("slots", ()))
        max_level = _max_slot_level(slots)
        gained = max(0, known - previous_known)
        opportunities.extend([max_level] * gained)
        if started and previous_known > 0:
            opportunities.append(max_level)
        previous_known = known
        started = True
    return opportunities


def _validate_third_acquisition(
    registry: ContentRegistry,
    selected: tuple[str, ...],
    opportunities: list[int],
    path: str,
) -> tuple[BuilderIssue, ...]:
    available = sorted(opportunities, reverse=True)
    selected_levels: list[tuple[int, str]] = []
    for ref in selected:
        spell = registry.get_optional(ref)
        level = spell.data.get("level") if spell is not None else None
        if isinstance(level, int) and level > 0:
            selected_levels.append((level, ref))
    for level, ref in sorted(selected_levels, reverse=True):
        match = next((i for i, maximum in enumerate(available) if maximum >= level), None)
        if match is None:
            return (
                _issue(
                    "impossible_subclass_spell_acquisition_order",
                    path,
                    "The final subclass spell selection cannot be produced by legal level-by-level acquisition/replacement.",
                    ref,
                ),
            )
        available.pop(match)
    return ()


def _third_spell_entry_id(subclass_ref: str, spell_ref: str, access_type: str) -> str:
    digest = sha1(f"{subclass_ref}|{spell_ref}|{access_type}".encode("utf-8")).hexdigest()[:10]
    parsed = parse_stable_key(subclass_ref)
    spell = parse_stable_key(spell_ref)
    return f"m01j:{parsed.index}:{access_type}:{spell.index}:{digest}"[:120]


def _compile_third_casters(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> ThirdCasterCompilation:
    class_levels, selected_subclasses = _class_state(draft)
    profiles: list[BuilderSpellcastingProfileSummary] = []
    entries: list[SpellAccessEntry] = []
    issues: list[BuilderIssue] = []
    contributions: list[tuple[str, int]] = []
    local_rows: list[tuple[str, tuple[int, ...]]] = []
    live_profile_ids: set[str] = set()

    for class_ref, subclass_ref in selected_subclasses.items():
        subclass = registry.get_optional(subclass_ref)
        if subclass is None:
            continue
        spec = subclass.data.get("subclass_spellcasting")
        if not isinstance(spec, dict):
            continue
        class_level = class_levels[class_ref]
        raw_rows = spec.get("rows")
        if not isinstance(raw_rows, dict):
            continue
        row = raw_rows.get(class_level) or raw_rows.get(str(class_level))
        if not isinstance(row, dict):
            continue
        spell_class_ref = spec.get("spell_class_ref")
        ability = spec.get("ability")
        if not isinstance(spell_class_ref, str) or not isinstance(ability, str):
            continue
        slots = tuple(int(value) for value in row.get("slots", ()))
        if len(slots) != 4:
            issues.append(
                _issue(
                    "subclass_spellcasting_rules_data_error",
                    "content",
                    f"{subclass.name} has an invalid spell-slot row.",
                    subclass_ref,
                )
            )
            continue
        max_level = _max_slot_level(slots)
        profile_id = _third_profile_id(subclass_ref)
        live_profile_ids.add(profile_id)
        selection = draft.draft_payload.spell_choices.get(profile_id, BuilderSpellChoiceInput())
        fixed_cantrips = tuple(
            ref for ref in spec.get("fixed_cantrip_refs", ()) if isinstance(ref, str)
        )
        total_cantrips = int(row.get("cantrips_known", 0))
        selectable_cantrips = max(0, total_cantrips - len(fixed_cantrips))
        known_count = int(row.get("spells_known", 0))
        available = _third_caster_available_spells(
            registry,
            spell_class_ref=spell_class_ref,
            max_level=max_level,
        )
        available_keys = {spell.key for spell in available}
        path = f"draft_payload.spell_choices.{profile_id}"

        if len(selection.cantrip_keys) != selectable_cantrips:
            issues.append(
                _issue(
                    "invalid_subclass_cantrip_choice_count",
                    f"{path}.cantrip_keys",
                    f"{subclass.name} requires exactly {selectable_cantrips} selectable cantrips; got {len(selection.cantrip_keys)}.",
                    subclass_ref,
                )
            )
        if len(selection.known_spell_keys) != known_count:
            issues.append(
                _issue(
                    "invalid_subclass_spell_choice_count",
                    f"{path}.known_spell_keys",
                    f"{subclass.name} requires exactly {known_count} known leveled spells; got {len(selection.known_spell_keys)}.",
                    subclass_ref,
                )
            )

        for ref in (*selection.cantrip_keys, *selection.known_spell_keys):
            spell = registry.get_optional(ref)
            if spell is None or ref not in available_keys:
                issues.append(
                    _issue(
                        "subclass_spell_not_on_source_list",
                        path,
                        "A selected subclass spell is not on the required source spell list.",
                        subclass_ref,
                        ref,
                    )
                )
                continue
            level = spell.data.get("level")
            if ref in selection.cantrip_keys and level != 0:
                issues.append(
                    _issue(
                        "invalid_subclass_cantrip_level",
                        f"{path}.cantrip_keys",
                        "Subclass cantrip selections must be level 0 spells.",
                        ref,
                    )
                )
            if ref in selection.known_spell_keys and (
                not isinstance(level, int) or level < 1 or level > max_level
            ):
                issues.append(
                    _issue(
                        "invalid_subclass_spell_level",
                        f"{path}.known_spell_keys",
                        "A selected subclass spell exceeds the subclass's current spell level.",
                        ref,
                    )
                )
        duplicate_fixed = set(fixed_cantrips).intersection(selection.cantrip_keys)
        if duplicate_fixed:
            issues.append(
                _issue(
                    "duplicate_fixed_subclass_cantrip",
                    f"{path}.cantrip_keys",
                    "A fixed subclass cantrip must not also occupy a selectable cantrip slot.",
                    *sorted(duplicate_fixed),
                )
            )

        allowed_schools = {
            value for value in spec.get("school_indices", ()) if isinstance(value, str)
        }
        unrestricted_slots = 0
        for threshold in (3, 8, 14, 20):
            if class_level >= threshold:
                unrestricted_slots += 1
        off_school = tuple(
            ref
            for ref in selection.known_spell_keys
            if (
                (spell := registry.get_optional(ref)) is not None
                and _spell_school_index(spell) not in allowed_schools
            )
        )
        if len(off_school) > unrestricted_slots:
            issues.append(
                _issue(
                    "subclass_spell_school_limit_exceeded",
                    f"{path}.known_spell_keys",
                    f"{subclass.name} allows at most {unrestricted_slots} known spells outside its restricted schools at this class level.",
                    *off_school,
                )
            )

        numeric_rows = {
            int(level): value
            for level, value in raw_rows.items()
            if (isinstance(level, int) or (isinstance(level, str) and level.isdigit()))
            and isinstance(value, dict)
        }
        issues.extend(
            _validate_third_acquisition(
                registry,
                selection.known_spell_keys,
                _third_acquisition_opportunities(numeric_rows, class_level),
                f"{path}.known_spell_keys",
            )
        )

        for ref in fixed_cantrips:
            if registry.get_optional(ref) is not None:
                entries.append(
                    SpellAccessEntry(
                        entry_id=_third_spell_entry_id(subclass_ref, ref, "granted"),
                        spell_key=ref,
                        source_type="subclass",
                        source_key=subclass_ref,
                        access_type="granted",
                    )
                )
        for ref in (*selection.cantrip_keys, *selection.known_spell_keys):
            if registry.get_optional(ref) is not None:
                entries.append(
                    SpellAccessEntry(
                        entry_id=_third_spell_entry_id(subclass_ref, ref, "known"),
                        spell_key=ref,
                        source_type="subclass",
                        source_key=subclass_ref,
                        access_type="known",
                    )
                )

        profiles.append(
            BuilderSpellcastingProfileSummary(
                profile_id=profile_id,
                source_type="subclass",
                source_key=subclass_ref,
                source_name=subclass.name,
                class_ref=class_ref,
                ability=ability,
                access_model=BuilderSpellAccessModel.KNOWN,
                class_level=class_level,
                max_spell_level=max_level,
                cantrip_count=selectable_cantrips,
                known_spell_count=known_count,
                spellbook_count=0,
                prepared_limit=None,
                resource_pool_type=BuilderSpellResourcePoolType.NORMAL_MULTICLASS_SLOTS,
                available_spells=tuple(
                    BuilderSpellOptionSummary(
                        spell_key=spell.key,
                        name=_entry_label(spell),
                        level=int(spell.data["level"]),
                    )
                    for spell in sorted(
                        available,
                        key=lambda item: (int(item.data["level"]), item.name, item.key),
                    )
                ),
                selected_cantrip_keys=selection.cantrip_keys,
                selected_known_spell_keys=selection.known_spell_keys,
                selected_spellbook_spell_keys=(),
                selected_prepared_spell_keys=(),
            )
        )
        contributions.append((class_ref, class_level // 3))
        local_rows.append((profile_id, slots))

    for profile_id in draft.draft_payload.spell_choices:
        if profile_id.startswith("subclass:phb2014:") and profile_id not in live_profile_ids:
            issues.append(
                _issue(
                    "invalid_subclass_spell_profile",
                    f"draft_payload.spell_choices.{profile_id}",
                    "This subclass spell selection belongs to a spellcasting subclass that is not active.",
                )
            )

    return ThirdCasterCompilation(
        profiles=tuple(profiles),
        spell_access_entries=tuple({entry.entry_id: entry for entry in entries}.values()),
        issues=tuple(issues),
        contributions=tuple(contributions),
        local_slot_rows=tuple(local_rows),
    )


def prepare_m01j_subclasses(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> M01JSubclassRuntime:
    class_levels, selected_subclasses = _class_state(draft)
    grant_specs = _active_grant_choice_specs(draft, registry)
    grant_choice_ids = {
        m01j_choice_id(subclass_ref, choice_key)
        for subclass_ref, choice_key, _level, _raw in grant_specs
    }
    base = prepare_base_m01j_subclasses(
        _without_grant_choice_selections(draft, grant_choice_ids),
        registry,
    )
    base, feature_choices, feature_issues = _legalize_base_feature_choices(
        draft,
        registry,
        base,
        class_levels,
        selected_subclasses,
    )

    choices: list[BuilderChoice] = list(feature_choices)
    issues: list[BuilderIssue] = [*base.issues, *feature_issues]
    grants: list[GrantSelection] = []
    active_ids: set[str] = {choice.choice_id for choice in feature_choices}
    selected_global: dict[tuple[str, str], str] = {}

    for subclass_ref, choice_key, class_level, raw in grant_specs:
        choice_id = m01j_choice_id(subclass_ref, choice_key)
        active_ids.add(choice_id)
        options = _grant_choice_options(registry, raw)
        legal = {option.option_id: option for option in options}
        selection = draft.draft_payload.choice_selections.get(choice_id)
        selected = selection.selected_option_ids if selection is not None else ()
        choose_total = _choice_total(raw, class_level)
        choices.append(
            BuilderChoice(
                choice_id=choice_id,
                label=str(raw.get("label") or registry.get(subclass_ref).name),
                source_ref=subclass_ref,
                required=True,
                choose_count=choose_total,
                option_source="content:m01-j-subclass-grant",
                options=options,
                selected_option_ids=selected,
            )
        )
        if len(selected) != choose_total:
            issues.append(
                _issue(
                    "invalid_subclass_grant_choice_count",
                    f"draft_payload.choice_selections.{choice_id}",
                    f"This subclass grant requires exactly {choose_total} selections; got {len(selected)}.",
                    subclass_ref,
                )
            )
        if len(selected) != len(set(selected)):
            issues.append(
                _issue(
                    "duplicate_subclass_grant_choice",
                    f"draft_payload.choice_selections.{choice_id}",
                    "Subclass grant choices cannot contain duplicate options.",
                    subclass_ref,
                )
            )
        illegal = tuple(ref for ref in selected if ref not in legal)
        if illegal:
            issues.append(
                _issue(
                    "illegal_subclass_grant_choice",
                    f"draft_payload.choice_selections.{choice_id}",
                    "A selected subclass grant option is unavailable.",
                    subclass_ref,
                    *illegal,
                )
            )
        grant_target = str(raw.get("grant_target") or "")
        selected_legal = tuple(ref for ref in selected if ref in legal)
        for ref in selected_legal:
            duplicate_key = (grant_target, ref)
            previous = selected_global.get(duplicate_key)
            if previous is not None and previous != choice_id:
                issues.append(
                    _issue(
                        "duplicate_subclass_grant_across_choices",
                        "draft_payload.choice_selections",
                        "The same permanent subclass grant cannot fill multiple choice slots.",
                        ref,
                    )
                )
            selected_global[duplicate_key] = choice_id
        grants.append(
            GrantSelection(
                subclass_ref=subclass_ref,
                source_ref=subclass_ref,
                grant_target=grant_target,
                access_type=(str(raw["access_type"]) if isinstance(raw.get("access_type"), str) else None),
                refs=selected_legal,
            )
        )

    for choice_id, selection in draft.draft_payload.choice_selections.items():
        if choice_id.startswith("m01-j:") and choice_id not in active_ids:
            issues.append(
                _issue(
                    "stale_subclass_choice",
                    f"draft_payload.choice_selections.{choice_id}",
                    "A subclass choice remains selected after its subclass/branch is no longer active.",
                    *(selection.selected_option_ids or ()),
                )
            )

    fixed_grants: list[tuple[str, dict[str, tuple[str, ...]]]] = []
    fixed_features: list[str] = []
    for class_ref, subclass_ref in selected_subclasses.items():
        subclass = registry.get_optional(subclass_ref)
        if subclass is None:
            continue
        raw_fixed = subclass.data.get("fixed_grants")
        if isinstance(raw_fixed, dict):
            normalized: dict[str, tuple[str, ...]] = {}
            for field, refs in raw_fixed.items():
                if isinstance(field, str) and isinstance(refs, (list, tuple)):
                    normalized[field] = tuple(ref for ref in refs if isinstance(ref, str))
            fixed_grants.append((subclass_ref, normalized))
        raw_features = subclass.data.get("fixed_feature_refs")
        if isinstance(raw_features, list):
            fixed_features.extend(ref for ref in raw_features if isinstance(ref, str))

    third = _compile_third_casters(draft, base.registry)
    issues.extend(third.issues)
    return M01JSubclassRuntime(
        base=base,
        registry=base.registry,
        choices=tuple(choices),
        issues=tuple(issues),
        grant_selections=tuple(grants),
        fixed_grants=tuple(fixed_grants),
        fixed_feature_refs=tuple(dict.fromkeys(fixed_features)),
        third_casters=third,
    )


def _classify_mixed_target(ref: str) -> str | None:
    try:
        kind = parse_stable_key(ref).kind
    except ValueError:
        return None
    if kind == "skill":
        return "skill"
    if kind == "language":
        return "language"
    if kind == "proficiency":
        return "proficiency"
    if kind == "ability":
        return "saving_throw"
    if kind == "spell":
        return "spell"
    return None


def _append_spell_grant(
    entries: dict[str, SpellAccessEntry],
    *,
    subclass_ref: str,
    spell_ref: str,
    access_type: str,
) -> None:
    entry = SpellAccessEntry(
        entry_id=_third_spell_entry_id(subclass_ref, spell_ref, access_type),
        spell_key=spell_ref,
        source_type="subclass",
        source_key=subclass_ref,
        access_type=access_type,
    )
    entries[entry.entry_id] = entry


def apply_m01j_subclass_runtime(
    build: CharacterBuild,
    runtime: M01JSubclassRuntime,
) -> CharacterBuild:
    build = apply_base_m01j_subclass_runtime(build, runtime.base)
    proficiencies = list(build.proficiencies)
    skills = list(build.skill_choices)
    languages = list(build.language_refs)
    saves = list(build.saving_throw_proficiencies)
    features = list(build.feature_refs)
    features.extend(runtime.fixed_feature_refs)
    spell_entries = {entry.entry_id: entry for entry in build.spell_access_entries}
    grant_sources = list(build.feature_grant_sources)

    for subclass_ref, grants in runtime.fixed_grants:
        proficiencies.extend(grants.get("proficiencies", ()))
        skills.extend(grants.get("skills", ()))
        languages.extend(grants.get("languages", ()))
        saves.extend(grants.get("saving_throw_proficiencies", ()))

    for selection in runtime.grant_selections:
        for ref in selection.refs:
            target = selection.grant_target
            if target == "mixed_skill_language":
                target = _classify_mixed_target(ref) or target
            if target == "proficiency":
                proficiencies.append(ref)
            elif target == "skill":
                skills.append(ref)
            elif target == "language":
                languages.append(ref)
            elif target == "saving_throw":
                saves.append(ref)
            elif target == "spell":
                _append_spell_grant(
                    spell_entries,
                    subclass_ref=selection.subclass_ref,
                    spell_ref=ref,
                    access_type=selection.access_type or "granted",
                )

    for entry in runtime.third_casters.spell_access_entries:
        spell_entries[entry.entry_id] = entry

    # Choice-owned feature grants already have provenance from the base M01-J
    # compiler. Fixed generated features are intrinsic progression identity and
    # therefore intentionally do not get a choice provenance row.
    return build.model_copy(
        update={
            "proficiencies": tuple(dict.fromkeys(proficiencies)),
            "skill_choices": tuple(dict.fromkeys(skills)),
            "language_refs": tuple(dict.fromkeys(languages)),
            "saving_throw_proficiencies": tuple(dict.fromkeys(saves)),
            "feature_refs": tuple(dict.fromkeys(features)),
            "feature_grant_sources": tuple(grant_sources),
            "spell_access_entries": tuple(spell_entries.values()),
        }
    )


def _normal_class_caster_contribution(
    build: CharacterBuild,
) -> tuple[int, int]:
    rules = load_spellcasting_rules()
    class_levels = Counter(build.class_progression)
    sources = 0
    total = 0
    for profile in build.spellcasting_profiles:
        if profile.source_type != "class" or profile.resource_pool_type != "normal_multiclass_slots":
            continue
        config = rules.classes.get(profile.class_ref)
        if config is None or config.slot_contribution.formula == "none":
            continue
        sources += 1
        total += caster_level_contribution(
            profile.class_ref,
            class_levels[profile.class_ref],
            config,
        )
    return sources, total


def _combined_normal_slots(
    build: CharacterBuild,
    third: ThirdCasterCompilation,
) -> tuple[int, ...] | None:
    if not third.profiles:
        return None
    class_sources, class_contribution = _normal_class_caster_contribution(build)
    third_sources = len(third.profiles)
    total_sources = class_sources + third_sources
    if total_sources == 1 and class_sources == 0 and len(third.local_slot_rows) == 1:
        return third.local_slot_rows[0][1]
    caster_level = class_contribution + sum(value for _class_ref, value in third.contributions)
    if caster_level <= 0:
        return ()
    row = load_spellcasting_rules().combined_spell_slots[min(caster_level, 20)]
    return tuple(row)


def _summary_normal_pool(slots: tuple[int, ...]) -> BuilderSpellResourcePoolSummary:
    return BuilderSpellResourcePoolSummary(
        pool_id="spell_slots:combined",
        pool_type=BuilderSpellResourcePoolType.NORMAL_MULTICLASS_SLOTS,
        slots=tuple(
            BuilderSpellSlotCapacity(level=level, count=count)
            for level, count in enumerate(slots, start=1)
            if count > 0
        ),
    )


def apply_m01j_spellcasting_summary(
    summary: BuilderResolvedSummary,
    runtime: M01JSubclassRuntime,
    build: CharacterBuild | None,
) -> BuilderResolvedSummary:
    if not runtime.third_casters.profiles:
        return summary
    profiles = tuple((*summary.spellcasting_profiles, *runtime.third_casters.profiles))
    pools = list(summary.spell_resource_pools)
    if build is not None:
        slots = _combined_normal_slots(build, runtime.third_casters)
        if slots is not None:
            pools = [
                pool
                for pool in pools
                if pool.pool_type is not BuilderSpellResourcePoolType.NORMAL_MULTICLASS_SLOTS
            ]
            if slots:
                pools.append(_summary_normal_pool(slots))
    return summary.model_copy(
        update={
            "spellcasting_profiles": profiles,
            "spell_resource_pools": tuple(pools),
        }
    )


def apply_m01j_spellcasting_build(
    build: CharacterBuild,
    runtime: M01JSubclassRuntime,
) -> CharacterBuild:
    if not runtime.third_casters.profiles:
        return build
    profiles = list(build.spellcasting_profiles)
    for profile in runtime.third_casters.profiles:
        profiles.append(
            SpellcastingProfile(
                profile_id=profile.profile_id,
                source_type="subclass",
                source_key=profile.source_key,
                class_ref=profile.class_ref,
                ability=profile.ability,
                access_model="known",
                resource_pool_type="normal_multiclass_slots",
                max_spell_level=profile.max_spell_level,
                prepared_limit=None,
            )
        )
    pools = [
        pool
        for pool in build.spell_resource_pools
        if pool.pool_type != "normal_multiclass_slots"
    ]
    slots = _combined_normal_slots(build, runtime.third_casters)
    if slots:
        pools.append(
            SpellResourcePool(
                pool_id="spell_slots:combined",
                pool_type="normal_multiclass_slots",
                slots=tuple(
                    SpellSlotCapacity(level=level, capacity=count)
                    for level, count in enumerate(slots, start=1)
                    if count > 0
                ),
            )
        )
    return build.model_copy(
        update={
            "spellcasting_profiles": tuple(profiles),
            "spell_resource_pools": tuple(pools),
        }
    )
