from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.content.identity import parse_stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import CharacterBuild, SpellAccessEntry
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.progression import progression_summary
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderMode,
    BuilderOptionKind,
)
from app.domain.character_builder.structural import StructuralCompilation, compile_structural_selections


OptionalFeatureMode = Literal["addition", "expanded_choice", "replacement", "retraining"]
NestedChoiceKind = Literal["cantrip", "feature_pool"]
RetrainingKind = Literal["feature_pool", "cantrip"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChoicePoolExtension(StrictModel):
    target_feature_indices: tuple[str, ...] = ()
    option_refs: tuple[str, ...] = ()
    option_pool: str | None = None
    target_required: bool = True


class SpellAccessExpansion(StrictModel):
    class_ref: str
    spell_refs: tuple[str, ...] = ()
    spell_indices: tuple[str, ...] = ()


class RetrainingStrategy(StrictModel):
    id: str
    label: str
    kind: RetrainingKind
    class_ref: str | None = None
    target_feature_indices: tuple[str, ...] = ()
    pool: str | None = None


class RetrainingSpec(StrictModel):
    class_levels: tuple[int, ...] = ()
    any_level_after_minimum: bool = False
    strategies: tuple[RetrainingStrategy, ...] = ()


class OptionalClassFeatureSpec(StrictModel):
    parent_class_ref: str
    minimum_class_level: int = Field(ge=1, le=20)
    mode: OptionalFeatureMode
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
    pool: str | None = None


class ChoicePoolOptionSpec(StrictModel):
    pool: str
    eligible_class_refs: tuple[str, ...] = ()
    minimum_class_level: int = Field(default=1, ge=1, le=20)
    required_feature_refs: tuple[str, ...] = ()
    any_required_feature_refs: tuple[str, ...] = ()
    nested: NestedChoiceSpec | None = None


@dataclass(frozen=True)
class OptionalFeatureRuntime:
    registry: "OptionalFeatureRegistry"
    choices: tuple[BuilderChoice, ...]
    active_feature_refs: tuple[str, ...]
    specs: dict[str, OptionalClassFeatureSpec]
    issues: tuple[BuilderIssue, ...]


def _selection(draft: BuilderDraft, choice_id: str) -> tuple[str, ...]:
    record = draft.draft_payload.choice_selections.get(choice_id)
    return record.selected_option_ids if record is not None else ()


def _entry_label(entry: ContentEntry) -> str:
    return f"{entry.name} · {entry.source_label or entry.source}"


def _class_counts(draft: BuilderDraft) -> Counter[str]:
    return Counter(level.class_ref for level in draft.draft_payload.level_choices)


def _target_character_level(draft: BuilderDraft) -> int:
    if draft.draft_payload.target_level is not None:
        return draft.draft_payload.target_level
    return max(1, len(draft.draft_payload.level_choices))


def _choice_prefix(draft: BuilderDraft) -> tuple[str, ...]:
    if draft.mode is BuilderMode.LEVEL_UP:
        return ("level", str(_target_character_level(draft)), "m01-i")
    return ("m01-i",)


def _choice_id(draft: BuilderDraft, *parts: str) -> str:
    return deterministic_choice_id(*_choice_prefix(draft), *parts)


def _feature_index(feature_ref: str) -> str | None:
    try:
        return parse_stable_key(feature_ref, kinds={"feature"}).index
    except ValueError:
        return None


def _optional_specs(registry: ContentRegistry) -> dict[str, OptionalClassFeatureSpec]:
    specs: dict[str, OptionalClassFeatureSpec] = {}
    for entry in registry.list_kind("feature", source="tce"):
        raw = entry.data.get("optional_class_feature")
        if not isinstance(raw, dict):
            continue
        specs[entry.key] = OptionalClassFeatureSpec.model_validate(raw)
    return specs


def _pool_option_spec(entry: ContentEntry) -> ChoicePoolOptionSpec | None:
    raw = entry.data.get("choice_pool_option")
    if not isinstance(raw, dict):
        return None
    return ChoicePoolOptionSpec.model_validate(raw)


def _pool_refs(registry: ContentRegistry, pool: str) -> tuple[str, ...]:
    refs = [
        entry.key
        for entry in registry.list_kind("feature")
        if (spec := _pool_option_spec(entry)) is not None and spec.pool == pool
    ]
    return tuple(sorted(dict.fromkeys(refs)))


def _extension_option_refs(
    registry: ContentRegistry,
    extension: ChoicePoolExtension,
) -> tuple[str, ...]:
    refs = list(extension.option_refs)
    if extension.option_pool is not None:
        refs.extend(_pool_refs(registry, extension.option_pool))
    return tuple(dict.fromkeys(refs))


def _append_reference_options(
    value: object,
    *,
    option_refs: tuple[str, ...],
    registry: ContentRegistry,
) -> object:
    if isinstance(value, dict):
        result = {key: deepcopy(child) for key, child in value.items()}
        source = result.get("from")
        if isinstance(result.get("choose"), int) and isinstance(source, dict):
            if source.get("option_set_type") == "options_array":
                raw_options = source.get("options")
                if isinstance(raw_options, list):
                    known: set[str] = set()
                    for raw in raw_options:
                        if not isinstance(raw, dict):
                            continue
                        item = raw.get("item")
                        if not isinstance(item, dict):
                            continue
                        key = item.get("key")
                        if isinstance(key, str):
                            known.add(key)
                    next_options = list(raw_options)
                    for ref in option_refs:
                        if ref in known:
                            continue
                        target = registry.get_optional(ref)
                        if target is None or not stable_key_is_kind(target.key, "feature"):
                            continue
                        next_options.append(
                            {
                                "option_type": "reference",
                                "item": {
                                    "key": target.key,
                                    "index": target.index,
                                    "name": target.name,
                                },
                            }
                        )
                        known.add(ref)
                    source = dict(source)
                    source["options"] = next_options
                    result["from"] = source
        for key, child in tuple(result.items()):
            if key == "from":
                continue
            result[key] = _append_reference_options(
                child,
                option_refs=option_refs,
                registry=registry,
            )
        return result
    if isinstance(value, list):
        return [
            _append_reference_options(child, option_refs=option_refs, registry=registry)
            for child in value
        ]
    return deepcopy(value)


class OptionalFeatureRegistry:
    """Read-only registry overlay for M01-I expanded pools and spell lists."""

    def __init__(
        self,
        base: ContentRegistry,
        active_specs: tuple[tuple[str, OptionalClassFeatureSpec], ...],
    ) -> None:
        self.base = base
        self.active_specs = active_specs
        self.enabled_pack_ids = base.enabled_pack_ids

    @property
    def manifest(self):
        return self.base.manifest

    @property
    def pack_count(self) -> int:
        return self.base.pack_count

    def get_source_manifest(self, source: str):
        return self.base.get_source_manifest(source)

    def _overlay_feature(self, entry: ContentEntry) -> ContentEntry:
        extensions: list[ChoicePoolExtension] = []
        for _feature_ref, spec in self.active_specs:
            for extension in spec.pool_extensions:
                if entry.index in extension.target_feature_indices:
                    extensions.append(extension)
        if not extensions:
            return entry

        root = entry.data.get("feature_specific")
        if not isinstance(root, dict):
            return entry
        next_root: object = deepcopy(root)
        for extension in extensions:
            refs = _extension_option_refs(self.base, extension)
            next_root = _append_reference_options(
                next_root,
                option_refs=refs,
                registry=self.base,
            )
        data = dict(entry.data)
        data["feature_specific"] = next_root
        return entry.model_copy(update={"data": data})

    def _overlay_spell(self, entry: ContentEntry) -> ContentEntry:
        matching: list[tuple[str, SpellAccessExpansion]] = []
        for feature_ref, spec in self.active_specs:
            expansion = spec.spell_access
            if expansion is None:
                continue
            if entry.key in expansion.spell_refs or entry.index in expansion.spell_indices:
                matching.append((feature_ref, expansion))
        if not matching:
            return entry

        classes = entry.data.get("classes")
        next_classes = list(classes) if isinstance(classes, list) else []
        known: set[str] = set()
        for reference in next_classes:
            if not isinstance(reference, dict):
                continue
            key = reference.get("key")
            if isinstance(key, str):
                known.add(key)

        expansion_sources: list[str] = []
        for feature_ref, expansion in matching:
            expansion_sources.append(feature_ref)
            if expansion.class_ref in known:
                continue
            class_entry = self.base.get_optional(expansion.class_ref)
            if class_entry is None:
                continue
            next_classes.append(
                {
                    "key": class_entry.key,
                    "index": class_entry.index,
                    "name": class_entry.name,
                }
            )
            known.add(class_entry.key)

        data = dict(entry.data)
        data["classes"] = next_classes
        data["m01_i_spell_access_sources"] = tuple(dict.fromkeys(expansion_sources))
        return entry.model_copy(update={"data": data})

    def _overlay(self, entry: ContentEntry) -> ContentEntry:
        if stable_key_is_kind(entry.key, "feature"):
            return self._overlay_feature(entry)
        if stable_key_is_kind(entry.key, "spell"):
            return self._overlay_spell(entry)
        return entry

    def get(self, key: str) -> ContentEntry:
        return self._overlay(self.base.get(key))

    def get_optional(self, key: str) -> ContentEntry | None:
        entry = self.base.get_optional(key)
        return None if entry is None else self._overlay(entry)

    def list_kind(self, kind: str, *, source: str | None = None) -> tuple[ContentEntry, ...]:
        return tuple(self._overlay(entry) for entry in self.base.list_kind(kind, source=source))

    def resolve(self, kind: str, index: str, *, source: str | None = None) -> ContentEntry:
        return self._overlay(self.base.resolve(kind, index, source=source))

    def __getattr__(self, name: str):
        return getattr(self.base, name)


def _feature_is_active(
    draft: BuilderDraft,
    feature_ref: str,
    *,
    choice_id: str,
    base_build: CharacterBuild | None,
) -> bool:
    selection = draft.draft_payload.choice_selections.get(choice_id)
    if selection is not None:
        return selection.selected_option_ids == (feature_ref,)
    return base_build is not None and feature_ref in base_build.feature_refs


def _level_up_new_class_level(draft: BuilderDraft, class_ref: str) -> int | None:
    if draft.mode is not BuilderMode.LEVEL_UP or not draft.draft_payload.level_choices:
        return None
    newest = draft.draft_payload.level_choices[-1]
    if newest.class_ref != class_ref:
        return None
    return sum(1 for level in draft.draft_payload.level_choices if level.class_ref == class_ref)


def _validate_active_extensions(
    registry: ContentRegistry,
    active_specs: tuple[tuple[str, OptionalClassFeatureSpec], ...],
) -> tuple[BuilderIssue, ...]:
    issues: list[BuilderIssue] = []
    feature_indices = {entry.index for entry in registry.list_kind("feature")}
    for feature_ref, spec in active_specs:
        for extension in spec.pool_extensions:
            missing_options = [
                ref
                for ref in _extension_option_refs(registry, extension)
                if registry.get_optional(ref) is None
            ]
            if missing_options:
                issues.append(
                    BuilderIssue(
                        code="optional_feature_pool_option_missing",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path="content",
                        message=f"{feature_ref} references missing expanded pool options.",
                        related_refs=tuple(missing_options),
                    )
                )
            if extension.target_required and extension.target_feature_indices:
                if not any(index in feature_indices for index in extension.target_feature_indices):
                    issues.append(
                        BuilderIssue(
                            code="optional_feature_pool_target_missing",
                            severity=BuilderIssueSeverity.BLOCKING_ERROR,
                            path="content",
                            message=f"{feature_ref} cannot find its target feature pool.",
                            related_refs=(feature_ref,),
                        )
                    )
        expansion = spec.spell_access
        if expansion is not None and registry.get_optional(expansion.class_ref) is None:
            issues.append(
                BuilderIssue(
                    code="optional_feature_spell_class_missing",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="content",
                    message=f"{feature_ref} references an unavailable spellcasting class.",
                    related_refs=(feature_ref, expansion.class_ref),
                )
            )
    return tuple(issues)


def prepare_optional_class_features(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    base_build: CharacterBuild | None = None,
) -> OptionalFeatureRuntime:
    specs = _optional_specs(registry)
    class_counts = _class_counts(draft)
    choices: list[BuilderChoice] = []
    active: list[tuple[str, OptionalClassFeatureSpec]] = []

    for feature_ref in sorted(specs):
        spec = specs[feature_ref]
        class_level = class_counts.get(spec.parent_class_ref, 0)
        if class_level < spec.minimum_class_level:
            continue
        feature = registry.get_optional(feature_ref)
        if feature is None:
            continue

        base_active = base_build is not None and feature_ref in base_build.feature_refs
        new_level = _level_up_new_class_level(draft, spec.parent_class_ref)
        if draft.mode is BuilderMode.LEVEL_UP and base_active:
            active.append((feature_ref, spec))
            continue
        if (
            draft.mode is BuilderMode.LEVEL_UP
            and new_level != spec.minimum_class_level
        ):
            continue

        choice_id = _choice_id(draft, "optional-feature", feature_ref)
        selected = _selection(draft, choice_id)
        disabled_reason = None
        choices.append(
            BuilderChoice(
                choice_id=choice_id,
                label=f"{feature.name} — Optional Class Feature",
                source_ref=feature_ref,
                required=False,
                choose_count=1,
                option_source="content:optional-class-feature",
                options=(
                    BuilderChoiceOption(
                        option_id=feature_ref,
                        label=_entry_label(feature),
                        kind=BuilderOptionKind.REFERENCE,
                        reference_id=feature_ref,
                        category="optional_class_feature",
                    ),
                ),
                selected_option_ids=selected,
                disabled_reason=disabled_reason,
                disabled_reason_code=(
                    "optional_feature_base_build_locked" if disabled_reason else None
                ),
            )
        )
        if _feature_is_active(
            draft,
            feature_ref,
            choice_id=choice_id,
            base_build=base_build,
        ):
            active.append((feature_ref, spec))

    active_tuple = tuple(active)
    issues = _validate_active_extensions(registry, active_tuple)
    return OptionalFeatureRuntime(
        registry=OptionalFeatureRegistry(registry, active_tuple),
        choices=tuple(choices),
        active_feature_refs=tuple(feature_ref for feature_ref, _spec in active_tuple),
        specs=specs,
        issues=issues,
    )


def _option_failure(
    draft: BuilderDraft,
    option_entry: ContentEntry,
    option_spec: ChoicePoolOptionSpec,
    *,
    base_build: CharacterBuild | None,
    automatic_feature_refs: set[str],
) -> tuple[str, str, dict[str, object]] | None:
    counts = _class_counts(draft)
    if option_spec.eligible_class_refs:
        eligible_levels = [
            counts.get(class_ref, 0) for class_ref in option_spec.eligible_class_refs
        ]
        if not eligible_levels or max(eligible_levels) < option_spec.minimum_class_level:
            return (
                "This option is not available to the current class progression.",
                "optional_pool_class_prerequisite_not_met",
                {"option_ref": option_entry.key},
            )

    known = set(base_build.feature_refs if base_build is not None else ())
    known.update(automatic_feature_refs)
    for selection in draft.draft_payload.choice_selections.values():
        for option_id in selection.selected_option_ids:
            try:
                if stable_key_is_kind(option_id, "feature"):
                    known.add(option_id)
            except ValueError:
                pass

    missing = [ref for ref in option_spec.required_feature_refs if ref not in known]
    if missing:
        return (
            "This option requires another class feature.",
            "optional_pool_feature_prerequisite_not_met",
            {"option_ref": option_entry.key, "required_feature_refs": missing},
        )
    if option_spec.any_required_feature_refs and not any(
        ref in known for ref in option_spec.any_required_feature_refs
    ):
        return (
            "This option requires another class feature.",
            "optional_pool_feature_prerequisite_not_met",
            {
                "option_ref": option_entry.key,
                "any_required_feature_refs": list(option_spec.any_required_feature_refs),
            },
        )
    return None


def apply_optional_pool_eligibility(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
    *,
    base_build: CharacterBuild | None = None,
) -> tuple[BuilderChoice, ...]:
    automatic = {
        ref
        for node in progression_summary(draft, registry)
        for ref in node.automatic_feature_refs
    }
    result: list[BuilderChoice] = []
    for choice in choices:
        options: list[BuilderChoiceOption] = []
        for option in choice.options:
            if option.reference_id is None:
                options.append(option)
                continue
            entry = registry.get_optional(option.reference_id)
            if entry is None:
                options.append(option)
                continue
            spec = _pool_option_spec(entry)
            if spec is None:
                options.append(option)
                continue
            failure = _option_failure(
                draft,
                entry,
                spec,
                base_build=base_build,
                automatic_feature_refs=automatic,
            )
            if failure is None:
                options.append(option)
                continue
            reason, code, params = failure
            options.append(
                option.model_copy(
                    update={
                        "disabled_reason": reason,
                        "disabled_reason_code": code,
                        "disabled_reason_params": params,
                    }
                )
            )
        result.append(choice.model_copy(update={"options": tuple(options)}))
    return tuple(result)


def _class_cantrip_options(
    registry: ContentRegistry,
    class_ref: str,
) -> tuple[BuilderChoiceOption, ...]:
    result: list[BuilderChoiceOption] = []
    for spell in registry.list_kind("spell"):
        if spell.data.get("level") != 0:
            continue
        classes = spell.data.get("classes")
        if not isinstance(classes, list):
            continue
        present = False
        for reference in classes:
            if not isinstance(reference, dict):
                continue
            if reference.get("key") == class_ref:
                present = True
                break
            try:
                if reference.get("key") is None:
                    index = parse_stable_key(class_ref, kinds={"class"}).index
                    if reference.get("index") == index:
                        present = True
                        break
            except ValueError:
                continue
        if present:
            result.append(
                BuilderChoiceOption(
                    option_id=spell.key,
                    label=_entry_label(spell),
                    kind=BuilderOptionKind.REFERENCE,
                    reference_id=spell.key,
                    category="spell",
                )
            )
    return tuple(sorted(result, key=lambda option: option.option_id))


def _feature_pool_options(
    registry: ContentRegistry,
    *,
    pool: str | None,
    target_feature_indices: tuple[str, ...],
) -> tuple[BuilderChoiceOption, ...]:
    refs: list[str] = []
    if pool is not None:
        refs.extend(_pool_refs(registry, pool))

    if target_feature_indices:
        for feature in registry.list_kind("feature"):
            if feature.index not in target_feature_indices:
                continue
            root = feature.data.get("feature_specific")
            if not isinstance(root, dict):
                continue

            def walk(value: object) -> None:
                if isinstance(value, dict):
                    source = value.get("from")
                    if isinstance(source, dict):
                        options = source.get("options")
                        if isinstance(options, list):
                            for raw in options:
                                if not isinstance(raw, dict):
                                    continue
                                item = raw.get("item")
                                if isinstance(item, dict):
                                    key = item.get("key")
                                    if isinstance(key, str):
                                        refs.append(key)
                    for child in value.values():
                        walk(child)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)

            walk(root)

    result: list[BuilderChoiceOption] = []
    for ref in dict.fromkeys(refs):
        entry = registry.get_optional(ref)
        if entry is None or not stable_key_is_kind(entry.key, "feature"):
            continue
        result.append(
            BuilderChoiceOption(
                option_id=entry.key,
                label=_entry_label(entry),
                kind=BuilderOptionKind.REFERENCE,
                reference_id=entry.key,
                category=pool or "feature_pool",
            )
        )
    return tuple(sorted(result, key=lambda option: option.option_id))


def build_optional_nested_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    parent_choices: tuple[BuilderChoice, ...],
    *,
    base_build: CharacterBuild | None = None,
) -> tuple[BuilderChoice, ...]:
    result: list[BuilderChoice] = []
    for parent in parent_choices:
        selected = _selection(draft, parent.choice_id)
        if not selected:
            continue
        option_map = {option.option_id: option for option in parent.options}
        for option_id in selected:
            parent_option = option_map.get(option_id)
            if (
                parent_option is None
                or parent_option.disabled_reason is not None
                or parent_option.reference_id is None
            ):
                continue
            entry = registry.get_optional(parent_option.reference_id)
            if entry is None:
                continue
            option_spec = _pool_option_spec(entry)
            if option_spec is None or option_spec.nested is None:
                continue
            nested = option_spec.nested
            if nested.kind == "cantrip":
                if nested.class_ref is None:
                    continue
                options = _class_cantrip_options(registry, nested.class_ref)
                option_source = "content:optional-feature:cantrip"
            else:
                options = _feature_pool_options(
                    registry,
                    pool=nested.pool,
                    target_feature_indices=nested.target_feature_indices,
                )
                option_source = "content:feature:optional-nested"

            choice_id = deterministic_choice_id(parent.choice_id, option_id, "nested")
            child = BuilderChoice(
                choice_id=choice_id,
                label=f"{entry.name} — Choice",
                source_ref=entry.key,
                required=True,
                choose_count=nested.choose,
                option_source=option_source,
                options=options,
                selected_option_ids=_selection(draft, choice_id),
            )
            result.append(
                apply_optional_pool_eligibility(
                    draft,
                    registry,
                    (child,),
                    base_build=base_build,
                )[0]
            )
    return tuple(result)


def _retraining_available(
    draft: BuilderDraft,
    spec: OptionalClassFeatureSpec,
) -> bool:
    retraining = spec.retraining
    if retraining is None or draft.mode not in {BuilderMode.LEVEL_UP, BuilderMode.BUILD_EDIT}:
        return False
    class_level = _class_counts(draft).get(spec.parent_class_ref, 0)
    if class_level < spec.minimum_class_level:
        return False
    if draft.mode is BuilderMode.LEVEL_UP:
        new_level = _level_up_new_class_level(draft, spec.parent_class_ref)
        if new_level is None:
            return False
        if retraining.class_levels and new_level not in retraining.class_levels:
            return False
        if retraining.any_level_after_minimum and new_level < spec.minimum_class_level:
            return False
        return bool(retraining.class_levels or retraining.any_level_after_minimum)
    return True


def _base_cantrips(
    base_build: CharacterBuild,
    class_ref: str,
    registry: ContentRegistry,
) -> tuple[str, ...]:
    result: list[str] = []
    for entry in base_build.spell_access_entries:
        if (
            entry.source_type != "class"
            or entry.source_key != class_ref
            or entry.access_type != "known"
        ):
            continue
        spell = registry.get_optional(entry.spell_key)
        if spell is not None and spell.data.get("level") == 0:
            result.append(entry.spell_key)
    return tuple(dict.fromkeys(result))


def build_optional_retraining_choices(
    draft: BuilderDraft,
    runtime: OptionalFeatureRuntime,
    *,
    base_build: CharacterBuild | None,
) -> tuple[BuilderChoice, ...]:
    if base_build is None:
        return ()
    result: list[BuilderChoice] = []

    for feature_ref in sorted(runtime.specs):
        spec = runtime.specs[feature_ref]
        if not _retraining_available(draft, spec) or spec.retraining is None:
            continue
        feature = runtime.registry.get_optional(feature_ref)
        if feature is None:
            continue

        for strategy in spec.retraining.strategies:
            if strategy.kind == "cantrip":
                class_ref = strategy.class_ref or spec.parent_class_ref
                current = _base_cantrips(base_build, class_ref, runtime.registry)
                candidates = tuple(
                    option.reference_id
                    for option in _class_cantrip_options(runtime.registry, class_ref)
                    if option.reference_id is not None
                )
            else:
                current = tuple(
                    ref
                    for ref in base_build.feature_refs
                    if ref in {
                        option.reference_id
                        for option in _feature_pool_options(
                            runtime.registry,
                            pool=strategy.pool,
                            target_feature_indices=strategy.target_feature_indices,
                        )
                        if option.reference_id is not None
                    }
                )
                candidates = tuple(
                    option.reference_id
                    for option in _feature_pool_options(
                        runtime.registry,
                        pool=strategy.pool,
                        target_feature_indices=strategy.target_feature_indices,
                    )
                    if option.reference_id is not None
                )

            if not current or not candidates:
                continue

            parent_id = _choice_id(
                draft,
                "retraining",
                feature_ref,
                strategy.id,
                "action",
            )
            replace_id = deterministic_choice_id(parent_id, "replace")
            result.append(
                BuilderChoice(
                    choice_id=parent_id,
                    label=f"{feature.name} — {strategy.label}",
                    source_ref=feature_ref,
                    required=False,
                    choose_count=1,
                    option_source="content:optional-feature:retraining-action",
                    options=(
                        BuilderChoiceOption(
                            option_id=replace_id,
                            label="Replace one choice",
                            kind=BuilderOptionKind.BRANCH,
                            branch_key="replace",
                        ),
                    ),
                    selected_option_ids=_selection(draft, parent_id),
                )
            )

            active = _selection(draft, parent_id) == (replace_id,)
            old_id = deterministic_choice_id(parent_id, "from")
            old_options = tuple(
                BuilderChoiceOption(
                    option_id=ref,
                    label=_entry_label(runtime.registry.get(ref)),
                    kind=BuilderOptionKind.REFERENCE,
                    reference_id=ref,
                )
                for ref in current
                if runtime.registry.get_optional(ref) is not None
            )
            result.append(
                BuilderChoice(
                    choice_id=old_id,
                    label=f"{feature.name} — Replace",
                    source_ref=feature_ref,
                    required=True,
                    choose_count=1,
                    option_source=f"content:optional-feature:retraining-from:{strategy.kind}",
                    options=old_options,
                    selected_option_ids=_selection(draft, old_id),
                    disabled_reason=None if active else "Choose Replace one choice first.",
                    disabled_reason_code=None if active else "retraining_action_required",
                )
            )

            selected_old = _selection(draft, old_id)
            new_id = deterministic_choice_id(parent_id, "to")
            next_options: list[BuilderChoiceOption] = []
            for ref in candidates:
                entry = runtime.registry.get_optional(ref)
                if entry is None:
                    continue
                next_options.append(
                    BuilderChoiceOption(
                        option_id=ref,
                        label=_entry_label(entry),
                        kind=BuilderOptionKind.REFERENCE,
                        reference_id=ref,
                        disabled_reason=(
                            "Choose a different option."
                            if selected_old == (ref,)
                            else None
                        ),
                        disabled_reason_code=(
                            "retraining_same_option" if selected_old == (ref,) else None
                        ),
                    )
                )
            result.append(
                BuilderChoice(
                    choice_id=new_id,
                    label=f"{feature.name} — New choice",
                    source_ref=feature_ref,
                    required=True,
                    choose_count=1,
                    option_source=f"content:optional-feature:retraining-to:{strategy.kind}",
                    options=tuple(next_options),
                    selected_option_ids=_selection(draft, new_id),
                    disabled_reason=None if active else "Choose Replace one choice first.",
                    disabled_reason_code=None if active else "retraining_action_required",
                )
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
        selected = _selection(draft, choice.choice_id)
        # Synthetic default selections (for example "keep current") are display
        # defaults only; absence remains legal when the choice is not required.
        if choice.required and len(selected) != choice.choose_count:
            issues.append(
                BuilderIssue(
                    code="invalid_optional_choice_count",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"draft_payload.choice_selections.{choice.choice_id}",
                    message=(
                        f"{choice.label} requires exactly {choice.choose_count} "
                        f"selection(s); got {len(selected)}."
                    ),
                    message_params={"choice_id": choice.choice_id},
                )
            )
        if len(selected) > choice.choose_count:
            issues.append(
                BuilderIssue(
                    code="optional_choice_limit_exceeded",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path=f"draft_payload.choice_selections.{choice.choice_id}",
                    message=f"{choice.label} allows at most {choice.choose_count} selection(s).",
                    related_refs=tuple(selected),
                )
            )
        option_map = {option.option_id: option for option in choice.options}
        for option_id in selected:
            option = option_map.get(option_id)
            if option is None:
                issues.append(
                    BuilderIssue(
                        code="invalid_optional_choice_option",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path=f"draft_payload.choice_selections.{choice.choice_id}",
                        message=f"{choice.label} contains an option that is no longer legal.",
                        related_refs=(option_id,),
                    )
                )
            elif option.disabled_reason is not None:
                issues.append(
                    BuilderIssue(
                        code="disabled_optional_choice_option",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path=f"draft_payload.choice_selections.{choice.choice_id}",
                        message=f"{choice.label} contains an ineligible option.",
                        related_refs=(option_id,),
                    )
                )
    return tuple(issues)


def _matches_replacement(
    feature_ref: str,
    spec: OptionalClassFeatureSpec,
) -> bool:
    if feature_ref in spec.replaces_feature_refs:
        return True
    index = _feature_index(feature_ref)
    if index is None:
        return False
    if any(index.startswith(prefix) for prefix in spec.replaces_feature_index_prefixes):
        return True
    return any(token in index for token in spec.replaces_feature_index_contains)


def apply_optional_feature_replacements(
    feature_refs: tuple[str, ...],
    runtime: OptionalFeatureRuntime,
) -> tuple[tuple[str, ...], tuple[BuilderIssue, ...]]:
    refs = list(dict.fromkeys(feature_refs))
    issues: list[BuilderIssue] = []

    for feature_ref in runtime.active_feature_refs:
        spec = runtime.specs[feature_ref]
        if spec.mode != "replacement":
            continue
        targets = [ref for ref in refs if _matches_replacement(ref, spec)]
        if not targets and spec.replacement_target_required:
            issues.append(
                BuilderIssue(
                    code="optional_feature_replacement_target_missing",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="build.feature_refs",
                    message=f"{feature_ref} could not find the base feature it replaces.",
                    related_refs=(feature_ref,),
                )
            )
        target_set = set(targets)
        refs = [ref for ref in refs if ref not in target_set]

    refs.extend(runtime.active_feature_refs)
    return tuple(dict.fromkeys(refs)), tuple(issues)


def suppress_replaced_choices(
    choices: tuple[BuilderChoice, ...],
    runtime: OptionalFeatureRuntime,
) -> tuple[BuilderChoice, ...]:
    replacement_specs = [
        runtime.specs[ref]
        for ref in runtime.active_feature_refs
        if runtime.specs[ref].mode == "replacement"
    ]
    if not replacement_specs:
        return choices
    result: list[BuilderChoice] = []
    for choice in choices:
        source_ref = choice.source_ref
        if source_ref is not None and any(
            _matches_replacement(source_ref, spec) for spec in replacement_specs
        ):
            continue
        result.append(choice)
    return tuple(result)


def compile_nested_feature_selections(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
) -> StructuralCompilation:
    feature_choices = tuple(
        choice
        for choice in choices
        if (choice.option_source or "").startswith("content:feature:")
    )
    return compile_structural_selections(draft, registry, feature_choices)


def compile_nested_spell_access(
    draft: BuilderDraft,
    registry: ContentRegistry,
    choices: tuple[BuilderChoice, ...],
) -> tuple[SpellAccessEntry, ...]:
    result: list[SpellAccessEntry] = []
    for choice in choices:
        if choice.option_source != "content:optional-feature:cantrip":
            continue
        source_ref = choice.source_ref
        if source_ref is None:
            continue
        source = registry.get_optional(source_ref)
        if source is None:
            continue
        spec = _pool_option_spec(source)
        nested = spec.nested if spec is not None else None
        if nested is None or nested.kind != "cantrip" or nested.casting_ability is None:
            continue
        for spell_key in _selection(draft, choice.choice_id):
            spell = registry.get_optional(spell_key)
            if spell is None or not stable_key_is_kind(spell.key, "spell"):
                continue
            result.append(
                SpellAccessEntry(
                    entry_id=f"feature:{parse_stable_key(source_ref).index}:known:{parse_stable_key(spell_key).index}",
                    spell_key=spell_key,
                    source_type="feature",
                    source_key=source_ref,
                    access_type="known",
                    casting_ability=nested.casting_ability,
                )
            )
    return tuple(result)


def _strategy_replacements(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
    kind: RetrainingKind,
) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    by_id = {choice.choice_id: choice for choice in choices}
    for action in choices:
        if action.option_source != "content:optional-feature:retraining-action":
            continue
        replace_id = deterministic_choice_id(action.choice_id, "replace")
        if _selection(draft, action.choice_id) != (replace_id,):
            continue
        old_id = deterministic_choice_id(action.choice_id, "from")
        new_id = deterministic_choice_id(action.choice_id, "to")
        old_choice = by_id.get(old_id)
        new_choice = by_id.get(new_id)
        if (
            old_choice is None
            or new_choice is None
            or old_choice.option_source != f"content:optional-feature:retraining-from:{kind}"
            or new_choice.option_source != f"content:optional-feature:retraining-to:{kind}"
        ):
            continue
        old = _selection(draft, old_id)
        new = _selection(draft, new_id)
        if len(old) == 1 and len(new) == 1 and old[0] != new[0]:
            result.append((old[0], new[0]))
    return tuple(result)


def apply_feature_pool_retraining(
    feature_refs: tuple[str, ...],
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
) -> tuple[str, ...]:
    refs = list(dict.fromkeys(feature_refs))
    for old, new in _strategy_replacements(draft, choices, "feature_pool"):
        refs = [new if ref == old else ref for ref in refs]
    return tuple(dict.fromkeys(refs))


def apply_cantrip_retraining(
    entries: tuple[SpellAccessEntry, ...],
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
    registry: ContentRegistry,
) -> tuple[SpellAccessEntry, ...]:
    result = list(entries)
    for old, new in _strategy_replacements(draft, choices, "cantrip"):
        replaced = False
        for index, entry in enumerate(result):
            if entry.spell_key != old or entry.access_type != "known":
                continue
            if entry.source_type != "class":
                continue
            new_spell = registry.get_optional(new)
            if new_spell is None or not stable_key_is_kind(new_spell.key, "spell"):
                continue
            result[index] = entry.model_copy(
                update={
                    "entry_id": (
                        f"class:{parse_stable_key(entry.source_key).index}:known:"
                        f"{parse_stable_key(new).index}"
                    ),
                    "spell_key": new,
                }
            )
            replaced = True
            break
        if not replaced:
            continue
    return tuple({entry.entry_id: entry for entry in result}.values())
