from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from app.content.identity import parse_stable_key, reference_to_stable_key, stable_key
from app.content.registry import CONTENT_PACKS_ROOT, ContentRegistry, ContentValidationError


INVENTORY_PATH = (
    CONTENT_PACKS_ROOT / "rules" / "dnd5e-2014" / "m01j-subclasses.json"
)
EXPECTED_SOURCES = ("phb2014", "scag", "xge", "tce")
ALLOWED_DISPOSITIONS = frozenset(
    {"implemented", "canonical_duplicate", "data_blocker"}
)


def _load_inventory(path: Path = INVENTORY_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentValidationError(f"cannot load M01-J subclass inventory: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContentValidationError("M01-J subclass inventory must be a JSON object")
    return payload


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


def _inventory_rows(payload: dict[str, Any]) -> tuple[dict[str, object], ...]:
    sources = payload.get("sources")
    if not isinstance(sources, dict) or set(sources) != set(EXPECTED_SOURCES):
        raise ContentValidationError(
            "M01-J subclass inventory sources must be exactly "
            + ", ".join(EXPECTED_SOURCES)
        )

    rows: list[dict[str, object]] = []
    for source in EXPECTED_SOURCES:
        class_groups = sources.get(source)
        if not isinstance(class_groups, dict) or not class_groups:
            raise ContentValidationError(f"M01-J inventory source {source} has no class groups")
        for class_index, raw_group in class_groups.items():
            if not isinstance(class_index, str) or not class_index:
                raise ContentValidationError(f"M01-J inventory {source} has invalid class index")
            if not isinstance(raw_group, dict):
                raise ContentValidationError(
                    f"M01-J inventory {source}/{class_index} must be an object"
                )
            level = raw_group.get("level")
            if not isinstance(level, int) or not 1 <= level <= 20:
                raise ContentValidationError(
                    f"M01-J inventory {source}/{class_index} has invalid acquisition level"
                )
            parent_source = raw_group.get("parent_source", "srd5.1")
            if not isinstance(parent_source, str):
                raise ContentValidationError(
                    f"M01-J inventory {source}/{class_index} has invalid parent_source"
                )
            parent_class_ref = stable_key(parent_source, "class", class_index)
            entries = raw_group.get("entries")
            if not isinstance(entries, list) or not entries:
                raise ContentValidationError(
                    f"M01-J inventory {source}/{class_index} has no subclass entries"
                )
            for raw_entry in entries:
                if not isinstance(raw_entry, list) or len(raw_entry) not in {3, 4}:
                    raise ContentValidationError(
                        f"M01-J inventory {source}/{class_index} entry must have 3 or 4 fields"
                    )
                index, name, disposition, *tail = raw_entry
                if not all(isinstance(value, str) and value for value in (index, name, disposition)):
                    raise ContentValidationError(
                        f"M01-J inventory {source}/{class_index} entry contains invalid strings"
                    )
                if disposition not in ALLOWED_DISPOSITIONS:
                    raise ContentValidationError(
                        f"M01-J inventory {source}/{class_index}/{index} has unsupported disposition {disposition}"
                    )
                canonical_key = tail[0] if tail else None
                if disposition == "canonical_duplicate":
                    if not isinstance(canonical_key, str) or not canonical_key:
                        raise ContentValidationError(
                            f"M01-J canonical duplicate {source}/{index} requires canonical_key"
                        )
                elif canonical_key is not None:
                    raise ContentValidationError(
                        f"M01-J {source}/{index} may only declare canonical_key as canonical_duplicate"
                    )

                rows.append(
                    {
                        "source": source,
                        "parent_class_ref": parent_class_ref,
                        "subclass_key": stable_key(source, "subclass", index),
                        "name": name,
                        "acquisition_class_level": level,
                        "disposition": disposition,
                        "canonical_key": canonical_key,
                    }
                )
    return tuple(rows)


def validate_m01j_inventory(registry: ContentRegistry) -> ContentRegistry:
    """Fail startup on silent M01-J inventory drift without treating blockers as implemented.

    The inventory deliberately accounts for source-book entries whose verified
    mechanics are not yet present. ``data_blocker`` is an explicit incomplete
    state and must never create a selectable runtime subclass.
    """

    payload = _load_inventory()
    if payload.get("phase") != "M01-J" or payload.get("ruleset") != "dnd5e-2014":
        raise ContentValidationError("M01-J subclass inventory phase/ruleset mismatch")

    blocker_text = payload.get("data_blocker")
    if not isinstance(blocker_text, str) or not blocker_text.strip():
        raise ContentValidationError("M01-J subclass inventory requires an explicit data-blocker reason")

    rows = _inventory_rows(payload)
    by_key = {str(row["subclass_key"]): row for row in rows}
    if len(by_key) != len(rows):
        raise ContentValidationError("M01-J subclass inventory contains duplicate source identities")

    expected_counts = payload.get("expected_counts")
    if not isinstance(expected_counts, dict):
        raise ContentValidationError("M01-J subclass inventory expected_counts is missing")
    actual_counts = Counter(str(row["source"]) for row in rows)
    maintained_counts = {source: actual_counts[source] for source in EXPECTED_SOURCES}
    if maintained_counts != expected_counts:
        raise ContentValidationError(
            f"M01-J subclass inventory count mismatch: expected={expected_counts}, actual={maintained_counts}"
        )

    for row in rows:
        subclass_key = str(row["subclass_key"])
        parent_class_ref = str(row["parent_class_ref"])
        disposition = str(row["disposition"])
        parent = registry.get_optional(parent_class_ref)
        if parent is None or parse_stable_key(parent.key).kind != "class":
            raise ContentValidationError(
                f"M01-J inventory {subclass_key} has missing parent class {parent_class_ref}"
            )

        runtime_entry = registry.get_optional(subclass_key)
        if disposition == "implemented":
            if runtime_entry is None:
                raise ContentValidationError(
                    f"M01-J inventory marks {subclass_key} implemented but runtime data is missing"
                )
            if parse_stable_key(runtime_entry.key).kind != "subclass":
                raise ContentValidationError(f"M01-J implemented entry has wrong kind: {subclass_key}")
            if _parent_ref(runtime_entry) != parent_class_ref:
                raise ContentValidationError(
                    f"M01-J implemented entry parent mismatch: {subclass_key}"
                )
            continue

        if disposition == "canonical_duplicate":
            if runtime_entry is not None:
                raise ContentValidationError(
                    f"M01-J canonical duplicate must not create a second runtime option: {subclass_key}"
                )
            canonical_key = row["canonical_key"]
            canonical = registry.get_optional(str(canonical_key))
            if canonical is None or parse_stable_key(canonical.key).kind != "subclass":
                raise ContentValidationError(
                    f"M01-J canonical duplicate target is missing: {subclass_key} -> {canonical_key}"
                )
            if _parent_ref(canonical) != parent_class_ref:
                raise ContentValidationError(
                    f"M01-J canonical duplicate target has wrong parent: {subclass_key} -> {canonical_key}"
                )
            continue

        if runtime_entry is not None:
            raise ContentValidationError(
                f"M01-J data blocker unexpectedly has runtime subclass data: {subclass_key}"
            )

    inventory_runtime_keys = {
        str(row["subclass_key"])
        for row in rows
        if row["disposition"] == "implemented"
    }
    actual_runtime_keys = {
        entry.key
        for source in EXPECTED_SOURCES
        for entry in registry.list_kind("subclass", source=source)
    }
    if actual_runtime_keys != inventory_runtime_keys:
        raise ContentValidationError(
            "M01-J runtime subclass inventory drift: "
            f"missing={sorted(inventory_runtime_keys - actual_runtime_keys)}, "
            f"extra={sorted(actual_runtime_keys - inventory_runtime_keys)}"
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
        try:
            parsed = parse_stable_key(raw, kinds={"subclass"})
        except ValueError as exc:
            raise ContentValidationError(f"{key}: invalid canonical_ref {raw}") from exc
        return stable_key(parsed.source, parsed.kind, parsed.index)
    if isinstance(raw, dict):
        try:
            resolved = reference_to_stable_key(raw, kinds={"subclass"})
        except ValueError as exc:
            raise ContentValidationError(f"{key}: invalid canonical_ref") from exc
        if resolved is not None:
            return resolved
    raise ContentValidationError(f"{key}: canonical_ref must be a subclass StableKey/reference")


def apply_m01j_subclass_relations(registry: ContentRegistry) -> ContentRegistry:
    """Expose canonical multi-pack subclasses through the existing class relation.

    P1 progression already gates subclass selection by per-class level, compiles
    subclass level feature rows, feeds subclass spell access into the canonical
    spell-source model, and lets feature resources flow into generic Current
    State counters. M01-J therefore only needs to make cross-pack subclasses
    discoverable without editing canonical SRD class files or duplicating the
    progression/compiler path.

    Runtime reprints may declare ``canonical_ref``. Only the canonical entry is
    injected into the parent class selector, so pack load order and localized
    display names cannot create duplicate Builder options.
    """

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


def m01j_inventory_summary() -> dict[str, object]:
    """Return static accounting for closeout/reporting without loading runtime content."""

    payload = _load_inventory()
    rows = _inventory_rows(payload)
    dispositions = Counter(str(row["disposition"]) for row in rows)
    return {
        "expected": len(rows),
        "implemented": dispositions["implemented"],
        "canonical_duplicates": dispositions["canonical_duplicate"],
        "data_blockers": dispositions["data_blocker"],
        "blocker_reason": payload["data_blocker"],
    }
