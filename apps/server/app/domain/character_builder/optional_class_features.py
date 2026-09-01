from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha1
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.content.identity import parse_stable_key, reference_to_stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import CharacterBuild, SpellAccessEntry
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderMode,
    BuilderOptionKind,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


OptionalFeatureMode = Literal["addition", "expanded_choice", "replacement", "retraining"]
OptionalFeatureActivation = Literal["choice", "automatic"]
RetrainingKind = Literal["feature_pool", "cantrip"]
NestedChoiceKind = Literal["cantrip", "feature_pool"]


class ChoicePoolExtension(StrictModel):
    target_feature_indices: tuple[str, ...]
    option_refs: tuple[str, ...]


class SpellAccessExpansion(StrictModel):
    class_ref: str
    spell_refs: tuple[str, ...]


class RetrainingStrategy(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    kind: RetrainingKind
    target_feature_indices: tuple[str, ...] = ()
    class_ref: str | None = None


class RetrainingSpec(StrictModel):
    class_levels: tuple[int, ...] = ()
    any_level_after_minimum: bool = False
    strategies: tuple[RetrainingStrategy, ...]


class OptionalClassFeatureSpec(StrictModel):
    parent_class_ref: str
    minimum_class_level: int = Field(ge=1, le=20)
    mode: OptionalFeatureMode
    activation: OptionalFeatureActivation = "choice"
    replaces_feature_refs: tuple[str, ...] = ()
    replaces_feature_index_prefixes: tuple[str, ...] = ()
    replaces_feature_index_contains: tuple[str, ...] = ()
    replacement_target_required: bool = False
    pool_extensions: tuple[ChoicePoolExtension, ...] = ()
    spell_access: SpellAccessExpansion | None = None
    retraining: RetrainingSpec | None = None


class NestedChoiceSpec(StrictModel):
    kind: NestedChoiceKind
    choose: int = Field(ge=1)
    class_ref: str | None = None
    casting_ability: str | None = None
    target_feature_indices: tuple[str, ...] = ()


class ChoicePoolOptionSpec(StrictModel):
    pool: str = Field(min_length=1, max_length=80)
    eligible_class_refs: tuple[str, ...] = ()
    minimum_class_level: int = Field(default=1, ge=1, le=20)
    nested: NestedChoiceSpec | None = None


@dataclass(frozen=True)
class OptionalFeatureRuntime:
    registry: "OptionalFeatureRegistry"
    choices: tuple[BuilderChoice, ...]
    active_feature_refs: tuple[str, ...]
    specs: dict[str, OptionalClassFeatureSpec]
    issues: tuple[BuilderIssue, ...]


class OptionalFeatureRegistry:
    """Read-only content overlay for M01-I expanded pools and spell access.

    The underlying registry stays authoritative. This view only augments rules
    declared by active TCE Optional Class Feature metadata, so the compiler can
    reuse the existing structural/spellcasting machinery without class-specific
    branches.
    """

    def __init__(
        self,
        base: ContentRegistry,
        specs: dict[str, OptionalClassFeatureSpec],
        active_feature_refs: tuple[str, ...],
    ) -> None:
        self._base = base
        self._specs = specs
        self._active = frozenset(active_feature_refs)
        self.enabled_pack_ids = base.enabled_pack_ids

    def _active_specs(self) -> tuple[OptionalClassFeatureSpec, ...]:
        return tuple(self._specs[key] for key in self._active if key in self._specs)

    @staticmethod
    def _reference_key(value: object) -> str | None:
        if not isinstance(value, dict):
            return None
        try:
            return reference_to_stable_key(value)
        except ValueError:
            return None

    def _append_pool_options(
        self,
        value: object,
        option_refs: tuple[str, ...],
    ) -> None:
        if isinstance(value, dict):
            source = value.get("from")
            if isinstance(source, dict) and source.get("option_set_type") == "options_array":
                raw_options = source.get("options")
                if isinstance(raw_options, list):
                    present: set[str] = set()
                    for raw in raw_options:
                        if not isinstance(raw, dict):
                            continue
                        reference = raw.get("item") if raw.get("option_type") == "reference" else None
                        key = self._reference_key(reference)
                        if key is not None:
                            present.add(key)
                    for ref in option_refs:
                        if ref in present:
                            continue
                        target = self._base.get_optional(ref)
                        if target is None or not stable_key_is_kind(target.key, "feature"):
                            continue
                        raw_options.append(
                            {
                                "option_type": "reference",
                                "item": {"key": target.key, "name": target.name},
                            }
                        )
                        present.add(ref)
            for child in value.values():
                self._append_pool_options(child, option_refs)
        elif isinstance(value, list):
            for child in value:
                self._append_pool_options(child, option_refs)

    def _overlay_feature(self, entry: ContentEntry) -> ContentEntry:
        extensions: list[ChoicePoolExtension] = []
        for spec in self._active_specs():
            extensions.extend(
                extension
                for extension in spec.pool_extensions
                if entry.index in extension.target_feature_indices
            )
        if not extensions:
            return entry
        data = deepcopy(entry.data)
        for extension in extensions:
            self._append_pool_options(data, extension.option_refs)
        return entry.model_copy(update={"data": data})

    def _overlay_spell(self, entry: ContentEntry) -> ContentEntry:
        class_refs: list[str] = []
        for spec in self._active_specs():
            expansion = spec.spell_access
            if expansion is not None and entry.key in expansion.spell_refs:
                class_refs.append(expansion.class_ref)
        if not class_refs:
            return entry

        data = deepcopy(entry.data)
        raw_classes = data.get("classes")
        classes = list(raw_classes) if isinstance(raw_classes, list) else []
        present = {
            key
            for raw in classes
            if (key := self._reference_key(raw)) is not None
        }
        for class_ref in class_refs:
            if class_ref in present:
                continue
            class_entry = self._base.get_optional(class_ref)
            if class_entry is None:
                continue
            classes.append({"key": class_entry.key, "name": class_entry.name})
            present.add(class_ref)
        data["classes"] = classes
        return entry.model_copy(update={"data": data})

    def _overlay(self, entry: ContentEntry) -> ContentEntry:
        if stable_key_is_kind(entry.key, "feature"):
            return self._overlay_feature(entry)
        if stable_key_is_kind(entry.key, "spell"):
            return self._overlay_spell(entry)
        return entry

    def get(self, key: str) -> ContentEntry:
        return self._overlay(self._base.get(key))

    def get_optional(self, key: str) -> ContentEntry | None:
        entry = self._base.get_optional(key)
        return None if entry is None else self._overlay(entry)

    def list_kind(
        self,
        kind: str,
        *,
        source: str | None = None,
    ) -> tuple[ContentEntry, ...]:
        return tuple(self._overlay(entry) for entry in self._base.list_kind(kind, source=source))

    def resolve(self, *parts: str) -> ContentEntry:
        return self._overlay(self._base.resolve(*parts))

    def resolve_reference(self, reference: dict[str, object], *, kinds: set[str] | None = None) -> ContentEntry:
        return self._overlay(self._base.resolve_reference(reference, kinds=kinds))

    def get_source_manifest(self, source: str):
        return self._base.get_source_manifest(source)

    def source_label(self, source: str) -> str:
        return self._base.source_label(source)

    @property
    def manifest(self):
        return self._base.manifest

    @property
    def pack_count(self) -> int:
        return self._base.pack_count

    def __len__(self) -> int:
        return len(self._base)


def _optional_specs(
    registry: ContentRegistry,
) -> tuple[dict[str, OptionalClassFeatureSpec], tuple[BuilderIssue, ...]]:
    specs: dict[str, OptionalClassFeatureSpec] = {}
    issues: list[BuilderIssue] = []
    for entry in registry.list_kind("feature", source="tce"):
        raw = entry.data.get("optional_class_feature")
        if raw is None:
            continue
        try:
            specs[entry.key] = OptionalClassFeatureSpec.model_validate(raw)
        except ValidationError as exc:
            issues.append(
                BuilderIssue(
                    code="invalid_optional_class_feature_data",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"content.{entry.key}.optional_class_feature",
                    message=f"Invalid Optional Class Feature metadata for {entry.key}: {exc}",
                    related_refs=(entry.key,),
                )
            )
    return specs, tuple(issues)


def _class_counts(draft: BuilderDraft) -> Counter[str]:
    return Counter(level.class_ref for level in draft.draft_payload.level_choices)


def _class_level_anchor(draft: BuilderDraft, class_ref: str, class_level: int) -> int | None:
    seen = 0
    for character_level, level in enumerate(draft.draft_payload.level_choices, start=1):
        if level.class_ref != class_ref:
            continue
        seen += 1
        if seen == class_level:
            return character_level
    return None


def _choice_id(anchor: int, feature_ref: str) -> str:
    return deterministic_choice_id("level", str(anchor), "tce-optional-feature", feature_ref)


def _selection(draft: BuilderDraft, choice_id: str) -> tuple[str, ...] | None:
    selection = draft.draft_payload.choice_selections.get(choice_id)
    return None if selection is None else selection.selected_option_ids


def _is_feature_active_from_choice(
    draft: BuilderDraft,
    feature_ref: str,
    spec: OptionalClassFeatureSpec,
    *,
    base_build: CharacterBuild | None,
) -> bool:
    anchor = _class_level_anchor(draft, spec.parent_class_ref, spec.minimum_class_level)
    if anchor is None:
        return False
    if spec.activation == "automatic":
        return True
    selected = _selection(draft, _choice_id(anchor, feature_ref))
    if selected is not None:
        return selected == (feature_ref,)
    return base_build is not None and feature_ref in base_build.feature_refs


def prepare_optional_class_features(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    base_build: CharacterBuild | None,
) -> OptionalFeatureRuntime:
    specs, data_issues = _optional_specs(registry)
    counts = _class_counts(draft)
    active: list[str] = []
    choices: list[BuilderChoice] = []
    issues: list[BuilderIssue] = list(data_issues)

    for feature_ref, spec in sorted(specs.items()):
        if counts[spec.parent_class_ref] < spec.minimum_class_level:
            continue
        if _is_feature_active_from_choice(
            draft,
            feature_ref,
            spec,
            base_build=base_build,
        ):
            active.append(feature_ref)
        if spec.activation == "automatic":
            continue

        anchor = _class_level_anchor(draft, spec.parent_class_ref, spec.minimum_class_level)
        if anchor is None:
            continue
        entry = registry.get_optional(feature_ref)
        if entry is None:
            continue
        choice_id = _choice_id(anchor, feature_ref)
        selected = _selection(draft, choice_id)
        if selected is None and base_build is not None and feature_ref in base_build.feature_refs:
            selected = (feature_ref,)
        selected = selected or ()
        choices.append(
            BuilderChoice(
                choice_id=choice_id,
                label=f"Optional Class Feature — {entry.name}",
                source_ref=feature_ref,
                required=False,
                choose_count=1,
                option_source="content:optional-class-feature",
                options=(
                    BuilderChoiceOption(
                        option_id=feature_ref,
                        label=entry.name,
                        kind=BuilderOptionKind.REFERENCE,
                        reference_id=feature_ref,
                        category="optional_class_feature",
                    ),
                ),
                selected_option_ids=selected,
            )
        )
        if len(selected) > 1 or (selected and selected != (feature_ref,)):
            issues.append(
                BuilderIssue(
                    code="invalid_optional_class_feature_selection",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"draft_payload.choice_selections.{choice_id}",
                    message=f"{entry.name} accepts only its own optional feature identity.",
                    related_refs=tuple(selected),
                )
            )

    active_tuple = tuple(dict.fromkeys(active))
    overlay = OptionalFeatureRegistry(registry, specs, active_tuple)
    issues.extend(_validate_active_extensions(overlay, specs, active_tuple))
    return OptionalFeatureRuntime(
        registry=overlay,
        choices=tuple(choices),
        active_feature_refs=active_tuple,
        specs=specs,
        issues=tuple(issues),
    )


def _walk_reference_options(value: object) -> tuple[str, ...]:
    refs: list[str] = []
    if isinstance(value, dict):
        if value.get("option_type") == "reference" and isinstance(value.get("item"), dict):
            try:
                key = reference_to_stable_key(value["item"])
            except ValueError:
                key = None
            if key is not None:
                refs.append(key)
        for child in value.values():
            refs.extend(_walk_reference_options(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_walk_reference_options(child))
    return tuple(dict.fromkeys(refs))


def _pool_option_refs(
    registry: OptionalFeatureRegistry,
    target_feature_indices: tuple[str, ...],
) -> tuple[str, ...]:
    refs: list[str] = []
    targets = set(target_feature_indices)
    for feature in registry.list_kind("feature"):
        if feature.index not in targets:
            continue
        refs.extend(_walk_reference_options(feature.data.get("feature_specific")))
    return tuple(dict.fromkeys(ref for ref in refs if stable_key_is_kind(ref, "feature")))


def _validate_active_extensions(
    registry: OptionalFeatureRegistry,
    specs: dict[str, OptionalClassFeatureSpec],
    active_refs: tuple[str, ...],
) -> tuple[BuilderIssue, ...]:
    issues: list[BuilderIssue] = []
    feature_indices = {entry.index for entry in registry.list_kind("feature")}
    for feature_ref in active_refs:
        spec = specs.get(feature_ref)
        if spec is None:
            continue
        for extension in spec.pool_extensions:
            if not any(index in feature_indices for index in extension.target_feature_indices):
                issues.append(
                    BuilderIssue(
                        code="optional_feature_pool_target_missing",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path=f"content.{feature_ref}.optional_class_feature.pool_extensions",
                        message=(
                            f"{feature_ref} cannot find any installed target choice pool: "
                            + ", ".join(extension.target_feature_indices)
                        ),
                        related_refs=(feature_ref,),
                    )
                )
    return tuple(issues)


def _spell_has_class(spell: ContentEntry, class_ref: str) -> bool:
    raw = spell.data.get("classes")
    if not isinstance(raw, list):
        return False
    for reference in raw:
        if not isinstance(reference, dict):
            continue
        try:
            key = reference_to_stable_key(reference, kinds={"class"})
        except ValueError:
            key = None
        if key == class_ref:
            return True
    return False


def _class_cantrip_refs(
    registry: OptionalFeatureRegistry,
    class_ref: str,
) -> tuple[str, ...]:
    result: list[str] = []
    for spell in registry.list_kind("spell"):
        if spell.data.get("level") == 0 and _spell_has_class(spell, class_ref):
            result.append(spell.key)
    return tuple(result)


def _choice_pool_option(entry: ContentEntry | None) -> ChoicePoolOptionSpec | None:
    if entry is None:
        return None
    raw = entry.data.get("choice_pool_option")
    if raw is None:
        return None
    try:
        return ChoicePoolOptionSpec.model_validate(raw)
    except ValidationError:
        return None


def build_optional_nested_choices(
    draft: BuilderDraft,
    registry: OptionalFeatureRegistry,
    parent_choices: tuple[BuilderChoice, ...],
) -> tuple[BuilderChoice, ...]:
    nested: list[BuilderChoice] = []
    for parent in parent_choices:
        selected = _selection(draft, parent.choice_id) or ()
        option_by_id = {option.option_id: option for option in parent.options}
        for selected_id in selected:
            option = option_by_id.get(selected_id)
            if option is None or option.reference_id is None:
                continue
            entry = registry.get_optional(option.reference_id)
            pool_option = _choice_pool_option(entry)
            if pool_option is None or pool_option.nested is None:
                continue
            nested_spec = pool_option.nested
            nested_id = deterministic_choice_id(parent.choice_id, option.reference_id, "nested")
            if nested_spec.kind == "cantrip" and nested_spec.class_ref is not None:
                refs = _class_cantrip_refs(registry, nested_spec.class_ref)
                category = "spell"
            elif nested_spec.kind == "feature_pool":
                refs = _pool_option_refs(registry, nested_spec.target_feature_indices)
                category = "feature"
            else:
                refs = ()
                category = "feature"
            options: list[BuilderChoiceOption] = []
            for ref in refs:
                target = registry.get_optional(ref)
                if target is None:
                    continue
                options.append(
                    BuilderChoiceOption(
                        option_id=ref,
                        label=target.name,
                        kind=BuilderOptionKind.REFERENCE,
                        reference_id=ref,
                        category=category,
                    )
                )
            nested.append(
                BuilderChoice(
                    choice_id=nested_id,
                    label=f"{entry.name} — choice" if entry is not None else "Optional feature choice",
                    source_ref=option.reference_id,
                    required=True,
                    choose_count=nested_spec.choose,
                    option_source=(
                        "content:feature:optional-nested"
                        if nested_spec.kind == "feature_pool"
                        else "content:optional-feature:cantrip"
                    ),
                    options=tuple(options),
                    selected_option_ids=_selection(draft, nested_id) or (),
                )
            )
    return tuple(nested)


def _retraining_is_available(
    draft: BuilderDraft,
    spec: OptionalClassFeatureSpec,
) -> bool:
    retraining = spec.retraining
    if retraining is None or draft.mode not in {BuilderMode.LEVEL_UP, BuilderMode.BUILD_EDIT}:
        return False
    counts = _class_counts(draft)
    class_level = counts[spec.parent_class_ref]
    if class_level < spec.minimum_class_level:
        return False
    if draft.mode is BuilderMode.LEVEL_UP:
        levels = draft.draft_payload.level_choices
        if not levels or levels[-1].class_ref != spec.parent_class_ref:
            return False
    return retraining.any_level_after_minimum or class_level in retraining.class_levels


def _base_cantrips(
    base_build: CharacterBuild | None,
    registry: OptionalFeatureRegistry,
    class_ref: str,
) -> tuple[str, ...]:
    if base_build is None:
        return ()
    result: list[str] = []
    for access in base_build.spell_access_entries:
        if access.source_type != "class" or access.source_key != class_ref:
            continue
        spell = registry.get_optional(access.spell_key)
        if spell is not None and spell.data.get("level") == 0:
            result.append(access.spell_key)
    return tuple(dict.fromkeys(result))


def build_optional_retraining_choices(
    draft: BuilderDraft,
    runtime: OptionalFeatureRuntime,
    *,
    base_build: CharacterBuild | None,
) -> tuple[BuilderChoice, ...]:
    result: list[BuilderChoice] = []
    registry = runtime.registry
    anchor = draft.draft_payload.target_level or 1

    for feature_ref in runtime.active_feature_refs:
        spec = runtime.specs.get(feature_ref)
        if spec is None or not _retraining_is_available(draft, spec) or spec.retraining is None:
            continue
        feature = registry.get_optional(feature_ref)
        if feature is None:
            continue
        parent_id = deterministic_choice_id("level", str(anchor), feature_ref, "retraining")
        parent_selected = _selection(draft, parent_id) or ()
        parent_options: list[BuilderChoiceOption] = [
            BuilderChoiceOption(
                option_id=f"{parent_id}:skip",
                label="Keep current choice",
                kind=BuilderOptionKind.BRANCH,
                branch_key="skip",
            )
        ]
        strategy_candidates: dict[str, tuple[str, ...]] = {}
        for strategy in spec.retraining.strategies:
            if strategy.kind == "feature_pool":
                candidates = _pool_option_refs(registry, strategy.target_feature_indices)
                current = tuple(
                    ref
                    for ref in (base_build.feature_refs if base_build is not None else ())
                    if ref in candidates
                )
            elif strategy.kind == "cantrip" and strategy.class_ref is not None:
                candidates = _class_cantrip_refs(registry, strategy.class_ref)
                current = _base_cantrips(base_build, registry, strategy.class_ref)
            else:
                candidates = ()
                current = ()
            if not candidates or not current:
                continue
            strategy_candidates[strategy.id] = candidates
            branch_id = f"{parent_id}:strategy:{strategy.id}"
            parent_options.append(
                BuilderChoiceOption(
                    option_id=branch_id,
                    label=strategy.label,
                    kind=BuilderOptionKind.BRANCH,
                    branch_key=strategy.id,
                )
            )
            active = parent_selected == (branch_id,)
            from_id = deterministic_choice_id(parent_id, strategy.id, "from")
            to_id = deterministic_choice_id(parent_id, strategy.id, "to")
            selected_from = _selection(draft, from_id) or ()
            from_ref = selected_from[0] if len(selected_from) == 1 else None
            from_options = tuple(
                BuilderChoiceOption(
                    option_id=ref,
                    label=(registry.get_optional(ref).name if registry.get_optional(ref) is not None else ref),
                    kind=BuilderOptionKind.REFERENCE,
                    reference_id=ref,
                    category="retraining_from",
                )
                for ref in current
            )
            to_options = tuple(
                BuilderChoiceOption(
                    option_id=ref,
                    label=(registry.get_optional(ref).name if registry.get_optional(ref) is not None else ref),
                    kind=BuilderOptionKind.REFERENCE,
                    reference_id=ref,
                    category="retraining_to",
                    disabled_reason=("Choose a different replacement." if ref == from_ref else None),
                    disabled_reason_code=("retraining_same_option" if ref == from_ref else None),
                )
                for ref in candidates
            )
            disabled_reason = None if active else "Choose this retraining branch first."
            disabled_code = None if active else "retraining_branch_required"
            result.extend(
                (
                    BuilderChoice(
                        choice_id=from_id,
                        label=f"{feature.name} — replace",
                        source_ref=feature_ref,
                        required=True,
                        choose_count=1,
                        option_source="content:optional-feature:retraining-from",
                        options=from_options,
                        selected_option_ids=selected_from,
                        disabled_reason=disabled_reason,
                        disabled_reason_code=disabled_code,
                    ),
                    BuilderChoice(
                        choice_id=to_id,
                        label=f"{feature.name} — with",
                        source_ref=feature_ref,
                        required=True,
                        choose_count=1,
                        option_source="content:optional-feature:retraining-to",
                        options=to_options,
                        selected_option_ids=_selection(draft, to_id) or (),
                        disabled_reason=disabled_reason,
                        disabled_reason_code=disabled_code,
                    ),
                )
            )
        if len(parent_options) > 1:
            result.insert(
                len(result) - 2 * len(strategy_candidates),
                BuilderChoice(
                    choice_id=parent_id,
                    label=f"{feature.name} — retraining",
                    source_ref=feature_ref,
                    required=True,
                    choose_count=1,
                    option_source="content:optional-feature:retraining",
                    options=tuple(parent_options),
                    selected_option_ids=parent_selected,
                ),
            )
    return tuple(result)


def validate_optional_choices(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
) -> tuple[BuilderIssue, ...]:
    issues: list[BuilderIssue] = []
    for choice in choices:
        if choice.disabled_reason is not None:
            continue
        selected = _selection(draft, choice.choice_id) or ()
        option_by_id = {option.option_id: option for option in choice.options}
        if choice.required and len(selected) != choice.choose_count:
            issues.append(
                BuilderIssue(
                    code="invalid_optional_feature_choice_count",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"draft_payload.choice_selections.{choice.choice_id}",
                    message=f"{choice.label} requires exactly {choice.choose_count} selection(s).",
                    related_refs=tuple(selected),
                )
            )
            continue
        if not choice.required and len(selected) > choice.choose_count:
            issues.append(
                BuilderIssue(
                    code="invalid_optional_feature_choice_count",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"draft_payload.choice_selections.{choice.choice_id}",
                    message=f"{choice.label} allows at most {choice.choose_count} selection(s).",
                    related_refs=tuple(selected),
                )
            )
            continue
        illegal = tuple(ref for ref in selected if ref not in option_by_id)
        disabled = tuple(
            ref
            for ref in selected
            if ref in option_by_id and option_by_id[ref].disabled_reason is not None
        )
        if illegal:
            issues.append(
                BuilderIssue(
                    code="invalid_optional_feature_option",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"draft_payload.choice_selections.{choice.choice_id}",
                    message=f"{choice.label} contains an option outside the server-authoritative pool.",
                    related_refs=illegal,
                )
            )
        if disabled:
            issues.append(
                BuilderIssue(
                    code="disabled_optional_feature_option",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"draft_payload.choice_selections.{choice.choice_id}",
                    message=f"{choice.label} contains an ineligible option.",
                    related_refs=disabled,
                )
            )
    return tuple(issues)


def apply_optional_feature_replacements(
    feature_refs: tuple[str, ...],
    runtime: OptionalFeatureRuntime,
) -> tuple[tuple[str, ...], tuple[BuilderIssue, ...]]:
    active_specs = [
        (feature_ref, runtime.specs[feature_ref])
        for feature_ref in runtime.active_feature_refs
        if feature_ref in runtime.specs and runtime.specs[feature_ref].mode == "replacement"
    ]
    if not active_specs:
        return tuple(dict.fromkeys(feature_refs)), ()

    result = list(feature_refs)
    issues: list[BuilderIssue] = []
    for feature_ref, spec in active_specs:
        removed: list[str] = []
        kept: list[str] = []
        exact = set(spec.replaces_feature_refs)
        for candidate in result:
            entry = runtime.registry.get_optional(candidate)
            index = entry.index if entry is not None else parse_stable_key(candidate).index
            matches = (
                candidate in exact
                or any(index.startswith(prefix) for prefix in spec.replaces_feature_index_prefixes)
                or any(token in index for token in spec.replaces_feature_index_contains)
            )
            if matches and candidate != feature_ref:
                removed.append(candidate)
            else:
                kept.append(candidate)
        if spec.replacement_target_required and not removed:
            issues.append(
                BuilderIssue(
                    code="optional_feature_replacement_target_missing",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"build.feature_refs.{feature_ref}",
                    message=f"{feature_ref} is selected but no declared base feature target is active.",
                    related_refs=(feature_ref,),
                )
            )
        result = kept
    result.extend(runtime.active_feature_refs)
    return tuple(dict.fromkeys(result)), tuple(issues)


def apply_feature_pool_retraining(
    feature_refs: tuple[str, ...],
    draft: BuilderDraft,
    runtime: OptionalFeatureRuntime,
    retraining_choices: tuple[BuilderChoice, ...],
) -> tuple[str, ...]:
    result = list(feature_refs)
    by_id = {choice.choice_id: choice for choice in retraining_choices}
    for feature_ref in runtime.active_feature_refs:
        spec = runtime.specs.get(feature_ref)
        if spec is None or spec.retraining is None or not _retraining_is_available(draft, spec):
            continue
        anchor = draft.draft_payload.target_level or 1
        parent_id = deterministic_choice_id("level", str(anchor), feature_ref, "retraining")
        parent_selected = _selection(draft, parent_id) or ()
        if len(parent_selected) != 1 or ":strategy:" not in parent_selected[0]:
            continue
        strategy_id = parent_selected[0].rsplit(":strategy:", 1)[-1]
        strategy = next((item for item in spec.retraining.strategies if item.id == strategy_id), None)
        if strategy is None or strategy.kind != "feature_pool":
            continue
        from_id = deterministic_choice_id(parent_id, strategy.id, "from")
        to_id = deterministic_choice_id(parent_id, strategy.id, "to")
        if from_id not in by_id or to_id not in by_id:
            continue
        selected_from = _selection(draft, from_id) or ()
        selected_to = _selection(draft, to_id) or ()
        if len(selected_from) != 1 or len(selected_to) != 1:
            continue
        old, new = selected_from[0], selected_to[0]
        if old == new:
            continue
        result = [ref for ref in result if ref != old]
        result.append(new)
    return tuple(dict.fromkeys(result))


def _spell_access_entry_id(source_ref: str, spell_ref: str) -> str:
    digest = sha1(f"{source_ref}|{spell_ref}".encode("utf-8")).hexdigest()[:16]
    return f"feature-spell:{digest}"


def compile_nested_spell_access(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
    registry: OptionalFeatureRegistry,
) -> tuple[SpellAccessEntry, ...]:
    result: list[SpellAccessEntry] = []
    for choice in choices:
        if choice.option_source != "content:optional-feature:cantrip" or choice.source_ref is None:
            continue
        style = registry.get_optional(choice.source_ref)
        pool_option = _choice_pool_option(style)
        nested = pool_option.nested if pool_option is not None else None
        if nested is None or nested.kind != "cantrip" or nested.casting_ability is None:
            continue
        option_by_id = {option.option_id: option for option in choice.options}
        selected = _selection(draft, choice.choice_id) or ()
        for option_id in selected:
            option = option_by_id.get(option_id)
            if option is None or option.reference_id is None:
                continue
            spell = registry.get_optional(option.reference_id)
            if spell is None or not stable_key_is_kind(spell.key, "spell") or spell.data.get("level") != 0:
                continue
            result.append(
                SpellAccessEntry(
                    entry_id=_spell_access_entry_id(choice.source_ref, spell.key),
                    spell_key=spell.key,
                    source_type="feature",
                    source_key=choice.source_ref,
                    access_type="known",
                    casting_ability=nested.casting_ability,
                )
            )
    return tuple(result)


def apply_cantrip_retraining(
    entries: tuple[SpellAccessEntry, ...],
    draft: BuilderDraft,
    runtime: OptionalFeatureRuntime,
    retraining_choices: tuple[BuilderChoice, ...],
) -> tuple[SpellAccessEntry, ...]:
    result = list(entries)
    by_id = {choice.choice_id: choice for choice in retraining_choices}
    for feature_ref in runtime.active_feature_refs:
        spec = runtime.specs.get(feature_ref)
        if spec is None or spec.retraining is None or not _retraining_is_available(draft, spec):
            continue
        anchor = draft.draft_payload.target_level or 1
        parent_id = deterministic_choice_id("level", str(anchor), feature_ref, "retraining")
        parent_selected = _selection(draft, parent_id) or ()
        if len(parent_selected) != 1 or ":strategy:" not in parent_selected[0]:
            continue
        strategy_id = parent_selected[0].rsplit(":strategy:", 1)[-1]
        strategy = next((item for item in spec.retraining.strategies if item.id == strategy_id), None)
        if strategy is None or strategy.kind != "cantrip" or strategy.class_ref is None:
            continue
        from_id = deterministic_choice_id(parent_id, strategy.id, "from")
        to_id = deterministic_choice_id(parent_id, strategy.id, "to")
        if from_id not in by_id or to_id not in by_id:
            continue
        selected_from = _selection(draft, from_id) or ()
        selected_to = _selection(draft, to_id) or ()
        if len(selected_from) != 1 or len(selected_to) != 1 or selected_from == selected_to:
            continue
        old, new = selected_from[0], selected_to[0]
        replaced = False
        next_entries: list[SpellAccessEntry] = []
        for entry in result:
            if (
                not replaced
                and entry.source_type == "class"
                and entry.source_key == strategy.class_ref
                and entry.spell_key == old
            ):
                next_entries.append(entry.model_copy(update={"spell_key": new}))
                replaced = True
            else:
                next_entries.append(entry)
        result = next_entries
    return tuple(result)
