from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any

from app.content.identity import parse_stable_key, reference_to_stable_key, stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry, ContentValidationError
from app.content.schemas import ContentEntry
from app.domain.character.schemas import CharacterBuild, SpellAccessEntry
from app.domain.character_builder.basics import resolve_creation_summary
from app.domain.character_builder.compiler import BuilderCompileResult
from app.domain.character_builder.m01k_feats import (
    FeatEvaluationContext,
    feat_failure_detail,
    feat_failure_reason,
)
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
)
from app.domain.character_builder.validation import make_validation_result
from app.domain.rules.spellcasting import spellcasting_ability


SPELL_SNIPER = "phb2014:feat:spell-sniper"
MAGIC_INITIATE = "phb2014:feat:magic-initiate"
RITUAL_CASTER = "phb2014:feat:ritual-caster"
FEAT_SPELL_SOURCES = {SPELL_SNIPER, MAGIC_INITIATE, RITUAL_CASTER}
FEAT_PARENT_SOURCES = {"content:race-feat", "content:asi-feat"}

# A class being a spellcasting class is not enough for the PHB feat prerequisite:
# the character must already be able to cast at least one spell at that point in
# the level rail. Full casters and Artificer start at 1; Paladin/Ranger at 2.
SPELLCASTING_START_LEVEL = {
    "artificer": 1,
    "bard": 1,
    "cleric": 1,
    "druid": 1,
    "sorcerer": 1,
    "warlock": 1,
    "wizard": 1,
    "paladin": 2,
    "ranger": 2,
}


def _blocking(
    code: str,
    path: str,
    message: str,
    *refs: str,
    params: dict[str, object] | None = None,
) -> BuilderIssue:
    return BuilderIssue(
        code=code,
        severity=BuilderIssueSeverity.BLOCKING_ERROR,
        path=path,
        message=message,
        message_params=params or {},
        related_refs=tuple(refs),
    )


class _CoreRegistryWithoutKPrerequisiteGating:
    """Delegate to ContentRegistry while deferring K prerequisite gating.

    The pre-K structural choice builder knows only the old SRD ability-only feat
    prerequisite shape. K's real resolver needs level-ordered ability,
    proficiency, spellcasting and acquisition context. Supplying PHB K feats to
    that legacy gate would disable them before the K resolver gets a chance to
    evaluate them. This view removes only ``prerequisites`` from phb2014 feats
    during the core compilation; all grants/choices/repeatability stay intact.
    ``apply_m01k_post_compile`` then applies the authoritative K resolver to the
    resulting options and final validation.
    """

    def __init__(self, registry: ContentRegistry) -> None:
        self._registry = registry
        self.enabled_pack_ids = registry.enabled_pack_ids

    @staticmethod
    def _patched(entry: ContentEntry | None) -> ContentEntry | None:
        if entry is None:
            return None
        try:
            parsed = parse_stable_key(entry.key)
        except ValueError:
            return entry
        if parsed.source != "phb2014" or parsed.kind != "feat":
            return entry
        data = dict(entry.data)
        data["prerequisites"] = []
        return entry.model_copy(update={"data": data})

    def get(self, key: str) -> ContentEntry:
        return self._patched(self._registry.get(key))  # type: ignore[return-value]

    def get_optional(self, key: str) -> ContentEntry | None:
        return self._patched(self._registry.get_optional(key))

    def resolve(self, *parts: str) -> ContentEntry:
        if len(parts) == 2:
            source = "srd5.1"
            kind, index = parts
        elif len(parts) == 3:
            source, kind, index = parts
        else:
            raise TypeError("resolve expects (kind, index) or (source, kind, index)")
        return self.get(stable_key(source, kind, index))

    def resolve_reference(
        self,
        reference: dict[str, Any],
        *,
        kinds: set[str] | None = None,
    ) -> ContentEntry:
        try:
            key = reference_to_stable_key(reference, kinds=kinds)
        except ValueError as exc:
            raise ContentValidationError(str(exc)) from exc
        if key is None:
            raise ContentValidationError("unsupported content reference shape")
        return self.get(key)

    def list_kind(
        self,
        kind: str,
        *,
        source: str | None = None,
    ) -> tuple[ContentEntry, ...]:
        return tuple(
            self._patched(entry)  # type: ignore[arg-type]
            for entry in self._registry.list_kind(kind, source=source)
        )

    def __getattr__(self, name: str) -> object:
        return getattr(self._registry, name)


def prepare_m01k_core_registry(registry: ContentRegistry) -> ContentRegistry:
    """Return a read-only registry view for the legacy core compiler."""

    return _CoreRegistryWithoutKPrerequisiteGating(registry)  # type: ignore[return-value]


def _choice_position(choice: BuilderChoice) -> tuple[int, int, int]:
    if choice.option_source == "content:race-feat":
        return (0, 0, 0)
    parts = choice.choice_id.split(":")
    if (
        choice.option_source == "content:asi-feat"
        and len(parts) >= 4
        and parts[0] == "level"
        and parts[1].isdigit()
        and parts[-1].isdigit()
    ):
        return (int(parts[1]), 1, int(parts[-1]))
    return (99, 99, 99)


def _choice_level(choice: BuilderChoice) -> int:
    return max(1, _choice_position(choice)[0])


def _reference_proficiencies(raw: object) -> set[str]:
    result: set[str] = set()
    if not isinstance(raw, list):
        return result
    for reference in raw:
        if not isinstance(reference, dict):
            continue
        try:
            key = reference_to_stable_key(reference, kinds={"proficiency"})
        except ValueError:
            key = None
        if key is not None:
            result.add(key)
    return result


def _origin_proficiencies(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
) -> set[str]:
    # Exclude all feat/ASI choices so a later feat cannot satisfy an earlier
    # prerequisite merely because the final high-level draft already contains it.
    origin_choices = tuple(
        choice
        for choice in choices
        if choice.option_source not in FEAT_PARENT_SOURCES
        and not (choice.option_source or "").startswith("content:feat:")
        and choice.option_source != "content:asi-ability"
        and not choice.choice_id.startswith("level:")
    )
    summary = resolve_creation_summary(draft, registry, origin_choices)
    return {
        grant.reference_id
        for grant in summary.grants
        if grant.kind == "proficiency" and grant.reference_id is not None
    }


def _class_proficiencies_through_level(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
    character_level: int,
) -> set[str]:
    result: set[str] = set()
    seen_classes: set[str] = set()
    for level_index, level_choice in enumerate(
        draft.draft_payload.level_choices[:character_level],
        start=1,
    ):
        class_entry = registry.get_optional(level_choice.class_ref)
        if class_entry is None:
            continue
        if level_index == 1:
            result.update(_reference_proficiencies(class_entry.data.get("proficiencies")))
        elif class_entry.key not in seen_classes:
            multiclass = class_entry.data.get("multi_classing")
            if isinstance(multiclass, dict):
                result.update(_reference_proficiencies(multiclass.get("proficiencies")))
        seen_classes.add(class_entry.key)

    # User-selected class proficiency rows are also authoritative grants. Keep
    # their level ordering so a future multiclass selection cannot satisfy an
    # earlier feat prerequisite in Direct High-Level Create.
    for choice in choices:
        if choice.option_source != "content:class-proficiency":
            continue
        parts = choice.choice_id.split(":")
        if len(parts) < 2 or parts[0] != "level" or not parts[1].isdigit():
            continue
        if int(parts[1]) > character_level:
            continue
        selected = draft.draft_payload.choice_selections.get(choice.choice_id)
        if selected is None:
            continue
        option_by_id = {option.option_id: option for option in choice.options}
        for option_id in selected.selected_option_ids:
            option = option_by_id.get(option_id)
            if option is not None and option.reference_id is not None:
                try:
                    if stable_key_is_kind(option.reference_id, "proficiency"):
                        result.add(option.reference_id)
                except ValueError:
                    pass
    return result


def _class_spellcasting_through_level(
    draft: BuilderDraft,
    registry: ContentRegistry,
    build: CharacterBuild | None,
    character_level: int,
) -> bool:
    counts: Counter[str] = Counter(
        level_choice.class_ref
        for level_choice in draft.draft_payload.level_choices[:character_level]
    )
    for class_ref, class_level in counts.items():
        class_entry = registry.get_optional(class_ref)
        if class_entry is None:
            continue
        try:
            index = parse_stable_key(class_ref, kinds={"class"}).index
        except ValueError:
            continue
        minimum = SPELLCASTING_START_LEVEL.get(index)
        if minimum is not None and class_level >= minimum:
            return True

    # M01-J third-caster subclass profiles are present on the candidate Build.
    # Their acquisition-level content gate prevents a future subclass from
    # satisfying Variant Human at level 1, while Fighter/Rogue ASIs begin after
    # their level-3 subclass choice.
    if build is not None:
        for profile in build.spellcasting_profiles:
            if profile.source_type != "subclass":
                continue
            class_level = counts.get(profile.class_ref, 0)
            source = registry.get_optional(profile.source_key)
            minimum = source.data.get("acquisition_class_level") if source is not None else None
            if not isinstance(minimum, int):
                minimum = 3
            if class_level >= minimum:
                return True
    return False


def _starting_ability_context(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
) -> tuple[dict[str, int] | None, set[str]]:
    # resolve_creation_summary handles base generation, ancestry choices and
    # Numeric Overrides, while ASI and M01-K feat bonuses are deliberately not
    # part of its ability-bonus categories.
    summary = resolve_creation_summary(draft, registry, choices)
    if not summary.ability_scores:
        return None, set()
    return (
        {entry.ability: entry.effective for entry in summary.ability_scores},
        {entry.ability for entry in summary.ability_scores if entry.overridden},
    )


def _apply_asi_after_opportunity(
    draft: BuilderDraft,
    choice: BuilderChoice,
    abilities: dict[str, int] | None,
    overridden: set[str],
) -> None:
    if abilities is None or choice.option_source != "content:asi-feat":
        return
    selected_parent = draft.draft_payload.choice_selections.get(choice.choice_id)
    asi_branch = next(
        (option.option_id for option in choice.options if option.branch_key == "asi"),
        None,
    )
    if selected_parent is None or asi_branch is None or selected_parent.selected_option_ids != (asi_branch,):
        return
    parts = choice.choice_id.split(":")
    if len(parts) < 4:
        return
    ability_choice_id = f"level:{parts[1]}:asi-abilities:{parts[-1]}"
    selected = draft.draft_payload.choice_selections.get(ability_choice_id)
    if selected is None:
        return
    for option_id in selected.selected_option_ids:
        if not option_id.startswith("ability:"):
            continue
        ability = option_id.removeprefix("ability:")
        if ability in abilities and ability not in overridden:
            abilities[ability] += 1


def _apply_selected_feat_context(
    feat: ContentEntry,
    opportunity_id: str,
    build: CharacterBuild | None,
    abilities: dict[str, int] | None,
    overridden: set[str],
    feat_proficiencies: set[str],
) -> bool:
    acquisition = None
    if build is not None:
        acquisition = next(
            (
                item
                for item in build.feat_acquisitions
                if item.source_opportunity == opportunity_id and item.feat_ref == feat.key
            ),
            None,
        )

    ability_rule = feat.data.get("ability_increase")
    if abilities is not None and isinstance(ability_rule, dict):
        value = ability_rule.get("value", 1)
        if isinstance(value, int):
            ability = None
            if ability_rule.get("mode") == "fixed" and isinstance(ability_rule.get("ability"), str):
                ability = ability_rule["ability"]
            elif ability_rule.get("mode") == "choice" and acquisition is not None:
                selected = acquisition.selections.get("ability", ())
                if len(selected) == 1 and selected[0].startswith("ability:"):
                    ability = selected[0].removeprefix("ability:")
            if ability in abilities and ability not in overridden:
                abilities[ability] += value

    grants = feat.data.get("proficiency_grants")
    if isinstance(grants, list):
        feat_proficiencies.update(
            item for item in grants if isinstance(item, str)
        )

    # A previous feat grants spellcasting context only once it actually compiled
    # at least one spell access row. This avoids an incomplete Magic Initiate
    # selection from unlocking War Caster in the same invalid draft.
    if build is not None:
        return any(
            entry.source_type == "feat" and entry.source_key == feat.key
            for entry in build.spell_access_entries
        )
    return False


def _base_unrepresented_feats(
    draft: BuilderDraft,
    base_build: CharacterBuild | None,
    parent_choices: tuple[BuilderChoice, ...],
) -> list[str]:
    if base_build is None:
        return []
    represented = {
        option_id
        for choice in parent_choices
        for option_id in (
            draft.draft_payload.choice_selections.get(choice.choice_id).selected_option_ids
            if draft.draft_payload.choice_selections.get(choice.choice_id) is not None
            else ()
        )
        if registry_safe_feat_id(option_id)
    }
    return [feat_ref for feat_ref in base_build.feat_refs if feat_ref not in represented]


def registry_safe_feat_id(value: str) -> bool:
    try:
        return stable_key_is_kind(value, "feat")
    except ValueError:
        return False


def _apply_ordered_feat_prerequisites(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
    build: CharacterBuild | None,
    base_build: CharacterBuild | None,
) -> tuple[tuple[BuilderChoice, ...], tuple[BuilderIssue, ...]]:
    parent_choices = tuple(
        sorted(
            (choice for choice in choices if choice.option_source in FEAT_PARENT_SOURCES),
            key=_choice_position,
        )
    )
    abilities, overridden = _starting_ability_context(draft, registry, choices)
    origin_proficiencies = _origin_proficiencies(draft, registry, choices)
    feat_proficiencies: set[str] = set()
    acquired = _base_unrepresented_feats(draft, base_build, parent_choices)
    feat_spellcasting = False
    patched_by_id: dict[str, BuilderChoice] = {}
    issues: list[BuilderIssue] = []

    for choice in parent_choices:
        level = _choice_level(choice)
        context = FeatEvaluationContext(
            abilities=dict(abilities) if abilities is not None else None,
            proficiencies=frozenset(
                origin_proficiencies
                | _class_proficiencies_through_level(draft, registry, choices, level)
                | feat_proficiencies
            ),
            has_spellcasting=(
                feat_spellcasting
                or _class_spellcasting_through_level(draft, registry, build, level)
            ),
        )
        options = []
        for option in choice.options:
            feat = registry.get_optional(option.reference_id or "")
            if feat is None or not registry_safe_feat_id(feat.key):
                options.append(option)
                continue
            detail = feat_failure_detail(feat, context, already_acquired=tuple(acquired))
            options.append(
                option.model_copy(
                    update={
                        "disabled_reason": feat_failure_reason(detail),
                        "disabled_reason_code": detail.code if detail is not None else None,
                        "disabled_reason_params": detail.params if detail is not None else {},
                    }
                )
            )
        patched = choice.model_copy(update={"options": tuple(options)})
        patched_by_id[choice.choice_id] = patched

        selected = draft.draft_payload.choice_selections.get(choice.choice_id)
        if selected is None or len(selected.selected_option_ids) != 1:
            _apply_asi_after_opportunity(draft, patched, abilities, overridden)
            continue
        selected_id = selected.selected_option_ids[0]
        selected_option = next((option for option in options if option.option_id == selected_id), None)
        selected_feat = registry.get_optional(selected_id)
        if selected_feat is None or not registry_safe_feat_id(selected_feat.key):
            _apply_asi_after_opportunity(draft, patched, abilities, overridden)
            continue

        detail = feat_failure_detail(selected_feat, context, already_acquired=tuple(acquired))
        if detail is not None or selected_option is None or selected_option.disabled_reason is not None:
            failure = detail
            code = failure.code if failure is not None else "illegal_feat_choice"
            params = failure.params if failure is not None else {"feat_ref": selected_feat.key}
            issues.append(
                _blocking(
                    code,
                    f"draft_payload.choice_selections.{choice.choice_id}",
                    "The selected feat does not satisfy its prerequisite or acquisition rule at this point in the level progression.",
                    selected_feat.key,
                    params=params,
                )
            )
            continue

        acquired.append(selected_feat.key)
        feat_spellcasting = (
            feat_spellcasting
            or _apply_selected_feat_context(
                selected_feat,
                choice.choice_id,
                build,
                abilities,
                overridden,
                feat_proficiencies,
            )
        )

    return (
        tuple(patched_by_id.get(choice.choice_id, choice) for choice in choices),
        tuple(issues),
    )


def _spell_sniper_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
) -> tuple[tuple[BuilderChoice, ...], tuple[BuilderIssue, ...]]:
    """Restrict Spell Sniper to cantrips that actually make a spell attack."""

    result: list[BuilderChoice] = []
    issues: list[BuilderIssue] = []
    for choice in choices:
        if choice.source_ref != SPELL_SNIPER or choice.option_source != "content:feat:spell":
            result.append(choice)
            continue

        legal_options = tuple(
            option
            for option in choice.options
            if option.reference_id is not None
            and (spell := registry.get_optional(option.reference_id)) is not None
            and spell.data.get("level") == 0
            and spell.data.get("attack_type") in {"melee", "ranged"}
        )
        legal_ids = {option.option_id for option in legal_options}
        selected = draft.draft_payload.choice_selections.get(choice.choice_id)
        if selected is not None:
            illegal = tuple(
                option_id
                for option_id in selected.selected_option_ids
                if option_id not in legal_ids
            )
            if illegal:
                issues.append(
                    _blocking(
                        "illegal_feat_spell_choice",
                        f"draft_payload.choice_selections.{choice.choice_id}",
                        "Spell Sniper must select a cantrip that requires a spell attack roll from the chosen source class.",
                        SPELL_SNIPER,
                        *illegal,
                    )
                )
        result.append(choice.model_copy(update={"options": legal_options}))
    return tuple(result), tuple(issues)


def _validate_nested_feat_choices(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
) -> tuple[BuilderIssue, ...]:
    issues: list[BuilderIssue] = []
    for choice in choices:
        if not (choice.option_source or "").startswith("content:feat:"):
            continue
        selected = draft.draft_payload.choice_selections.get(choice.choice_id)
        if selected is None:
            continue
        option_by_id = {option.option_id: option for option in choice.options}
        illegal = tuple(
            option_id
            for option_id in selected.selected_option_ids
            if option_id not in option_by_id
            or option_by_id[option_id].disabled_reason is not None
        )
        if illegal:
            issues.append(
                _blocking(
                    "illegal_feat_nested_choice",
                    f"draft_payload.choice_selections.{choice.choice_id}",
                    "A feat-specific selection is not legal for the selected feat source or option pool.",
                    *(filter(registry_safe_feat_id, (choice.source_ref or "",))),
                    *illegal,
                    params={"choice_id": choice.choice_id, "option_ids": list(illegal)},
                )
            )
    return tuple(issues)


def _feat_spell_source_ability(
    build: CharacterBuild,
    feat_ref: str,
    registry: ContentRegistry,
) -> str | None:
    acquisitions = tuple(
        acquisition
        for acquisition in build.feat_acquisitions
        if acquisition.feat_ref == feat_ref
    )
    if len(acquisitions) != 1:
        return None
    source = acquisitions[0].selections.get("spell-source", ())
    if len(source) != 1:
        return None
    return spellcasting_ability(source[0], registry)


def _normalize_feat_spell_access(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> CharacterBuild:
    """Materialize casting-source semantics on feat-granted spell access rows."""

    ability_by_feat = {
        feat_ref: _feat_spell_source_ability(build, feat_ref, registry)
        for feat_ref in FEAT_SPELL_SOURCES
    }
    acquisitions_by_feat = {
        acquisition.feat_ref: acquisition
        for acquisition in build.feat_acquisitions
        if acquisition.feat_ref in FEAT_SPELL_SOURCES
    }

    entries: list[SpellAccessEntry] = []
    for entry in build.spell_access_entries:
        if entry.source_type != "feat" or entry.source_key not in FEAT_SPELL_SOURCES:
            entries.append(entry)
            continue

        updates: dict[str, object] = {}
        ability = ability_by_feat.get(entry.source_key)
        if ability is not None:
            updates["casting_ability"] = ability

        if entry.source_key == MAGIC_INITIATE:
            acquisition = acquisitions_by_feat.get(MAGIC_INITIATE)
            selected_level_one = (
                acquisition.selections.get("spell", ())
                if acquisition is not None
                else ()
            )
            if entry.spell_key in selected_level_one:
                updates["uses_per_rest"] = 1
                updates["rest_type"] = "long_rest"

        entries.append(entry.model_copy(update=updates) if updates else entry)

    return build.model_copy(update={"spell_access_entries": tuple(entries)})


def _preserve_legacy_base_feat_summary(
    build: CharacterBuild,
    base_build: CharacterBuild | None,
) -> CharacterBuild:
    if base_build is None:
        return build
    # Pre-K immutable Builds can contain feat_refs without acquisition rows or
    # recoverable Draft provenance. Feats have no K retraining workflow, so keep
    # those historical identities instead of silently dropping them on Level Up.
    acquisition_refs = {item.feat_ref for item in base_build.feat_acquisitions}
    legacy_refs = tuple(
        feat_ref for feat_ref in base_build.feat_refs if feat_ref not in acquisition_refs
    )
    if not legacy_refs:
        return build
    return build.model_copy(
        update={"feat_refs": tuple(dict.fromkeys((*legacy_refs, *build.feat_refs)))}
    )


def apply_m01k_post_compile(
    draft: BuilderDraft,
    registry: ContentRegistry,
    compiled: BuilderCompileResult,
    *,
    base_build: CharacterBuild | None = None,
) -> BuilderCompileResult:
    choices, prerequisite_issues = _apply_ordered_feat_prerequisites(
        draft,
        registry,
        compiled.choices,
        compiled.build_candidate,
        base_build,
    )
    choices, spell_sniper_issues = _spell_sniper_choices(draft, registry, choices)
    nested_issues = _validate_nested_feat_choices(draft, choices)
    build = compiled.build_candidate
    if build is not None:
        build = _normalize_feat_spell_access(build, registry)
        build = _preserve_legacy_base_feat_summary(build, base_build)
    validation = make_validation_result(
        (
            *compiled.validation.issues,
            *prerequisite_issues,
            *spell_sniper_issues,
            *nested_issues,
        )
    )
    return replace(
        compiled,
        build_candidate=build,
        choices=choices,
        validation=validation,
    )
