from __future__ import annotations

from copy import deepcopy

from app.content.identity import reference_to_stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character.schemas import CharacterBuild
from app.domain.character_builder.optional_class_features import (
    OptionalClassFeatureSpec,
    OptionalFeatureRegistry,
    OptionalFeatureRuntime,
    _choice_id,
    _class_counts,
    _entry_label,
    _feature_is_active,
    _level_up_new_class_level,
    _optional_specs,
    _selection,
    _validate_active_extensions,
)
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderMode,
    BuilderOptionKind,
)


class M01IReferenceNormalizedRegistry:
    """Expose legacy embedded content references with canonical StableKeys.

    Imported SRD feature-specific choices predate the multi-pack StableKey
    contract and commonly contain only ``index/name/url``. M01-I retraining
    needs to compare those options with persisted ``feature_refs``. Normalizing
    the embedded reference at this read-only overlay boundary lets the generic
    pool machinery use one identity model without mutating source data.
    """

    def __init__(self, base: ContentRegistry) -> None:
        self.base = base

    @staticmethod
    def _normalize_entry(entry: ContentEntry) -> ContentEntry:
        if not stable_key_is_kind(entry.key, "feature"):
            return entry
        root = entry.data.get("feature_specific")
        if not isinstance(root, dict):
            return entry

        normalized = deepcopy(root)
        changed = False

        def walk(value: object) -> None:
            nonlocal changed
            if isinstance(value, dict):
                if "key" not in value:
                    try:
                        key = reference_to_stable_key(value)
                    except ValueError:
                        key = None
                    if key is not None:
                        value["key"] = key
                        changed = True
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(normalized)
        if not changed:
            return entry
        data = dict(entry.data)
        data["feature_specific"] = normalized
        return entry.model_copy(update={"data": data})

    def get(self, key: str) -> ContentEntry:
        return self._normalize_entry(self.base.get(key))

    def get_optional(self, key: str) -> ContentEntry | None:
        entry = self.base.get_optional(key)
        return None if entry is None else self._normalize_entry(entry)

    def list_kind(self, kind: str, *, source: str | None = None) -> tuple[ContentEntry, ...]:
        return tuple(
            self._normalize_entry(entry)
            for entry in self.base.list_kind(kind, source=source)
        )

    def resolve(self, *parts: str) -> ContentEntry:
        return self._normalize_entry(self.base.resolve(*parts))

    def __getattr__(self, name: str):
        return getattr(self.base, name)


def prepare_optional_class_features_for_m01i(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    base_build: CharacterBuild | None = None,
) -> OptionalFeatureRuntime:
    """Prepare M01-I features using the documented minimum-level semantics.

    A skipped optional feature remains adoptable on later level-ups once the
    character meets its minimum class level. Existing active features carry
    forward without asking the user to re-select them.
    """

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
        if draft.mode is BuilderMode.LEVEL_UP and (
            new_level is None or new_level < spec.minimum_class_level
        ):
            continue

        choice_id = _choice_id(draft, "optional-feature", feature_ref)
        selected = _selection(draft, choice_id)
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
    optional_registry = OptionalFeatureRegistry(registry, active_tuple)
    normalized_registry = M01IReferenceNormalizedRegistry(optional_registry)
    issues = _validate_active_extensions(normalized_registry, active_tuple)
    return OptionalFeatureRuntime(
        registry=normalized_registry,
        choices=tuple(choices),
        active_feature_refs=tuple(feature_ref for feature_ref, _spec in active_tuple),
        specs=specs,
        issues=issues,
    )
