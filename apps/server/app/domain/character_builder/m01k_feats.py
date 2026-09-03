from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.content.identity import parse_stable_key, reference_to_stable_key, stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import (
    FeatAcquisition,
    FeatResourceGrant,
    SpellAccessEntry,
    StaticDerivedModifier,
)
from app.domain.character_builder.basics import resolve_creation_summary
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderOptionKind,
)
from app.domain.character_builder.structural import compile_structural_selections


ABILITY_TO_INDEX = {
    "strength": "str",
    "dexterity": "dex",
    "constitution": "con",
    "intelligence": "int",
    "wisdom": "wis",
    "charisma": "cha",
}
ABILITY_LABELS = {key: value.upper() for key, value in ABILITY_TO_INDEX.items()}
FEAT_CHOICE_SOURCES = {"content:race-feat", "content:asi-feat"}
FEAT_ABILITY_CAP = 20
ARMOR_PROFICIENCY_IMPLICATIONS = {
    "srd5.1:proficiency:all-armor": frozenset(
        {
            "srd5.1:proficiency:light-armor",
            "srd5.1:proficiency:medium-armor",
            "srd5.1:proficiency:heavy-armor",
        }
    ),
}


@dataclass(frozen=True)
class FeatEvaluationContext:
    abilities: dict[str, int] | None
    proficiencies: frozenset[str]
    has_spellcasting: bool


@dataclass(frozen=True)
class FeatFailureDetail:
    code: str
    params: dict[str, object]


@dataclass(frozen=True)
class FeatCompilation:
    acquisitions: tuple[FeatAcquisition, ...]
    ability_bonuses: dict[str, int]
    proficiencies: tuple[str, ...]
    saving_throw_proficiencies: tuple[str, ...]
    skill_refs: tuple[str, ...]
    language_refs: tuple[str, ...]
    feature_refs: tuple[str, ...]
    static_modifiers: tuple[StaticDerivedModifier, ...]
    resource_grants: tuple[FeatResourceGrant, ...]
    spell_access_entries: tuple[SpellAccessEntry, ...]
    issues: tuple[BuilderIssue, ...]


def _acquisition_id(opportunity_id: str) -> str:
    digest = sha256(opportunity_id.encode("utf-8")).hexdigest()[:24]
    return f"feat-acquisition:{digest}"


def _child_choice_id(opportunity_id: str, field: str) -> str:
    digest = sha256(f"{opportunity_id}|{field}".encode("utf-8")).hexdigest()[:24]
    return f"feat:{digest}:{field}"


def _selection(draft: BuilderDraft, choice_id: str) -> tuple[str, ...]:
    record = draft.draft_payload.choice_selections.get(choice_id)
    return record.selected_option_ids if record is not None else ()


def _entry_label(entry: ContentEntry) -> str:
    return f"{entry.name} · {entry.source_label or entry.source}"


def _legacy_ability_prerequisite(raw: dict[str, object]) -> dict[str, object] | None:
    ability = raw.get("ability_score")
    minimum = raw.get("minimum_score")
    if not isinstance(ability, dict) or not isinstance(minimum, int):
        return None
    key = reference_to_stable_key(ability)
    if key is None or not stable_key_is_kind(key, "ability"):
        return None
    index = parse_stable_key(key).index
    for name, candidate in ABILITY_TO_INDEX.items():
        if candidate == index:
            return {"type": "ability", "ability": name, "minimum_score": minimum}
    return None


def _has_proficiency(context: FeatEvaluationContext, required: str) -> bool:
    if required in context.proficiencies:
        return True
    return any(
        required in ARMOR_PROFICIENCY_IMPLICATIONS.get(held, ())
        for held in context.proficiencies
    )


def _requirement_failure(
    requirement: dict[str, object],
    context: FeatEvaluationContext,
) -> dict[str, object] | None:
    req_type = requirement.get("type")
    if req_type is None:
        normalized = _legacy_ability_prerequisite(requirement)
        if normalized is None:
            return {"type": "unsupported"}
        requirement = normalized
        req_type = "ability"

    if req_type == "ability":
        ability = requirement.get("ability")
        minimum = requirement.get("minimum_score")
        if not isinstance(ability, str) or ability not in ABILITY_TO_INDEX or not isinstance(minimum, int):
            return {"type": "unsupported"}
        if context.abilities is None:
            return {"type": "ability_scores_incomplete", "ability": ability, "minimum_score": minimum}
        actual = context.abilities.get(ability, 0)
        return None if actual >= minimum else {
            "type": "ability",
            "ability": ability,
            "minimum_score": minimum,
            "actual_score": actual,
        }

    if req_type == "armor_proficiency":
        proficiency_ref = requirement.get("proficiency_ref")
        if not isinstance(proficiency_ref, str) or not stable_key_is_kind(proficiency_ref, "proficiency"):
            return {"type": "unsupported"}
        return None if _has_proficiency(context, proficiency_ref) else {
            "type": "armor_proficiency",
            "proficiency_ref": proficiency_ref,
        }

    if req_type == "spellcasting":
        return None if context.has_spellcasting else {"type": "spellcasting"}

    if req_type == "any_of":
        options = requirement.get("options")
        if not isinstance(options, list) or not options:
            return {"type": "unsupported"}
        failures = []
        for option in options:
            if not isinstance(option, dict):
                return {"type": "unsupported"}
            failure = _requirement_failure(option, context)
            if failure is None:
                return None
            failures.append(failure)
        return {"type": "any_of", "options": failures}

    return {"type": "unsupported"}


def feat_failure_detail(
    feat: ContentEntry,
    context: FeatEvaluationContext,
    *,
    already_acquired: tuple[str, ...] = (),
) -> FeatFailureDetail | None:
    if feat.key in already_acquired and feat.data.get("repeatable") is not True:
        return FeatFailureDetail(
            code="feat_not_repeatable",
            params={"feat_ref": feat.key},
        )

    prerequisites = feat.data.get("prerequisites")
    if prerequisites is None:
        return None
    if not isinstance(prerequisites, list):
        return FeatFailureDetail(
            code="unsupported_feat_prerequisite",
            params={"feat_ref": feat.key},
        )

    failures: list[dict[str, object]] = []
    for requirement in prerequisites:
        if not isinstance(requirement, dict):
            return FeatFailureDetail(
                code="unsupported_feat_prerequisite",
                params={"feat_ref": feat.key},
            )
        failure = _requirement_failure(requirement, context)
        if failure is not None:
            if failure.get("type") == "unsupported":
                return FeatFailureDetail(
                    code="unsupported_feat_prerequisite",
                    params={"feat_ref": feat.key},
                )
            failures.append(failure)
    if not failures:
        return None
    if any(failure.get("type") == "ability_scores_incomplete" for failure in failures):
        return FeatFailureDetail(
            code="feat_ability_scores_incomplete",
            params={"feat_ref": feat.key, "requirements": failures},
        )
    return FeatFailureDetail(
        code="feat_prerequisite_not_met",
        params={"feat_ref": feat.key, "requirements": failures},
    )


def feat_failure_reason(detail: FeatFailureDetail | None) -> str | None:
    if detail is None:
        return None
    if detail.code == "feat_not_repeatable":
        return "This feat cannot be acquired more than once."
    if detail.code == "feat_ability_scores_incomplete":
        return "Complete ability scores before choosing this feat."
    if detail.code == "unsupported_feat_prerequisite":
        return "This feat has an unsupported prerequisite shape."
    failures = detail.params.get("requirements")
    labels: list[str] = []
    if isinstance(failures, list):
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            failure_type = failure.get("type")
            if failure_type == "ability":
                ability = str(failure.get("ability"))
                labels.append(f"{ABILITY_LABELS.get(ability, ability.upper())} {failure.get('minimum_score')}+")
            elif failure_type == "armor_proficiency":
                labels.append(f"proficiency {failure.get('proficiency_ref')}")
            elif failure_type == "spellcasting":
                labels.append("the ability to cast at least one spell")
            elif failure_type == "any_of":
                labels.append("one of the listed prerequisite alternatives")
    return "Requires " + (" and ".join(labels) if labels else "the feat prerequisites") + "."


def _class_starting_proficiencies(draft: BuilderDraft, registry: ContentRegistry) -> set[str]:
    if not draft.draft_payload.level_choices:
        return set()
    first = registry.get_optional(draft.draft_payload.level_choices[0].class_ref)
    if first is None:
        return set()
    raw = first.data.get("proficiencies")
    result: set[str] = set()
    if isinstance(raw, list):
        for reference in raw:
            if isinstance(reference, dict):
                key = reference_to_stable_key(reference)
                if key is not None and stable_key_is_kind(key, "proficiency"):
                    result.add(key)
    return result


def _class_has_spellcasting(class_entry: ContentEntry) -> bool:
    if isinstance(class_entry.data.get("spellcasting"), dict):
        return True
    return parse_stable_key(class_entry.key).index in {
        "bard", "cleric", "druid", "paladin", "ranger", "sorcerer", "warlock", "wizard", "artificer"
    }


def build_evaluation_context(
    draft: BuilderDraft,
    registry: ContentRegistry,
    abilities: dict[str, int] | None,
    *,
    extra_proficiencies: tuple[str, ...] = (),
) -> FeatEvaluationContext:
    classes = [registry.get_optional(item.class_ref) for item in draft.draft_payload.level_choices]
    return FeatEvaluationContext(
        abilities=abilities,
        proficiencies=frozenset((*_class_starting_proficiencies(draft, registry), *extra_proficiencies)),
        has_spellcasting=any(entry is not None and _class_has_spellcasting(entry) for entry in classes),
    )


def _reference_options(entries: tuple[ContentEntry, ...]) -> tuple[BuilderChoiceOption, ...]:
    return tuple(
        BuilderChoiceOption(
            option_id=entry.key,
            label=_entry_label(entry),
            kind=BuilderOptionKind.REFERENCE,
            reference_id=entry.key,
        )
        for entry in entries
    )


def _proficiency_reference_is_kind(entry: ContentEntry, kind: str) -> bool:
    reference = entry.data.get("reference")
    if not isinstance(reference, dict):
        return False
    try:
        key = reference_to_stable_key(reference)
    except ValueError:
        return False
    return key is not None and stable_key_is_kind(key, kind)


def _ability_choice(
    draft: BuilderDraft,
    opportunity_id: str,
    feat: ContentEntry,
    raw: dict[str, object],
) -> BuilderChoice | None:
    if raw.get("mode") != "choice":
        return None
    abilities = raw.get("abilities")
    if not isinstance(abilities, list) or not abilities:
        return None
    choice_id = _child_choice_id(opportunity_id, "ability")
    options = tuple(
        BuilderChoiceOption(
            option_id=f"ability:{ability}",
            label=f"{ABILITY_LABELS.get(str(ability), str(ability).upper())} +{raw.get('value', 1)}",
            kind=BuilderOptionKind.BRANCH,
            branch_key=str(ability),
        )
        for ability in abilities
        if isinstance(ability, str) and ability in ABILITY_TO_INDEX
    )
    return BuilderChoice(
        choice_id=choice_id,
        label=f"{feat.name} — ability increase",
        source_ref=feat.key,
        required=True,
        choose_count=1,
        option_source="content:feat:ability",
        options=options,
        selected_option_ids=_selection(draft, choice_id),
    )


def _spell_options(
    registry: ContentRegistry,
    *,
    source_class_ref: str | None,
    level: int | None,
    ritual: bool | None,
) -> tuple[ContentEntry, ...]:
    result: list[ContentEntry] = []
    for spell in registry.list_kind("spell"):
        if level is not None and spell.data.get("level") != level:
            continue
        if ritual is not None and spell.data.get("ritual") is not ritual:
            continue
        if source_class_ref is not None:
            raw_classes = spell.data.get("classes")
            if not isinstance(raw_classes, list):
                continue
            class_refs = {
                reference_to_stable_key(item)
                for item in raw_classes
                if isinstance(item, dict)
            }
            if source_class_ref not in class_refs:
                continue
        result.append(spell)
    return tuple(result)


def _class_has_attack_roll_cantrip(registry: ContentRegistry, class_ref: str) -> bool:
    for spell in registry.list_kind("spell"):
        if spell.data.get("level") != 0:
            continue
        if spell.data.get("attack_type") not in {"melee", "ranged"}:
            continue
        raw_classes = spell.data.get("classes")
        if not isinstance(raw_classes, list):
            continue
        class_refs = {
            reference_to_stable_key(item)
            for item in raw_classes
            if isinstance(item, dict)
        }
        if class_ref in class_refs:
            return True
    return False


def _feat_nested_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    opportunity_id: str,
    feat: ContentEntry,
) -> tuple[BuilderChoice, ...]:
    result: list[BuilderChoice] = []
    ability = feat.data.get("ability_increase")
    if isinstance(ability, dict):
        choice = _ability_choice(draft, opportunity_id, feat, ability)
        if choice is not None:
            result.append(choice)

    raw_choices = feat.data.get("choices")
    if not isinstance(raw_choices, list):
        return tuple(result)

    choice_ids: dict[str, str] = {}
    for raw in raw_choices:
        if isinstance(raw, dict) and isinstance(raw.get("id"), str):
            choice_ids[raw["id"]] = _child_choice_id(opportunity_id, raw["id"])

    for raw in raw_choices:
        if not isinstance(raw, dict):
            continue
        choice_name = raw.get("id")
        kind = raw.get("kind")
        choose = raw.get("choose", 1)
        if not isinstance(choice_name, str) or not isinstance(kind, str) or not isinstance(choose, int):
            continue
        choice_id = choice_ids[choice_name]
        options: tuple[BuilderChoiceOption, ...] = ()
        disabled_reason = None
        disabled_code = None

        if kind == "enum":
            raw_options = raw.get("options")
            if isinstance(raw_options, list):
                options = tuple(
                    BuilderChoiceOption(
                        option_id=f"enum:{value}",
                        label=str(value).replace("_", " ").title(),
                        kind=BuilderOptionKind.BRANCH,
                        branch_key=str(value),
                    )
                    for value in raw_options
                    if isinstance(value, str)
                )
        elif kind == "language":
            options = _reference_options(registry.list_kind("language"))
        elif kind == "maneuver":
            maneuvers = tuple(
                entry
                for entry in registry.list_kind("feature")
                if isinstance(entry.data.get("choice_pool_option"), dict)
                and entry.data["choice_pool_option"].get("pool") == "battle-master-maneuver"
            )
            options = _reference_options(maneuvers)
        elif kind == "spellcasting_source":
            refs = raw.get("class_refs")
            entries = tuple(
                entry
                for ref in refs if isinstance(ref, str)
                if (entry := registry.get_optional(ref)) is not None
            ) if isinstance(refs, list) else ()
            if feat.key == "phb2014:feat:spell-sniper":
                options = tuple(
                    BuilderChoiceOption(
                        option_id=entry.key,
                        label=_entry_label(entry),
                        kind=BuilderOptionKind.REFERENCE,
                        reference_id=entry.key,
                        disabled_reason=(
                            "This class has no cantrips that require an attack roll in 5e 2014 rules."
                            if not _class_has_attack_roll_cantrip(registry, entry.key)
                            else None
                        ),
                        disabled_reason_code=(
                            "feat_spell_source_no_attack_cantrip"
                            if not _class_has_attack_roll_cantrip(registry, entry.key)
                            else None
                        ),
                        disabled_reason_params=(
                            {"class_ref": entry.key}
                            if not _class_has_attack_roll_cantrip(registry, entry.key)
                            else {}
                        ),
                    )
                    for entry in entries
                )
            else:
                options = _reference_options(entries)
        elif kind == "spell":
            source_choice = raw.get("from_source_choice")
            source_ref = None
            if isinstance(source_choice, str) and source_choice in choice_ids:
                selected_source = _selection(draft, choice_ids[source_choice])
                if len(selected_source) == 1:
                    source_ref = selected_source[0]
                else:
                    disabled_reason = "Choose the feat's spellcasting source first."
                    disabled_code = "feat_spell_source_required"
            level = raw.get("level") if isinstance(raw.get("level"), int) else None
            ritual = raw.get("ritual") if isinstance(raw.get("ritual"), bool) else None
            options = _reference_options(
                _spell_options(registry, source_class_ref=source_ref, level=level, ritual=ritual)
            ) if disabled_reason is None else ()
        elif kind == "skill_or_tool_proficiency":
            entries = tuple(
                entry
                for entry in registry.list_kind("proficiency")
                if entry.data.get("type") == "Skills"
                or (
                    entry.data.get("type") not in {"Armor", "Weapons"}
                    and _proficiency_reference_is_kind(entry, "equipment")
                )
            )
            options = _reference_options(entries)
        elif kind == "weapon_proficiency":
            entries = tuple(
                entry
                for entry in registry.list_kind("proficiency")
                if entry.data.get("type") == "Weapons"
                and _proficiency_reference_is_kind(entry, "equipment")
            )
            options = _reference_options(entries)

        result.append(
            BuilderChoice(
                choice_id=choice_id,
                label=f"{feat.name} — {choice_name.replace('-', ' ')}",
                source_ref=feat.key,
                required=True,
                choose_count=choose,
                option_source=f"content:feat:{kind}",
                options=options,
                selected_option_ids=_selection(draft, choice_id),
                disabled_reason=disabled_reason,
                disabled_reason_code=disabled_code,
            )
        )
    return tuple(result)


def enrich_feat_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
    context: FeatEvaluationContext,
) -> tuple[BuilderChoice, ...]:
    """Apply one prerequisite/repeatability resolver to Variant Human and ASI feat opportunities."""

    result: list[BuilderChoice] = []
    acquired: list[str] = []
    for choice in choices:
        if choice.option_source not in FEAT_CHOICE_SOURCES:
            result.append(choice)
            continue
        options: list[BuilderChoiceOption] = []
        for option in choice.options:
            feat = registry.get_optional(option.reference_id or "")
            if feat is None or not stable_key_is_kind(feat.key, "feat"):
                options.append(option)
                continue
            detail = feat_failure_detail(feat, context, already_acquired=tuple(acquired))
            options.append(option.model_copy(update={
                "disabled_reason": feat_failure_reason(detail),
                "disabled_reason_code": detail.code if detail is not None else None,
                "disabled_reason_params": detail.params if detail is not None else {},
            }))
        patched = choice.model_copy(update={"options": tuple(options)})
        result.append(patched)

        selected = _selection(draft, choice.choice_id)
        if len(selected) != 1:
            continue
        feat = registry.get_optional(selected[0])
        selected_option = next((option for option in options if option.option_id == selected[0]), None)
        if feat is None or selected_option is None or selected_option.disabled_reason is not None:
            continue
        if not stable_key_is_kind(feat.key, "feat"):
            continue
        result.extend(_feat_nested_choices(draft, registry, choice.choice_id, feat))
        acquired.append(feat.key)
    return tuple(result)


def _issue(code: str, path: str, message: str, *refs: str) -> BuilderIssue:
    return BuilderIssue(
        code=code,
        severity=BuilderIssueSeverity.BLOCKING_ERROR,
        path=path,
        message=message,
        related_refs=tuple(refs),
    )


def _selected_child_values(draft: BuilderDraft, opportunity_id: str, field: str) -> tuple[str, ...]:
    return _selection(draft, _child_choice_id(opportunity_id, field))


def _capped_feat_ability_bonuses(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
    raw_bonuses: dict[str, int],
) -> dict[str, int]:
    if not raw_bonuses:
        return {}
    foundation = resolve_creation_summary(draft, registry, choices)
    baseline = {entry.ability: entry.resolved for entry in foundation.ability_scores}
    if not baseline:
        return raw_bonuses
    structural = compile_structural_selections(draft, registry, choices)
    result: dict[str, int] = {}
    for ability, bonus in raw_bonuses.items():
        before_feat = baseline.get(ability, 0) + structural.ability_bonuses.get(ability, 0)
        if before_feat >= FEAT_ABILITY_CAP:
            result[ability] = 0
        else:
            result[ability] = min(bonus, FEAT_ABILITY_CAP - before_feat)
    return result


def compile_feat_acquisitions(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
) -> FeatCompilation:
    choices_by_id = {choice.choice_id: choice for choice in choices}
    acquisitions: list[FeatAcquisition] = []
    ability_bonuses: dict[str, int] = {}
    proficiencies: list[str] = []
    saves: list[str] = []
    skills: list[str] = []
    languages: list[str] = []
    features: list[str] = []
    static_modifiers: list[StaticDerivedModifier] = []
    resources: list[FeatResourceGrant] = []
    spell_access: list[SpellAccessEntry] = []
    issues: list[BuilderIssue] = []
    acquired_refs: list[str] = []
    repeat_distinct: dict[str, set[str]] = {}

    for choice in choices:
        if choice.option_source not in FEAT_CHOICE_SOURCES:
            continue
        selected = _selection(draft, choice.choice_id)
        if len(selected) != 1:
            continue
        option = next((item for item in choice.options if item.option_id == selected[0]), None)
        feat = registry.get_optional(selected[0])
        if option is None or feat is None or option.disabled_reason is not None:
            continue
        if not stable_key_is_kind(feat.key, "feat"):
            continue
        if feat.key in acquired_refs and feat.data.get("repeatable") is not True:
            issues.append(_issue(
                "feat_not_repeatable",
                f"draft_payload.choice_selections.{choice.choice_id}",
                f"{feat.name} cannot be acquired more than once.",
                feat.key,
            ))
            continue

        selections: dict[str, tuple[str, ...]] = {}
        ability_rule = feat.data.get("ability_increase")
        if isinstance(ability_rule, dict):
            mode = ability_rule.get("mode")
            value = ability_rule.get("value", 1)
            if isinstance(value, int):
                if mode == "fixed" and isinstance(ability_rule.get("ability"), str):
                    ability = ability_rule["ability"]
                    ability_bonuses[ability] = ability_bonuses.get(ability, 0) + value
                elif mode == "choice":
                    picked = _selected_child_values(draft, choice.choice_id, "ability")
                    selections["ability"] = picked
                    if len(picked) == 1 and picked[0].startswith("ability:"):
                        ability = picked[0].removeprefix("ability:")
                        allowed = ability_rule.get("abilities")
                        if isinstance(allowed, list) and ability in allowed:
                            ability_bonuses[ability] = ability_bonuses.get(ability, 0) + value
                        else:
                            issues.append(_issue("invalid_feat_choice", choice.choice_id, "Feat ability choice is not legal.", feat.key))
                    else:
                        issues.append(_issue("incomplete_feat_choice", choice.choice_id, "Feat ability choice is incomplete.", feat.key))

        raw_grants = feat.data.get("proficiency_grants")
        if isinstance(raw_grants, list):
            proficiencies.extend(item for item in raw_grants if isinstance(item, str))

        if feat.data.get("saving_throw_grant_from_ability_choice") is True:
            picked = selections.get("ability", ())
            if len(picked) == 1:
                ability = picked[0].removeprefix("ability:")
                index = ABILITY_TO_INDEX.get(ability)
                if index is not None:
                    saves.append(stable_key("srd5.1", "ability", index))

        for raw_modifier in feat.data.get("static_modifiers", []):
            if isinstance(raw_modifier, dict):
                target = raw_modifier.get("target")
                value = raw_modifier.get("value")
                per_level = raw_modifier.get("per_level", False)
                if target in {"max_hp", "passive_perception", "passive_investigation"} and isinstance(value, int) and isinstance(per_level, bool):
                    static_modifiers.append(StaticDerivedModifier(target=target, value=value, per_level=per_level, source_ref=feat.key))

        raw_resource = feat.data.get("resource")
        if isinstance(raw_resource, dict):
            recharge = raw_resource.get("recharge")
            resources.append(FeatResourceGrant(
                resource_id=str(raw_resource.get("resource_id")),
                capacity=int(raw_resource.get("capacity", 1)),
                die_size=(int(raw_resource["die_size"]) if isinstance(raw_resource.get("die_size"), int) else None),
                recharge=tuple(item for item in recharge if item in {"short_rest", "long_rest"}) if isinstance(recharge, list) else (),
                stacking="aggregate-superiority-dice" if raw_resource.get("stacking") == "aggregate-superiority-dice" else "separate",
                source_ref=feat.key,
            ))

        raw_choices = feat.data.get("choices")
        if isinstance(raw_choices, list):
            for raw in raw_choices:
                if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
                    continue
                field = raw["id"]
                values = _selected_child_values(draft, choice.choice_id, field)
                selections[field] = values
                expected = raw.get("choose", 1)
                child = choices_by_id.get(_child_choice_id(choice.choice_id, field))
                if child is not None and child.disabled_reason is not None:
                    continue
                if isinstance(expected, int) and len(values) != expected:
                    issues.append(_issue("incomplete_feat_choice", choice.choice_id, f"{feat.name} requires {expected} selection(s) for {field}.", feat.key))
                    continue
                kind = raw.get("kind")
                if kind == "language":
                    languages.extend(value for value in values if stable_key_is_kind(value, "language"))
                elif kind == "maneuver":
                    features.extend(value for value in values if stable_key_is_kind(value, "feature"))
                elif kind in {"skill_or_tool_proficiency", "weapon_proficiency"}:
                    for value in values:
                        if not stable_key_is_kind(value, "proficiency"):
                            continue
                        parsed = parse_stable_key(value)
                        if parsed.index.startswith("skill-"):
                            skill_ref = stable_key(parsed.source, "skill", parsed.index.removeprefix("skill-"))
                            if registry.get_optional(skill_ref) is not None:
                                skills.append(skill_ref)
                                continue
                        proficiencies.append(value)
                elif kind == "enum" and raw.get("distinct_across_acquisitions") is True:
                    bucket = repeat_distinct.setdefault(feat.key, set())
                    overlap = bucket.intersection(values)
                    if overlap:
                        issues.append(_issue("repeatable_feat_choice_must_differ", choice.choice_id, f"{feat.name} requires a different repeated option.", feat.key))
                    bucket.update(values)
                elif kind == "spell":
                    source_choice = raw.get("from_source_choice")
                    source_values = selections.get(str(source_choice), ()) if source_choice is not None else ()
                    source_key = source_values[0] if len(source_values) == 1 else feat.key
                    access_type = "granted"
                    for spell_ref in values:
                        if not stable_key_is_kind(spell_ref, "spell"):
                            continue
                        digest = sha256(f"{choice.choice_id}|{field}|{spell_ref}".encode("utf-8")).hexdigest()[:20]
                        spell_access.append(SpellAccessEntry(
                            entry_id=f"feat:{digest}",
                            spell_key=spell_ref,
                            source_type="feat",
                            source_key=feat.key,
                            access_type=access_type,
                        ))

        acquisition = FeatAcquisition(
            acquisition_id=_acquisition_id(choice.choice_id),
            feat_ref=feat.key,
            source_opportunity=choice.choice_id,
            selections=selections,
        )
        acquisitions.append(acquisition)
        acquired_refs.append(feat.key)

    capped_ability_bonuses = _capped_feat_ability_bonuses(
        draft,
        registry,
        choices,
        ability_bonuses,
    )
    return FeatCompilation(
        acquisitions=tuple(acquisitions),
        ability_bonuses=capped_ability_bonuses,
        proficiencies=tuple(dict.fromkeys(proficiencies)),
        saving_throw_proficiencies=tuple(dict.fromkeys(saves)),
        skill_refs=tuple(dict.fromkeys(skills)),
        language_refs=tuple(dict.fromkeys(languages)),
        feature_refs=tuple(dict.fromkeys(features)),
        static_modifiers=tuple(static_modifiers),
        resource_grants=tuple(resources),
        spell_access_entries=tuple({entry.entry_id: entry for entry in spell_access}.values()),
        issues=tuple(issues),
    )
