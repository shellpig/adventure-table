from __future__ import annotations

from collections import Counter, defaultdict

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.m01j_reference_content import (
    EXPECTED_SOURCES,
    InventoryRow,
    m01j_reference_inventory,
)
from app.content.registry import ContentRegistry, ContentValidationError


ALLOWED_DISPOSITIONS = frozenset({"implemented", "canonical_duplicate"})


def _parent_ref(subclass_entry: object) -> str | None:
    data = getattr(subclass_entry, "data", None)
    if not isinstance(data, dict):
        return None
    raw = data.get("class")
    if not isinstance(raw, dict):
        return None
    try:
        return reference_to_stable_key(raw, kinds={"class"})
    except ValueError:
        return None


def _feature_refs_from_level(
    registry: ContentRegistry,
    row: InventoryRow,
    level: int,
) -> tuple[str, ...]:
    subclass_index = parse_stable_key(row.subclass_key, kinds={"subclass"}).index
    level_key = f"{row.source}:level:{subclass_index}-{level}"
    level_entry = registry.get_optional(level_key)
    if level_entry is None:
        raise ContentValidationError(
            f"M01-J implemented subclass is missing progression row {level_key}"
        )
    parent = level_entry.data.get("subclass")
    if not isinstance(parent, dict):
        raise ContentValidationError(f"{level_key}: subclass level row has no parent")
    try:
        parent_ref = reference_to_stable_key(parent, kinds={"subclass"})
    except ValueError as exc:
        raise ContentValidationError(f"{level_key}: invalid subclass parent") from exc
    if parent_ref != row.subclass_key:
        raise ContentValidationError(
            f"{level_key}: wrong subclass parent {parent_ref}; expected {row.subclass_key}"
        )
    features = level_entry.data.get("features")
    if not isinstance(features, list):
        raise ContentValidationError(f"{level_key}: features must be a list")
    refs: list[str] = []
    for reference in features:
        if not isinstance(reference, dict):
            raise ContentValidationError(f"{level_key}: feature reference must be an object")
        try:
            feature_ref = reference_to_stable_key(reference, kinds={"feature"})
        except ValueError as exc:
            raise ContentValidationError(f"{level_key}: invalid feature reference") from exc
        if feature_ref is None or registry.get_optional(feature_ref) is None:
            raise ContentValidationError(f"{level_key}: missing feature target {feature_ref}")
        refs.append(feature_ref)
    return tuple(refs)


def _validate_choice_metadata(
    registry: ContentRegistry,
    row: InventoryRow,
    subclass: object,
) -> None:
    data = getattr(subclass, "data", None)
    if not isinstance(data, dict):
        raise ContentValidationError(f"{row.subclass_key}: invalid subclass data")
    raw_choices = data.get("persistent_choices", [])
    if not isinstance(raw_choices, list):
        raise ContentValidationError(f"{row.subclass_key}: persistent_choices must be a list")
    seen: set[str] = set()
    for raw in raw_choices:
        if not isinstance(raw, dict):
            raise ContentValidationError(f"{row.subclass_key}: persistent choice must be an object")
        choice_key = raw.get("choice_key")
        minimum_level = raw.get("minimum_class_level")
        choose_total = raw.get("choose_total")
        option_refs = raw.get("option_refs")
        if not isinstance(choice_key, str) or not choice_key or choice_key in seen:
            raise ContentValidationError(f"{row.subclass_key}: invalid/duplicate persistent choice key")
        seen.add(choice_key)
        if not isinstance(minimum_level, int) or minimum_level < row.acquisition_class_level:
            raise ContentValidationError(f"{row.subclass_key}/{choice_key}: invalid minimum class level")
        if not isinstance(choose_total, int) or choose_total < 1:
            raise ContentValidationError(f"{row.subclass_key}/{choice_key}: invalid choose_total")
        if not isinstance(option_refs, (list, tuple)) or len(option_refs) < choose_total:
            raise ContentValidationError(f"{row.subclass_key}/{choice_key}: insufficient options")
        if len(option_refs) != len(set(option_refs)):
            raise ContentValidationError(f"{row.subclass_key}/{choice_key}: duplicate options")
        for option_ref in option_refs:
            if not isinstance(option_ref, str):
                raise ContentValidationError(f"{row.subclass_key}/{choice_key}: invalid option ref")
            option = registry.get_optional(option_ref)
            if option is None or parse_stable_key(option.key).kind != "feature":
                raise ContentValidationError(
                    f"{row.subclass_key}/{choice_key}: missing feature option {option_ref}"
                )

        progression = raw.get("progression", [])
        if not isinstance(progression, (list, tuple)):
            raise ContentValidationError(f"{row.subclass_key}/{choice_key}: invalid progression")
        previous_level = 0
        previous_count = 0
        for step in progression:
            if not isinstance(step, dict):
                raise ContentValidationError(f"{row.subclass_key}/{choice_key}: invalid progression step")
            class_level = step.get("class_level")
            count = step.get("choose_total")
            if (
                not isinstance(class_level, int)
                or not isinstance(count, int)
                or class_level <= previous_level
                or count < previous_count
                or count > len(option_refs)
            ):
                raise ContentValidationError(
                    f"{row.subclass_key}/{choice_key}: non-monotonic choice progression"
                )
            previous_level = class_level
            previous_count = count


def _validate_spell_metadata(
    registry: ContentRegistry,
    row: InventoryRow,
    subclass: object,
) -> None:
    data = getattr(subclass, "data", None)
    if not isinstance(data, dict):
        return
    for field in ("spells", "expanded_spells"):
        raw_rows = data.get(field, [])
        if not isinstance(raw_rows, list):
            raise ContentValidationError(f"{row.subclass_key}: {field} must be a list")
        for raw in raw_rows:
            if not isinstance(raw, dict):
                raise ContentValidationError(f"{row.subclass_key}: invalid {field} record")
            unresolved = raw.get("unresolved_spell_name")
            if unresolved is not None:
                raise ContentValidationError(
                    f"{row.subclass_key}: unresolved repository spell reference {unresolved!r}"
                )
            spell = raw.get("spell")
            if not isinstance(spell, dict):
                raise ContentValidationError(f"{row.subclass_key}: {field} row has no spell reference")
            try:
                spell_ref = reference_to_stable_key(spell, kinds={"spell"})
            except ValueError as exc:
                raise ContentValidationError(f"{row.subclass_key}: invalid spell reference") from exc
            if spell_ref is None or registry.get_optional(spell_ref) is None:
                raise ContentValidationError(f"{row.subclass_key}: missing spell target {spell_ref}")
            expected_access = "expanded" if field == "expanded_spells" else raw.get("access_type")
            if field == "expanded_spells" and raw.get("access_type") != expected_access:
                raise ContentValidationError(f"{row.subclass_key}: expanded spell row has wrong access type")
            if field == "spells" and raw.get("access_type") not in {
                "always_prepared",
                "granted",
                "known",
            }:
                raise ContentValidationError(
                    f"{row.subclass_key}: unsupported subclass spell access type {raw.get('access_type')}"
                )


def _validate_resource_metadata(
    registry: ContentRegistry,
    row: InventoryRow,
    subclass: object,
) -> None:
    data = getattr(subclass, "data", None)
    if not isinstance(data, dict):
        return
    raw_refs = data.get("resource_feature_refs", [])
    if not isinstance(raw_refs, list):
        raise ContentValidationError(f"{row.subclass_key}: resource_feature_refs must be a list")
    for feature_ref in raw_refs:
        if not isinstance(feature_ref, str):
            raise ContentValidationError(f"{row.subclass_key}: invalid resource feature ref")
        feature = registry.get_optional(feature_ref)
        if feature is None or feature.data.get("resource") is None:
            raise ContentValidationError(
                f"{row.subclass_key}: resource feature is missing capacity/recharge metadata: {feature_ref}"
            )


def validate_m01j_inventory(registry: ContentRegistry) -> ContentRegistry:
    """Close M01-J only when the verified subclass inventory is fully runnable."""

    rows = m01j_reference_inventory(registry)
    by_key = {row.subclass_key: row for row in rows}
    if len(by_key) != len(rows):
        raise ContentValidationError("M01-J subclass inventory contains duplicate source identities")

    actual_counts = Counter(row.source for row in rows)
    expected_counts = {"phb2014": 40, "scag": 11, "xge": 31, "tce": 30}
    maintained_counts = {source: actual_counts[source] for source in EXPECTED_SOURCES}
    if maintained_counts != expected_counts:
        raise ContentValidationError(
            f"M01-J subclass inventory count mismatch: expected={expected_counts}, actual={maintained_counts}"
        )

    dispositions = Counter(row.disposition for row in rows)
    if set(dispositions) - ALLOWED_DISPOSITIONS:
        raise ContentValidationError(
            f"M01-J closeout contains unsupported/incomplete dispositions: {dict(dispositions)}"
        )
    if dispositions["implemented"] + dispositions["canonical_duplicate"] != len(rows):
        raise ContentValidationError("M01-J subclass inventory is not fully accounted for")

    implemented_keys: set[str] = set()
    for row in rows:
        parent = registry.get_optional(row.parent_class_ref)
        if parent is None or parse_stable_key(parent.key).kind != "class":
            raise ContentValidationError(
                f"M01-J inventory {row.subclass_key} has missing parent class {row.parent_class_ref}"
            )

        runtime_entry = registry.get_optional(row.subclass_key)
        if row.disposition == "canonical_duplicate":
            if runtime_entry is not None:
                raise ContentValidationError(
                    f"M01-J canonical duplicate must not create a second runtime option: {row.subclass_key}"
                )
            canonical = registry.get_optional(str(row.canonical_key))
            if canonical is None or parse_stable_key(canonical.key).kind != "subclass":
                raise ContentValidationError(
                    f"M01-J canonical duplicate target is missing: {row.subclass_key} -> {row.canonical_key}"
                )
            if _parent_ref(canonical) != row.parent_class_ref:
                raise ContentValidationError(
                    f"M01-J canonical duplicate target has wrong parent: {row.subclass_key} -> {row.canonical_key}"
                )
            continue

        implemented_keys.add(row.subclass_key)
        if runtime_entry is None or parse_stable_key(runtime_entry.key).kind != "subclass":
            raise ContentValidationError(
                f"M01-J inventory marks {row.subclass_key} implemented but runtime data is missing"
            )
        if _parent_ref(runtime_entry) != row.parent_class_ref:
            raise ContentValidationError(f"M01-J implemented entry parent mismatch: {row.subclass_key}")
        if runtime_entry.data.get("acquisition_class_level") != row.acquisition_class_level:
            raise ContentValidationError(
                f"{row.subclass_key}: acquisition class level metadata mismatch"
            )
        if tuple(runtime_entry.data.get("progression_levels", ())) != row.progression_levels:
            raise ContentValidationError(f"{row.subclass_key}: progression level metadata mismatch")
        reference_doc = runtime_entry.data.get("reference_doc")
        if not isinstance(reference_doc, str) or not reference_doc:
            raise ContentValidationError(f"{row.subclass_key}: repository reference provenance is missing")

        level_features: list[str] = []
        for level in row.progression_levels:
            level_features.extend(_feature_refs_from_level(registry, row, level))
        declared_features = runtime_entry.data.get("progression_feature_refs")
        if not isinstance(declared_features, list):
            raise ContentValidationError(f"{row.subclass_key}: progression_feature_refs must be a list")
        if tuple(dict.fromkeys(level_features)) != tuple(declared_features):
            raise ContentValidationError(
                f"{row.subclass_key}: progression_feature_refs do not match level rows"
            )
        _validate_choice_metadata(registry, row, runtime_entry)
        _validate_spell_metadata(registry, row, runtime_entry)
        _validate_resource_metadata(registry, row, runtime_entry)

    actual_runtime_keys = {
        entry.key
        for source in EXPECTED_SOURCES
        for entry in registry.list_kind("subclass", source=source)
    }
    if actual_runtime_keys != implemented_keys:
        raise ContentValidationError(
            "M01-J runtime subclass inventory drift: "
            f"missing={sorted(implemented_keys - actual_runtime_keys)}, "
            f"extra={sorted(actual_runtime_keys - implemented_keys)}"
        )
    return registry


def _canonical_runtime_subclass_ref(entry: object) -> str:
    data = getattr(entry, "data", None)
    key = getattr(entry, "key", None)
    if not isinstance(data, dict) or not isinstance(key, str):
        raise ContentValidationError("invalid runtime subclass entry")
    raw = data.get("canonical_ref")
    if raw is None:
        return key
    if isinstance(raw, str):
        parsed = parse_stable_key(raw, kinds={"subclass"})
        return f"{parsed.source}:{parsed.kind}:{parsed.index}"
    if isinstance(raw, dict):
        resolved = reference_to_stable_key(raw, kinds={"subclass"})
        if resolved is not None:
            return resolved
    raise ContentValidationError(f"{key}: canonical_ref must be a subclass StableKey/reference")


def apply_m01j_subclass_relations(registry: ContentRegistry) -> ContentRegistry:
    """Expose canonical multi-pack subclasses through existing parent classes."""

    supported_sources = frozenset((*EXPECTED_SOURCES, "srd5.1"))
    canonical_by_parent: dict[str, list[object]] = defaultdict(list)

    for entry in registry.list_kind("subclass"):
        if entry.source not in supported_sources:
            continue
        parent_ref = _parent_ref(entry)
        if parent_ref is None:
            raise ContentValidationError(f"{entry.key}: subclass parent class is invalid")
        canonical_key = _canonical_runtime_subclass_ref(entry)
        canonical = registry.get_optional(canonical_key)
        if canonical is None or parse_stable_key(canonical.key).kind != "subclass":
            raise ContentValidationError(
                f"{entry.key}: canonical subclass target is missing: {canonical_key}"
            )
        if _parent_ref(canonical) != parent_ref:
            raise ContentValidationError(
                f"{entry.key}: canonical subclass target belongs to a different parent class"
            )
        if canonical.key == entry.key:
            canonical_by_parent[parent_ref].append(canonical)

    for class_entry in registry.list_kind("class"):
        discovered = canonical_by_parent.get(class_entry.key)
        if not discovered:
            continue
        existing_by_key: dict[str, dict[str, object]] = {}
        raw_existing = class_entry.data.get("subclasses")
        if isinstance(raw_existing, list):
            for raw_ref in raw_existing:
                if not isinstance(raw_ref, dict):
                    continue
                try:
                    existing_key = reference_to_stable_key(raw_ref, kinds={"subclass"})
                except ValueError:
                    continue
                if existing_key is not None:
                    existing_by_key[existing_key] = raw_ref

        ordered_keys = list(existing_by_key)
        for subclass in sorted(
            discovered,
            key=lambda item: (str(getattr(item, "source", "")), str(getattr(item, "key", ""))),
        ):
            subclass_key = str(getattr(subclass, "key"))
            if subclass_key not in ordered_keys:
                ordered_keys.append(subclass_key)

        normalized_refs: list[dict[str, object]] = []
        for subclass_key in ordered_keys:
            target = registry.get_optional(subclass_key)
            if target is None or _parent_ref(target) != class_entry.key:
                continue
            normalized_refs.append(
                existing_by_key.get(
                    subclass_key,
                    {"key": target.key, "name": target.name},
                )
            )
        class_entry.data["subclasses"] = normalized_refs
    return registry


def m01j_inventory_summary(registry: ContentRegistry | None = None) -> dict[str, object]:
    rows = m01j_reference_inventory(registry) if registry is not None else m01j_reference_inventory(object())
    dispositions = Counter(row.disposition for row in rows)
    return {
        "expected": len(rows),
        "implemented": dispositions["implemented"],
        "canonical_duplicates": dispositions["canonical_duplicate"],
        "data_blockers": 0,
        "sources": dict(Counter(row.source for row in rows)),
    }
