from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.content.identity import (
    parse_stable_key,
    reference_to_stable_key,
    stable_key,
    stable_key_is_kind,
)
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import PreparedSpellSelection, SpellAccessEntry
from app.domain.character_builder.rules import (
    SpellcastingClassRule,
    caster_level_contribution,
    load_spellcasting_rules,
    prepared_limit as calculate_prepared_limit,
)
from app.domain.character_builder.schemas import (
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderSpellAccessModel,
    BuilderSpellcastingProfileSummary,
    BuilderSpellChoiceInput,
    BuilderSpellOptionSummary,
    BuilderSpellResourcePoolSummary,
    BuilderSpellResourcePoolType,
    BuilderSpellSlotCapacity,
)
from app.domain.rules.abilities import ABILITY_INDEX_TO_NAME, ability_modifier


@dataclass(frozen=True)
class SpellcastingCompilation:
    profiles: tuple[BuilderSpellcastingProfileSummary, ...]
    resource_pools: tuple[BuilderSpellResourcePoolSummary, ...]
    spell_access_entries: tuple[SpellAccessEntry, ...]
    initial_prepared_spells: tuple[PreparedSpellSelection, ...]
    issues: tuple[BuilderIssue, ...]


def _class_index(class_ref: str) -> str:
    return parse_stable_key(class_ref, kinds={"class"}).index


def _spell_index(spell_key: str) -> str:
    return parse_stable_key(spell_key, kinds={"spell"}).index


def _identity_token(key: str) -> str:
    parsed = parse_stable_key(key)
    return parsed.index if parsed.source == "srd5.1" else f"{parsed.source}:{parsed.index}"


def _profile_id(class_ref: str) -> str:
    return f"class:{_identity_token(class_ref)}"


def _level_entry(registry: ContentRegistry, class_ref: str, class_level: int) -> ContentEntry:
    parsed = parse_stable_key(class_ref, kinds={"class"})
    return registry.get(stable_key(parsed.source, "level", f"{parsed.index}-{class_level}"))


def _spellcasting_row(
    registry: ContentRegistry,
    class_ref: str,
    class_level: int,
) -> dict[str, object]:
    raw = _level_entry(registry, class_ref, class_level).data.get("spellcasting")
    return raw if isinstance(raw, dict) else {}


def _spellcasting_start_level(class_entry: ContentEntry) -> int | None:
    raw = class_entry.data.get("spellcasting")
    if not isinstance(raw, dict):
        return None
    value = raw.get("level")
    return value if isinstance(value, int) and value >= 1 else None


def _spellcasting_ability(class_entry: ContentEntry) -> str | None:
    raw = class_entry.data.get("spellcasting")
    if not isinstance(raw, dict):
        return None
    reference = raw.get("spellcasting_ability")
    if not isinstance(reference, dict):
        return None
    try:
        key = reference_to_stable_key(reference, kinds={"ability"})
    except ValueError:
        return None
    index = parse_stable_key(key).index if key is not None else reference.get("index")
    return ABILITY_INDEX_TO_NAME.get(index) if isinstance(index, str) else None


def _slot_counts(row: dict[str, object]) -> dict[int, int]:
    result: dict[int, int] = {}
    for spell_level in range(1, 10):
        value = row.get(f"spell_slots_level_{spell_level}")
        if isinstance(value, int) and value > 0:
            result[spell_level] = value
    return result


def _max_spell_level(row: dict[str, object]) -> int:
    slots = _slot_counts(row)
    return max(slots, default=0)


def _class_levels(draft: BuilderDraft) -> Counter[str]:
    return Counter(level.class_ref for level in draft.draft_payload.level_choices)


def _spell_on_class_list(
    registry: ContentRegistry,
    spell: ContentEntry,
    class_ref: str,
) -> bool:
    references = spell.data.get("classes")
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, dict):
                continue
            try:
                if reference_to_stable_key(reference, kinds={"class"}) == class_ref:
                    return True
            except ValueError:
                continue

    class_entry = registry.get_optional(class_ref)
    if class_entry is None:
        return False
    dedicated = class_entry.data.get("spell_list")
    if not isinstance(dedicated, list):
        return False
    for reference in dedicated:
        if not isinstance(reference, dict):
            continue
        try:
            if reference_to_stable_key(reference, kinds={"spell"}) == spell.key:
                return True
        except ValueError:
            continue
    return False


def _eligible_spells(
    registry: ContentRegistry,
    class_ref: str,
    max_spell_level: int,
) -> tuple[ContentEntry, ...]:
    return tuple(
        spell
        for spell in registry.list_kind("spell")
        if _spell_on_class_list(registry, spell, class_ref)
        and isinstance(spell.data.get("level"), int)
        and int(spell.data["level"]) <= max_spell_level
    )


def _spell_options(entries: tuple[ContentEntry, ...]) -> tuple[BuilderSpellOptionSummary, ...]:
    return tuple(
        BuilderSpellOptionSummary(
            spell_key=spell.key,
            name=f"{spell.name} · {spell.source_label or spell.source}",
            level=int(spell.data["level"]),
        )
        for spell in sorted(entries, key=lambda item: (int(item.data["level"]), item.name, item.key))
    )


def _prepared_limit(
    rule: SpellcastingClassRule,
    class_level: int,
    ability_score: int | None,
) -> int | None:
    if rule.prepared_formula is None or ability_score is None:
        return None
    return calculate_prepared_limit(rule, class_level, ability_modifier(ability_score))


def _entry_id(source_type: str, source_key: str, access_type: str, spell_key: str) -> str:
    return f"{source_type}:{_identity_token(source_key)}:{access_type}:{_identity_token(spell_key)}"


def _issue(
    code: str,
    path: str,
    message: str,
    *related_refs: str,
) -> BuilderIssue:
    return BuilderIssue(
        code=code,
        severity=BuilderIssueSeverity.BLOCKING_ERROR,
        path=path,
        message=message,
        related_refs=tuple(related_refs),
    )


def _spell_level(registry: ContentRegistry, spell_key: str) -> int | None:
    entry = registry.get_optional(spell_key)
    if entry is None or not stable_key_is_kind(entry.key, "spell"):
        return None
    value = entry.data.get("level")
    return value if isinstance(value, int) else None


def _validate_exact_selection(
    *,
    registry: ContentRegistry,
    selected: tuple[str, ...],
    expected_count: int,
    class_ref: str,
    expected_level: int | None,
    max_spell_level: int,
    path: str,
    label: str,
) -> list[BuilderIssue]:
    issues: list[BuilderIssue] = []
    if len(selected) != expected_count:
        issues.append(
            _issue(
                "invalid_spell_choice_count",
                path,
                f"{label} requires exactly {expected_count} selections; got {len(selected)}.",
                class_ref,
            )
        )
    for spell_key in selected:
        spell = registry.get_optional(spell_key)
        if spell is None or not stable_key_is_kind(spell.key, "spell"):
            issues.append(
                _issue(
                    "invalid_spell_reference",
                    path,
                    f"Unknown spell selection: {spell_key}.",
                    spell_key,
                )
            )
            continue
        level = spell.data.get("level")
        if not isinstance(level, int) or not _spell_on_class_list(registry, spell, class_ref):
            issues.append(
                _issue(
                    "spell_not_on_source_list",
                    path,
                    f"{spell.name} is not available from this spellcasting source.",
                    spell_key,
                    class_ref,
                )
            )
            continue
        if expected_level is not None and level != expected_level:
            issues.append(
                _issue(
                    "invalid_spell_level",
                    path,
                    f"{label} selections must be spell level {expected_level}; {spell.name} is level {level}.",
                    spell_key,
                )
            )
        elif expected_level is None and (level < 1 or level > max_spell_level):
            issues.append(
                _issue(
                    "invalid_spell_level",
                    path,
                    f"{spell.name} is not an eligible leveled spell for this source at its current class level.",
                    spell_key,
                )
            )
    return issues


def _validate_prepared_selection(
    *,
    registry: ContentRegistry,
    selected: tuple[str, ...],
    limit: int,
    class_ref: str,
    max_spell_level: int,
    path: str,
    spellbook_keys: tuple[str, ...] | None = None,
) -> list[BuilderIssue]:
    issues: list[BuilderIssue] = []
    if len(selected) > limit:
        issues.append(
            _issue(
                "prepared_spell_limit_exceeded",
                path,
                f"Prepared spell limit is {limit}; got {len(selected)} selections.",
                class_ref,
            )
        )
    spellbook = set(spellbook_keys or ())
    for spell_key in selected:
        spell = registry.get_optional(spell_key)
        if spell is None or not stable_key_is_kind(spell.key, "spell"):
            issues.append(_issue("invalid_spell_reference", path, f"Unknown prepared spell: {spell_key}.", spell_key))
            continue
        level = spell.data.get("level")
        if not isinstance(level, int) or level < 1 or level > max_spell_level:
            issues.append(
                _issue(
                    "invalid_prepared_spell",
                    path,
                    f"{spell.name} is not a prepareable leveled spell at this source level.",
                    spell_key,
                )
            )
            continue
        if spellbook_keys is not None:
            if spell_key not in spellbook:
                issues.append(
                    _issue(
                        "prepared_spell_not_in_spellbook",
                        path,
                        f"{spell.name} is not in this Wizard spellbook.",
                        spell_key,
                    )
                )
        elif not _spell_on_class_list(registry, spell, class_ref):
            issues.append(
                _issue(
                    "spell_not_on_source_list",
                    path,
                    f"{spell.name} cannot be prepared from this spellcasting source.",
                    spell_key,
                    class_ref,
                )
            )
    return issues


def _acquisition_opportunity_levels(
    registry: ContentRegistry,
    class_ref: str,
    class_level: int,
    rule: SpellcastingClassRule,
) -> list[int]:
    """Return max spell level for every final-spell acquisition opportunity.

    This lets high-level creation save a compact final selection while still
    rejecting impossible results such as filling a level-17 Wizard spellbook
    entirely with 9th-level spells. Wizard opportunities are six at first
    level and two on every later Wizard level. Known casters gain slots when
    spells_known increases and may replace one known spell on each later class
    level, matching 2014 level-up behavior.
    """

    opportunities: list[int] = []
    if rule.access_model == "spellbook":
        for current in range(1, class_level + 1):
            row = _spellcasting_row(registry, class_ref, current)
            if not row:
                continue
            count = rule.spellbook_initial if current == 1 else rule.spellbook_per_level
            opportunities.extend([_max_spell_level(row)] * count)
        return opportunities

    if rule.access_model != "known":
        return opportunities

    previous_known = 0
    started = False
    for current in range(1, class_level + 1):
        row = _spellcasting_row(registry, class_ref, current)
        if not row:
            continue
        known = row.get("spells_known")
        if not isinstance(known, int):
            continue
        gained = max(0, known - previous_known)
        max_level = _max_spell_level(row)
        opportunities.extend([max_level] * gained)
        if started and previous_known > 0:
            opportunities.append(max_level)
        started = True
        previous_known = known
    return opportunities


def _validate_acquisition_feasibility(
    registry: ContentRegistry,
    selected: tuple[str, ...],
    opportunities: list[int],
    path: str,
) -> list[BuilderIssue]:
    levels = []
    for spell_key in selected:
        level = _spell_level(registry, spell_key)
        if level is not None and level > 0:
            levels.append((level, spell_key))
    available = sorted(opportunities, reverse=True)
    for level, spell_key in sorted(levels, reverse=True):
        match = next((index for index, max_level in enumerate(available) if max_level >= level), None)
        if match is None:
            return [
                _issue(
                    "impossible_spell_acquisition_order",
                    path,
                    "The final spell selection cannot be produced by legal level-by-level spell acquisition/replacement.",
                    spell_key,
                )
            ]
        available.pop(match)
    return []


def _normal_spellcasting_sources(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> list[tuple[str, int, SpellcastingClassRule]]:
    rules = load_spellcasting_rules()
    result: list[tuple[str, int, SpellcastingClassRule]] = []
    for class_ref, class_level in _class_levels(draft).items():
        rule = rules.classes.get(class_ref)
        class_entry = registry.get_optional(class_ref)
        if rule is None or class_entry is None:
            continue
        start = _spellcasting_start_level(class_entry)
        if (
            start is None
            or class_level < start
            or rule.resource_pool_type != "normal_multiclass_slots"
            or rule.slot_contribution.formula == "none"
        ):
            continue
        result.append((class_ref, class_level, rule))
    return result


def calculate_multiclass_spell_slots(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> dict[int, int]:
    """Return normal spell-slot capacity while keeping Pact Magic separate.

    A character with only one normal Spellcasting class still uses that class's
    own progression table. The multiclass caster-level table applies only when
    two or more normal Spellcasting classes contribute; Pact Magic never counts
    toward that threshold or the combined caster level.
    """

    sources = _normal_spellcasting_sources(draft, registry)
    if not sources:
        return {}
    if len(sources) == 1:
        class_ref, class_level, _rule = sources[0]
        return _slot_counts(_spellcasting_row(registry, class_ref, class_level))

    caster_level = sum(
        caster_level_contribution(class_ref, class_level, rule)
        for class_ref, class_level, rule in sources
    )
    if caster_level <= 0:
        return {}
    row = load_spellcasting_rules().combined_spell_slots[min(caster_level, 20)]
    return {level: count for level, count in enumerate(row, start=1) if count > 0}


def _resource_pools(
    draft: BuilderDraft,
    registry: ContentRegistry,
    profiles: tuple[BuilderSpellcastingProfileSummary, ...],
) -> tuple[BuilderSpellResourcePoolSummary, ...]:
    pools: list[BuilderSpellResourcePoolSummary] = []
    normal = calculate_multiclass_spell_slots(draft, registry)
    normal_profile_count = sum(
        profile.resource_pool_type is BuilderSpellResourcePoolType.NORMAL_MULTICLASS_SLOTS
        for profile in profiles
    )
    if normal:
        pools.append(
            BuilderSpellResourcePoolSummary(
                pool_id="spell_slots:combined" if normal_profile_count > 1 else "spell_slots:normal",
                pool_type=BuilderSpellResourcePoolType.NORMAL_MULTICLASS_SLOTS,
                slots=tuple(
                    BuilderSpellSlotCapacity(level=level, count=count)
                    for level, count in sorted(normal.items())
                ),
            )
        )

    for profile in profiles:
        if profile.resource_pool_type is not BuilderSpellResourcePoolType.PACT_MAGIC:
            continue
        row = _spellcasting_row(registry, profile.class_ref, profile.class_level)
        slots = _slot_counts(row)
        pools.append(
            BuilderSpellResourcePoolSummary(
                pool_id=f"pact_magic:{profile.class_ref}",
                pool_type=BuilderSpellResourcePoolType.PACT_MAGIC,
                source_profile_id=profile.profile_id,
                slots=tuple(
                    BuilderSpellSlotCapacity(level=level, count=count)
                    for level, count in sorted(slots.items())
                ),
            )
        )
    return tuple(pools)


def _subclass_spell_access(
    draft: BuilderDraft,
    registry: ContentRegistry,
    feature_refs: tuple[str, ...],
) -> tuple[SpellAccessEntry, ...]:
    class_levels = _class_levels(draft)
    feature_set = set(feature_refs)
    subclass_refs = tuple(
        dict.fromkeys(
            level.subclass_ref
            for level in draft.draft_payload.level_choices
            if level.subclass_ref is not None
        )
    )
    entries: list[SpellAccessEntry] = []
    for subclass_ref in subclass_refs:
        subclass = registry.get_optional(subclass_ref)
        if subclass is None:
            continue
        parent = subclass.data.get("class")
        if not isinstance(parent, dict):
            continue
        try:
            class_ref = reference_to_stable_key(parent, kinds={"class"})
        except ValueError:
            continue
        if class_ref is None:
            continue
        class_level = class_levels.get(class_ref, 0)
        raw_spells = subclass.data.get("spells")
        if not isinstance(raw_spells, list):
            continue
        for raw in raw_spells:
            if not isinstance(raw, dict):
                continue
            prerequisites = raw.get("prerequisites")
            legal = True
            if isinstance(prerequisites, list):
                for prerequisite in prerequisites:
                    if not isinstance(prerequisite, dict):
                        continue
                    kind = prerequisite.get("type")
                    index = prerequisite.get("index")
                    if kind == "level" and isinstance(index, str):
                        try:
                            required_level = int(index.rsplit("-", 1)[1])
                        except (IndexError, ValueError):
                            legal = False
                            break
                        if class_level < required_level:
                            legal = False
                            break
                    elif kind == "feature":
                        feature_key = prerequisite.get("key")
                        if isinstance(feature_key, str):
                            try:
                                parsed_feature = parse_stable_key(feature_key, kinds={"feature"})
                                required_feature = stable_key(
                                    parsed_feature.source,
                                    parsed_feature.kind,
                                    parsed_feature.index,
                                )
                            except ValueError:
                                legal = False
                                break
                        elif isinstance(index, str):
                            required_feature = stable_key("srd5.1", "feature", index)
                        else:
                            legal = False
                            break
                        if required_feature not in feature_set:
                            legal = False
                            break
            spell = raw.get("spell")
            if not legal or not isinstance(spell, dict):
                continue
            try:
                spell_key = reference_to_stable_key(spell, kinds={"spell"})
            except ValueError:
                continue
            if spell_key is None or registry.get_optional(spell_key) is None:
                continue
            entries.append(
                SpellAccessEntry(
                    entry_id=_entry_id("subclass", subclass_ref, "always_prepared", spell_key),
                    spell_key=spell_key,
                    source_type="subclass",
                    source_key=subclass_ref,
                    access_type="always_prepared",
                )
            )
    return tuple(entries)


def compile_spellcasting(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    effective_abilities: dict[str, int] | None,
    feature_refs: tuple[str, ...] = (),
) -> SpellcastingCompilation:
    rules = load_spellcasting_rules()
    class_levels = _class_levels(draft)
    profiles: list[BuilderSpellcastingProfileSummary] = []
    access_entries: list[SpellAccessEntry] = []
    prepared: list[PreparedSpellSelection] = []
    issues: list[BuilderIssue] = []
    live_profile_ids: set[str] = set()

    for class_ref, class_level in class_levels.items():
        rule = rules.classes.get(class_ref)
        class_entry = registry.get_optional(class_ref)
        if rule is None or class_entry is None:
            continue
        start_level = _spellcasting_start_level(class_entry)
        if start_level is None or class_level < start_level:
            continue
        row = _spellcasting_row(registry, class_ref, class_level)
        if not row:
            issues.append(
                _issue(
                    "spellcasting_rules_data_error",
                    "draft_payload.level_choices",
                    f"{class_entry.name} level {class_level} is missing spellcasting progression data.",
                    class_ref,
                )
            )
            continue
        ability = _spellcasting_ability(class_entry)
        if ability is None:
            issues.append(
                _issue(
                    "spellcasting_rules_data_error",
                    "draft_payload.level_choices",
                    f"{class_entry.name} is missing a spellcasting ability.",
                    class_ref,
                )
            )
            continue

        profile_id = _profile_id(class_ref)
        live_profile_ids.add(profile_id)
        choice = draft.draft_payload.spell_choices.get(profile_id, BuilderSpellChoiceInput())
        max_level = _max_spell_level(row)
        cantrip_count = int(row.get("cantrips_known", 0)) if isinstance(row.get("cantrips_known", 0), int) else 0
        known_count = int(row.get("spells_known", 0)) if isinstance(row.get("spells_known", 0), int) else 0
        spellbook_count = (
            rule.spellbook_initial + rule.spellbook_per_level * max(0, class_level - 1)
            if rule.access_model == "spellbook"
            else 0
        )
        prepared_limit = _prepared_limit(
            rule,
            class_level,
            (effective_abilities or {}).get(ability),
        )
        eligible = _eligible_spells(registry, class_ref, max_level)

        path = f"draft_payload.spell_choices.{profile_id}"
        issues.extend(
            _validate_exact_selection(
                registry=registry,
                selected=choice.cantrip_keys,
                expected_count=cantrip_count,
                class_ref=class_ref,
                expected_level=0,
                max_spell_level=max_level,
                path=f"{path}.cantrip_keys",
                label=f"{class_entry.name} cantrips",
            )
        )

        if rule.access_model == "known":
            issues.extend(
                _validate_exact_selection(
                    registry=registry,
                    selected=choice.known_spell_keys,
                    expected_count=known_count,
                    class_ref=class_ref,
                    expected_level=None,
                    max_spell_level=max_level,
                    path=f"{path}.known_spell_keys",
                    label=f"{class_entry.name} known spells",
                )
            )
            issues.extend(
                _validate_acquisition_feasibility(
                    registry,
                    choice.known_spell_keys,
                    _acquisition_opportunity_levels(registry, class_ref, class_level, rule),
                    f"{path}.known_spell_keys",
                )
            )
        elif choice.known_spell_keys:
            issues.append(
                _issue(
                    "spell_access_model_mismatch",
                    f"{path}.known_spell_keys",
                    f"{class_entry.name} does not use the known-spell model.",
                    class_ref,
                )
            )

        if rule.access_model == "spellbook":
            issues.extend(
                _validate_exact_selection(
                    registry=registry,
                    selected=choice.spellbook_spell_keys,
                    expected_count=spellbook_count,
                    class_ref=class_ref,
                    expected_level=None,
                    max_spell_level=max_level,
                    path=f"{path}.spellbook_spell_keys",
                    label=f"{class_entry.name} spellbook spells",
                )
            )
            issues.extend(
                _validate_acquisition_feasibility(
                    registry,
                    choice.spellbook_spell_keys,
                    _acquisition_opportunity_levels(registry, class_ref, class_level, rule),
                    f"{path}.spellbook_spell_keys",
                )
            )
        elif choice.spellbook_spell_keys:
            issues.append(
                _issue(
                    "spell_access_model_mismatch",
                    f"{path}.spellbook_spell_keys",
                    f"{class_entry.name} does not use a spellbook.",
                    class_ref,
                )
            )

        if prepared_limit is not None:
            issues.extend(
                _validate_prepared_selection(
                    registry=registry,
                    selected=choice.prepared_spell_keys,
                    limit=prepared_limit,
                    class_ref=class_ref,
                    max_spell_level=max_level,
                    path=f"{path}.prepared_spell_keys",
                    spellbook_keys=(
                        choice.spellbook_spell_keys if rule.access_model == "spellbook" else None
                    ),
                )
            )
        elif choice.prepared_spell_keys:
            issues.append(
                _issue(
                    "spell_access_model_mismatch",
                    f"{path}.prepared_spell_keys",
                    f"{class_entry.name} does not prepare a daily spell list.",
                    class_ref,
                )
            )

        for spell_key in choice.cantrip_keys:
            if _spell_level(registry, spell_key) == 0 and registry.get_optional(spell_key) is not None:
                access_entries.append(
                    SpellAccessEntry(
                        entry_id=_entry_id("class", class_ref, "known", spell_key),
                        spell_key=spell_key,
                        source_type="class",
                        source_key=class_ref,
                        access_type="known",
                    )
                )
        for spell_key in choice.known_spell_keys:
            if registry.get_optional(spell_key) is not None:
                access_entries.append(
                    SpellAccessEntry(
                        entry_id=_entry_id("class", class_ref, "known", spell_key),
                        spell_key=spell_key,
                        source_type="class",
                        source_key=class_ref,
                        access_type="known",
                    )
                )
        for spell_key in choice.spellbook_spell_keys:
            if registry.get_optional(spell_key) is not None:
                access_entries.append(
                    SpellAccessEntry(
                        entry_id=_entry_id("class", class_ref, "spellbook", spell_key),
                        spell_key=spell_key,
                        source_type="class",
                        source_key=class_ref,
                        access_type="spellbook",
                    )
                )

        access_by_spell = {
            entry.spell_key: entry.entry_id
            for entry in access_entries
            if entry.source_type == "class" and entry.source_key == class_ref
        }
        for spell_key in choice.prepared_spell_keys:
            if registry.get_optional(spell_key) is None:
                continue
            prepared.append(
                PreparedSpellSelection(
                    spell_key=spell_key,
                    source_profile_id=profile_id,
                    source_access_entry_id=(
                        access_by_spell.get(spell_key) if rule.access_model == "spellbook" else None
                    ),
                )
            )

        profiles.append(
            BuilderSpellcastingProfileSummary(
                profile_id=profile_id,
                source_type="class",
                source_key=class_ref,
                source_name=class_entry.name,
                class_ref=class_ref,
                ability=ability,
                access_model=BuilderSpellAccessModel(rule.access_model),
                class_level=class_level,
                max_spell_level=max_level,
                cantrip_count=cantrip_count,
                known_spell_count=known_count if rule.access_model == "known" else 0,
                spellbook_count=spellbook_count,
                prepared_limit=prepared_limit,
                resource_pool_type=BuilderSpellResourcePoolType(rule.resource_pool_type),
                available_spells=_spell_options(eligible),
                selected_cantrip_keys=choice.cantrip_keys,
                selected_known_spell_keys=choice.known_spell_keys,
                selected_spellbook_spell_keys=choice.spellbook_spell_keys,
                selected_prepared_spell_keys=choice.prepared_spell_keys,
            )
        )

    for profile_id in draft.draft_payload.spell_choices:
        if profile_id not in live_profile_ids:
            issues.append(
                _issue(
                    "invalid_spell_profile",
                    f"draft_payload.spell_choices.{profile_id}",
                    "This spell selection belongs to a spellcasting profile that is not present in the current progression.",
                )
            )

    subclass_entries = _subclass_spell_access(draft, registry, feature_refs)
    access_entries.extend(subclass_entries)

    deduped_entries = tuple({entry.entry_id: entry for entry in access_entries}.values())
    profile_tuple = tuple(profiles)
    return SpellcastingCompilation(
        profiles=profile_tuple,
        resource_pools=_resource_pools(draft, registry, profile_tuple),
        spell_access_entries=deduped_entries,
        initial_prepared_spells=tuple(prepared),
        issues=tuple(issues),
    )
