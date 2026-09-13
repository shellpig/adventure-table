from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256

from app.content.identity import parse_stable_key, reference_to_stable_key, stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import (
    FeatAcquisition,
    SpellcastingFocusFact,
    TelepathyFact,
    WeaponProficiencyCategoryFact,
    FeatResourceGrant,
    SpellAccessEntry,
    StaticDerivedModifier,
)
from app.domain.character_builder.m01o_prerequisites import (
    M01OPrerequisiteContext,
    is_m01o_prerequisite_type,
    m01o_requirement_failure,
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
from app.domain.character_builder.progression import progression_summary
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
VARIANT_ANCESTRY_OVERRIDES = {
    "phb2014:race:variant-human": "srd5.1:race:human",
}
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
    ancestry_ref: str | None = None
    lineage_ref: str | None = None
    size: str | None = None
    feature_refs: frozenset[str] = frozenset()
    skill_refs: frozenset[str] = frozenset()
    expertise_refs: frozenset[str] = frozenset()
    spell_refs: frozenset[str] = frozenset()
    class_levels: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatRetrainingPolicy:
    """Feat-linked retraining declared by content (``retraining`` on the feat)."""

    policy: str
    replace_choices: tuple[str, ...]


FEAT_RETRAINING_POLICIES = frozenset({"on_any_level_up", "on_asi_level_up"})


def feat_retraining_policy(feat: ContentEntry | None) -> FeatRetrainingPolicy | None:
    raw = feat.data.get("retraining") if feat is not None else None
    if not isinstance(raw, dict) or raw.get("policy") not in FEAT_RETRAINING_POLICIES:
        return None
    fields = raw.get("replace_choices")
    if not isinstance(fields, list):
        return None
    return FeatRetrainingPolicy(
        policy=str(raw["policy"]),
        replace_choices=tuple(item for item in fields if isinstance(item, str)),
    )


def nested_feat_choice_field(choice_id: str) -> str:
    """``feat:<digest>:<field>`` -> ``<field>`` (see ``_child_choice_id``)."""

    return choice_id.split(":", 2)[2] if choice_id.startswith("feat:") else ""


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
    expertise_refs: tuple[str, ...]
    language_refs: tuple[str, ...]
    feature_refs: tuple[str, ...]
    static_modifiers: tuple[StaticDerivedModifier, ...]
    resource_grants: tuple[FeatResourceGrant, ...]
    spell_access_entries: tuple[SpellAccessEntry, ...]
    walking_speed_bonus: int
    static_facts: tuple[WeaponProficiencyCategoryFact | TelepathyFact | SpellcastingFocusFact, ...]
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

    if is_m01o_prerequisite_type(req_type):
        return m01o_requirement_failure(
            requirement,
            M01OPrerequisiteContext(
                ability_scores=context.abilities,
                ancestry_ref=context.ancestry_ref,
                lineage_ref=context.lineage_ref,
                size=context.size,
                feature_refs=context.feature_refs,
                proficiency_refs=context.proficiencies,
                has_spellcasting=context.has_spellcasting,
            ),
        )

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
            elif failure_type == "ancestry":
                labels.append("a specific ancestry")
            elif failure_type == "lineage":
                labels.append("a specific lineage")
            elif failure_type == "size":
                labels.append("a specific size")
            elif failure_type == "proficiency":
                labels.append("a required proficiency")
            elif str(failure_type).endswith("_context_missing"):
                labels.append("more character origin information")
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
    payload = draft.draft_payload
    race_ref = (
        payload.race_selection.reference_id
        if payload.race_selection is not None
        else None
    )
    race = registry.get_optional(race_ref) if race_ref is not None else None
    race_size = race.data.get("size") if race is not None else None
    nodes = progression_summary(draft, registry)
    return FeatEvaluationContext(
        abilities=abilities,
        proficiencies=frozenset((*_class_starting_proficiencies(draft, registry), *extra_proficiencies)),
        has_spellcasting=any(entry is not None and _class_has_spellcasting(entry) for entry in classes),
        ancestry_ref=VARIANT_ANCESTRY_OVERRIDES.get(race_ref, race_ref),
        lineage_ref=(
            payload.lineage_selection.reference_id
            if payload.lineage_selection is not None
            else (
                payload.subrace_selection.reference_id
                if payload.subrace_selection is not None
                else None
            )
        ),
        size=race_size.lower() if isinstance(race_size, str) else None,
        feature_refs=frozenset(
            feature_ref
            for node in nodes
            for feature_ref in node.automatic_feature_refs
        ),
        class_levels=dict(Counter(item.class_ref for item in payload.level_choices)),
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
    schools: tuple[str, ...] = (),
) -> tuple[ContentEntry, ...]:
    result: list[ContentEntry] = []
    class_spell_refs: set[str] | None = None
    if source_class_ref is not None:
        class_entry = registry.get_optional(source_class_ref)
        raw_spell_list = class_entry.data.get("spell_list") if class_entry is not None else None
        if isinstance(raw_spell_list, list):
            class_spell_refs = {
                key
                for item in raw_spell_list
                if isinstance(item, dict)
                if (key := reference_to_stable_key(item, kinds={"spell"})) is not None
            }
    for spell in registry.list_kind("spell"):
        if level is not None and spell.data.get("level") != level:
            continue
        if ritual is not None and spell.data.get("ritual") is not ritual:
            continue
        if schools:
            school = spell.data.get("school")
            school_index = None
            if isinstance(school, dict):
                school_index = school.get("index")
                if school_index is None and isinstance(school.get("key"), str):
                    school_index = parse_stable_key(school["key"]).index
            if school_index not in schools:
                continue
        if source_class_ref is not None:
            if class_spell_refs is not None:
                if spell.key not in class_spell_refs:
                    continue
                result.append(spell)
                continue
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


def _choice_pool_options(
    registry: ContentRegistry,
    pool: str,
) -> tuple[ContentEntry, ...]:
    return tuple(
        entry
        for entry in registry.list_kind("feature")
        if isinstance(entry.data.get("choice_pool_option"), dict)
        and entry.data["choice_pool_option"].get("pool") == pool
    )


FIGHTER_CLASS_REF = "srd5.1:class:fighter"
WARLOCK_CLASS_REF = "srd5.1:class:warlock"
ELDRITCH_INVOCATIONS_FEATURE = "srd5.1:feature:eldritch-invocations"


def _fighter_fighting_style_options(registry: ContentRegistry) -> tuple[ContentEntry, ...]:
    """Fighting Initiate reuses the canonical Fighter Fighting Style pool."""

    return tuple(
        entry
        for entry in _choice_pool_options(registry, "fighting-style")
        if FIGHTER_CLASS_REF in entry.data["choice_pool_option"].get("eligible_class_refs", ())
    )


def _eldritch_invocation_options(registry: ContentRegistry) -> tuple[ContentEntry, ...]:
    """Canonical Eldritch Invocation pool: SRD invocation list plus later-source pool options."""

    result: list[ContentEntry] = []
    root = registry.get_optional(ELDRITCH_INVOCATIONS_FEATURE)
    feature_specific = root.data.get("feature_specific") if root is not None else None
    invocations = feature_specific.get("invocations") if isinstance(feature_specific, dict) else None
    if isinstance(invocations, list):
        for reference in invocations:
            if not isinstance(reference, dict):
                continue
            key = reference_to_stable_key(reference, kinds={"feature"})
            entry = registry.get_optional(key) if key is not None else None
            if entry is not None:
                result.append(entry)
    result.extend(_choice_pool_options(registry, "eldritch-invocation"))
    return tuple({entry.key: entry for entry in result}.values())


def _srd_url_key(url: object, *, kind: str) -> str | None:
    """SRD invocation prerequisites reference features/spells by API url only."""

    if not isinstance(url, str) or not url:
        return None
    return reference_to_stable_key({"index": url.rstrip("/").rsplit("/", 1)[-1], "url": url}, kinds={kind})


def _invocation_prerequisite_failure(
    entry: ContentEntry,
    context: FeatEvaluationContext | None,
) -> dict[str, object] | None:
    """Eldritch Adept: invocations without prerequisites are open to anyone; the rest need a qualifying Warlock.

    SRD invocations carry ``prerequisites`` (level / feature / spell). Later-source pool
    options express the same thing through ``choice_pool_option``; a bare Warlock 2 gate is
    the pool baseline, not an invocation prerequisite.
    """

    warlock_level = context.class_levels.get(WARLOCK_CLASS_REF, 0) if context is not None else 0
    features = context.feature_refs if context is not None else frozenset()
    spells = context.spell_refs if context is not None else frozenset()
    required_level = 0
    required_features: list[str] = []
    required_spells: list[str] = []

    raw_prerequisites = entry.data.get("prerequisites")
    if isinstance(raw_prerequisites, list):
        for raw in raw_prerequisites:
            if not isinstance(raw, dict):
                continue
            if raw.get("type") == "level" and isinstance(raw.get("level"), int):
                required_level = max(required_level, raw["level"])
            elif raw.get("type") == "feature":
                key = _srd_url_key(raw.get("feature"), kind="feature")
                if key is not None:
                    required_features.append(key)
            elif raw.get("type") == "spell":
                key = _srd_url_key(raw.get("spell"), kind="spell")
                if key is not None:
                    required_spells.append(key)
    pool = entry.data.get("choice_pool_option")
    if isinstance(pool, dict):
        minimum = pool.get("minimum_class_level")
        if isinstance(minimum, int) and minimum > 2:
            required_level = max(required_level, minimum)
        required_features.extend(
            ref for ref in pool.get("required_feature_refs", ()) if isinstance(ref, str)
        )

    if not required_level and not required_features and not required_spells:
        return None
    if warlock_level < max(required_level, 1):
        return {
            "code": "feat_invocation_prerequisite_not_met",
            "reason": "This invocation has a prerequisite that only a qualifying Warlock can meet.",
            "required_warlock_level": max(required_level, 1),
        }
    missing_features = [ref for ref in required_features if ref not in features]
    missing_spells = [ref for ref in required_spells if ref not in spells]
    if missing_features or missing_spells:
        return {
            "code": "feat_invocation_prerequisite_not_met",
            "reason": "This invocation requires another Warlock feature or spell.",
            "required_feature_refs": missing_features,
            "required_spell_refs": missing_spells,
        }
    return None


def _filter_allowed_choice_options(
    options: tuple[BuilderChoiceOption, ...],
    raw: dict[str, object],
) -> tuple[BuilderChoiceOption, ...]:
    allowed_refs = raw.get("allowed_refs")
    if not isinstance(allowed_refs, list):
        return options
    allowed = {item for item in allowed_refs if isinstance(item, str)}
    if not allowed:
        return ()
    return tuple(
        option
        for option in options
        if option.option_id in allowed or option.reference_id in allowed
    )


def _feat_nested_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    opportunity_id: str,
    feat: ContentEntry,
    context: FeatEvaluationContext | None = None,
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
        elif kind == "skill":
            options = _reference_options(
                tuple(
                    entry
                    for entry in registry.list_kind("proficiency")
                    if entry.data.get("type") == "Skills"
                )
            )
        elif kind == "tool":
            options = _reference_options(
                tuple(
                    entry
                    for entry in registry.list_kind("proficiency")
                    if entry.data.get("type") not in {"Armor", "Weapons", "Skills"}
                )
            )
        elif kind == "artisan_tool":
            allowed = {
                "alchemists-supplies",
                "brewers-supplies",
                "calligraphers-supplies",
                "carpenters-tools",
                "cartographers-tools",
                "cobblers-tools",
                "cooks-utensils",
                "glassblowers-tools",
                "jewelers-tools",
                "leatherworkers-tools",
                "masons-tools",
                "painters-supplies",
                "potters-tools",
                "smiths-tools",
                "tinkers-tools",
                "weavers-tools",
                "woodcarvers-tools",
            }
            options = _reference_options(
                tuple(
                    entry
                    for entry in registry.list_kind("proficiency")
                    if parse_stable_key(entry.key).index in allowed
                )
            )
        elif kind == "expertise":
            skill_refs = set(context.skill_refs if context is not None else ())
            prerequisite_choice = raw.get("include_from_choice")
            if isinstance(prerequisite_choice, str) and prerequisite_choice in choice_ids:
                for selected in _selection(draft, choice_ids[prerequisite_choice]):
                    if stable_key_is_kind(selected, "proficiency"):
                        parsed = parse_stable_key(selected)
                        if parsed.index.startswith("skill-"):
                            skill_refs.add(stable_key(parsed.source, "skill", parsed.index.removeprefix("skill-")))
            expertise_refs = set(context.expertise_refs if context is not None else ())
            options = tuple(
                BuilderChoiceOption(
                    option_id=skill_ref,
                    label=_entry_label(entry) if (entry := registry.get_optional(skill_ref)) is not None else skill_ref,
                    kind=BuilderOptionKind.REFERENCE,
                    reference_id=skill_ref,
                    disabled_reason=(
                        "This skill already has expertise."
                        if skill_ref in expertise_refs
                        else None
                    ),
                    disabled_reason_code=(
                        "skill_already_has_expertise"
                        if skill_ref in expertise_refs
                        else None
                    ),
                )
                for skill_ref in sorted(skill_refs)
            )
        elif kind == "maneuver":
            options = _reference_options(_choice_pool_options(registry, "battle-master-maneuver"))
        elif kind == "fighting_style":
            owned = set(context.feature_refs if context is not None else ())
            style_options: list[BuilderChoiceOption] = []
            for entry in _fighter_fighting_style_options(registry):
                option = _reference_options((entry,))[0]
                if entry.key in owned:
                    option = option.model_copy(update={
                        "disabled_reason": "This fighting style is already known.",
                        "disabled_reason_code": "feat_fighting_style_already_known",
                    })
                style_options.append(option)
            options = tuple(style_options)
        elif kind == "invocation":
            invocation_options: list[BuilderChoiceOption] = []
            for entry in _eldritch_invocation_options(registry):
                option = _reference_options((entry,))[0]
                failure = _invocation_prerequisite_failure(entry, context)
                if failure is not None:
                    params = {key: value for key, value in failure.items() if key not in {"code", "reason"}}
                    option = option.model_copy(update={
                        "disabled_reason": failure["reason"],
                        "disabled_reason_code": failure["code"],
                        "disabled_reason_params": {"option_ref": entry.key, **params},
                    })
                invocation_options.append(option)
            options = tuple(invocation_options)
        elif kind == "metamagic":
            options = _reference_options(
                (
                    *_choice_pool_options(registry, "metamagic"),
                    *tuple(
                        entry
                        for entry in registry.list_kind("feature", source="srd5.1")
                        if parse_stable_key(entry.key).index.startswith("metamagic-")
                        and parse_stable_key(entry.key).index
                        not in {"metamagic-1", "metamagic-2", "metamagic-3"}
                    ),
                )
            )
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
            source_ref = raw.get("source_class_ref") if isinstance(raw.get("source_class_ref"), str) else None
            if isinstance(source_choice, str) and source_choice in choice_ids:
                selected_source = _selection(draft, choice_ids[source_choice])
                if len(selected_source) == 1:
                    source_ref = selected_source[0]
                else:
                    disabled_reason = "Choose the feat's spellcasting source first."
                    disabled_code = "feat_spell_source_required"
            level = raw.get("level") if isinstance(raw.get("level"), int) else None
            ritual = raw.get("ritual") if isinstance(raw.get("ritual"), bool) else None
            schools = tuple(item for item in raw.get("schools", ()) if isinstance(item, str))
            options = _reference_options(
                _spell_options(
                    registry,
                    source_class_ref=source_ref,
                    level=level,
                    ritual=ritual,
                    schools=schools,
                )
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

        options = _filter_allowed_choice_options(options, raw)
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


def _with_selected_grants(
    choices: tuple[BuilderChoice, ...],
    context: FeatEvaluationContext,
) -> FeatEvaluationContext:
    """Add features / spells the draft already selected (class style, Pact Boon, cantrips...).

    Only the submitted class/origin choices count; nested feat choices are compiled
    later, so a feat's own selection can never disable itself.
    """

    features = set(context.feature_refs)
    spells = set(context.spell_refs)
    for choice in choices:
        option_by_id = {option.option_id: option for option in choice.options}
        for option_id in choice.selected_option_ids:
            option = option_by_id.get(option_id)
            reference = option.reference_id if option is not None else None
            if reference is None:
                continue
            try:
                if stable_key_is_kind(reference, "feature"):
                    features.add(reference)
                elif stable_key_is_kind(reference, "spell"):
                    spells.add(reference)
            except ValueError:
                continue
    return replace(context, feature_refs=frozenset(features), spell_refs=frozenset(spells))


def enrich_feat_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
    context: FeatEvaluationContext,
) -> tuple[BuilderChoice, ...]:
    """Apply one prerequisite/repeatability resolver to Variant Human and ASI feat opportunities."""

    result: list[BuilderChoice] = []
    acquired: list[str] = []
    context = _with_selected_grants(choices, context)
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
        result.extend(_feat_nested_choices(draft, registry, choice.choice_id, feat, context))
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
    expertise: list[str] = []
    languages: list[str] = []
    features: list[str] = []
    static_modifiers: list[StaticDerivedModifier] = []
    walking_speed_bonus = 0
    static_facts: list[WeaponProficiencyCategoryFact | TelepathyFact | SpellcastingFocusFact] = []
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
                            issues.append(_issue("invalid_feat_choice", f"draft_payload.choice_selections.{choice.choice_id}", "Feat ability choice is not legal.", feat.key))
                    else:
                        issues.append(_issue("incomplete_feat_choice", f"draft_payload.choice_selections.{choice.choice_id}", "Feat ability choice is incomplete.", feat.key))

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

        for raw_mechanic in feat.data.get("mechanics", []):
            if (
                isinstance(raw_mechanic, dict)
                and raw_mechanic.get("kind") == "walking_speed_bonus"
                and isinstance(raw_mechanic.get("value"), int)
            ):
                walking_speed_bonus += raw_mechanic["value"]

        raw_resource = feat.data.get("resource")
        if isinstance(raw_resource, dict):
            recharge = raw_resource.get("recharge")
            allowed_spend_tags = raw_resource.get("allowed_spend_tags")
            resources.append(FeatResourceGrant(
                resource_id=str(raw_resource.get("resource_id")),
                capacity=int(raw_resource.get("capacity", 1)),
                die_size=(int(raw_resource["die_size"]) if isinstance(raw_resource.get("die_size"), int) else None),
                recharge=tuple(item for item in recharge if item in {"short_rest", "long_rest"}) if isinstance(recharge, list) else (),
                allowed_spend_tags=tuple(
                    item for item in allowed_spend_tags if isinstance(item, str)
                ) if isinstance(allowed_spend_tags, list) else (),
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
                    issues.append(_issue("incomplete_feat_choice", f"draft_payload.choice_selections.{choice.choice_id}", f"{feat.name} requires {expected} selection(s) for {field}.", feat.key))
                    continue
                kind = raw.get("kind")
                if kind == "language":
                    languages.extend(value for value in values if stable_key_is_kind(value, "language"))
                elif kind in {"maneuver", "fighting_style", "invocation", "metamagic"}:
                    features.extend(value for value in values if stable_key_is_kind(value, "feature"))
                elif kind == "skill":
                    for value in values:
                        if stable_key_is_kind(value, "proficiency"):
                            parsed = parse_stable_key(value)
                            if parsed.index.startswith("skill-"):
                                skill_ref = stable_key(parsed.source, "skill", parsed.index.removeprefix("skill-"))
                                if registry.get_optional(skill_ref) is not None:
                                    skills.append(skill_ref)
                elif kind == "expertise":
                    for value in values:
                        if stable_key_is_kind(value, "skill"):
                            expertise.append(value)
                elif kind in {"skill_or_tool_proficiency", "weapon_proficiency", "tool", "artisan_tool"}:
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
                        issues.append(_issue("repeatable_feat_choice_must_differ", f"draft_payload.choice_selections.{choice.choice_id}", f"{feat.name} requires a different repeated option.", feat.key))
                    bucket.update(values)
                elif kind == "spell":
                    source_choice = raw.get("from_source_choice")
                    source_values = selections.get(str(source_choice), ()) if source_choice is not None else ()
                    source_key = source_values[0] if len(source_values) == 1 else feat.key
                    access_type = "granted"
                    selected_ability = None
                    selected = selections.get("ability", ())
                    if len(selected) == 1 and selected[0].startswith("ability:"):
                        selected_ability = selected[0].removeprefix("ability:")
                    casting_ability = raw.get("casting_ability")
                    if casting_ability == "$ability_choice":
                        casting_ability = selected_ability
                    recharge = raw.get("recharge_types")
                    uses = raw.get("uses_per_rest")
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
                            casting_ability=casting_ability if isinstance(casting_ability, str) else None,
                            uses_per_rest=uses if isinstance(uses, int) else None,
                            recharge_types=tuple(
                                item for item in recharge if item in {"short_rest", "long_rest"}
                            ) if isinstance(recharge, list) else (),
                        ))

        raw_languages = feat.data.get("language_grants")
        if isinstance(raw_languages, list):
            languages.extend(value for value in raw_languages if isinstance(value, str))

        raw_features = feat.data.get("feature_grants")
        if isinstance(raw_features, list):
            features.extend(value for value in raw_features if isinstance(value, str))

        raw_spell_grants = feat.data.get("spell_grants")
        if isinstance(raw_spell_grants, list):
            selected_ability = None
            selected = selections.get("ability", ())
            if len(selected) == 1 and selected[0].startswith("ability:"):
                selected_ability = selected[0].removeprefix("ability:")
            for raw_spell in raw_spell_grants:
                if not isinstance(raw_spell, dict):
                    continue
                spell_ref = raw_spell.get("spell_ref")
                if not isinstance(spell_ref, str) or not stable_key_is_kind(spell_ref, "spell"):
                    continue
                ability = raw_spell.get("casting_ability")
                if ability == "$ability_choice":
                    ability = selected_ability
                recharge = raw_spell.get("recharge_types")
                uses = raw_spell.get("uses_per_rest")
                digest = sha256(f"{choice.choice_id}|fixed|{spell_ref}".encode("utf-8")).hexdigest()[:20]
                spell_access.append(SpellAccessEntry(
                    entry_id=f"feat:{digest}",
                    spell_key=spell_ref,
                    source_type="feat",
                    source_key=feat.key,
                    access_type="granted",
                    casting_ability=ability if isinstance(ability, str) else None,
                    uses_per_rest=uses if isinstance(uses, int) else None,
                    recharge_types=tuple(
                        item for item in recharge if item in {"short_rest", "long_rest"}
                    ) if isinstance(recharge, list) else (),
                ))

        for raw_mechanic in feat.data.get("mechanics", []):
            if not isinstance(raw_mechanic, dict):
                continue
            mechanic_kind = raw_mechanic.get("kind")
            if mechanic_kind == "weapon_proficiency_category":
                static_facts.append(WeaponProficiencyCategoryFact(
                    category=raw_mechanic.get("category"),
                    source_ref=feat.key,
                ))
            elif mechanic_kind == "one_way_telepathy":
                static_facts.append(TelepathyFact(
                    range_ft=raw_mechanic.get("range_ft"),
                    requires_visible_target=bool(raw_mechanic.get("requires_visible_target")),
                    requires_shared_language=bool(raw_mechanic.get("requires_shared_language")),
                    grants_reply=bool(raw_mechanic.get("grants_reply")),
                    source_ref=feat.key,
                ))
            elif mechanic_kind == "spellcasting_focus_from_selected_tool":
                # The focus is the very tool the acquisition selected; one choice, one fact.
                tool_choice = raw_mechanic.get("tool_choice")
                selected_tools = selections.get(str(tool_choice), ()) if tool_choice is not None else ()
                if len(selected_tools) == 1 and stable_key_is_kind(selected_tools[0], "proficiency"):
                    static_facts.append(SpellcastingFocusFact(
                        tool_ref=selected_tools[0],
                        casting_ability=raw_mechanic.get("applies_to_casting_ability"),
                        source_ref=feat.key,
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
        expertise_refs=tuple(dict.fromkeys(expertise)),
        language_refs=tuple(dict.fromkeys(languages)),
        feature_refs=tuple(dict.fromkeys(features)),
        static_modifiers=tuple(static_modifiers),
        walking_speed_bonus=walking_speed_bonus,
        static_facts=tuple(static_facts),
        resource_grants=tuple(resources),
        spell_access_entries=tuple({entry.entry_id: entry for entry in spell_access}.values()),
        issues=tuple(issues),
    )
