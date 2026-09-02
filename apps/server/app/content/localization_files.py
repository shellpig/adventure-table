from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.content.identity import parse_stable_key
from app.content.localization import (
    ROLEPLAY_FIELDS,
    SUPPORTED_CONTENT_LOCALES,
    ContentLocalizationCatalog,
    LocalizableFieldPolicy,
)
from app.content.localization_paths import read_localization_path
from app.content.registry import ContentRegistry, ContentValidationError


def _read_overlay_file(path: Path, locale: str) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentValidationError(f"cannot load locale overlay {path}: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ContentValidationError(f"locale overlay {path} schema_version must be 1")
    if payload.get("locale") != locale:
        raise ContentValidationError(f"locale overlay {path} locale mismatch")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, dict):
        raise ContentValidationError(f"locale overlay {path} entries must be an object")

    normalized: dict[str, dict[str, Any]] = {}
    for key, fields in raw_entries.items():
        if not isinstance(key, str) or not isinstance(fields, dict):
            raise ContentValidationError(f"locale overlay {path} has invalid entry payload")
        normalized[key] = dict(fields)
    return normalized


def _locale_paths(content_root: Path, source: str, locale: str) -> tuple[Path, ...]:
    """Prefer human-review shards; fall back to the legacy monolithic overlay."""

    locale_root = content_root / source / "locales"
    shard_root = locale_root / locale
    if shard_root.is_dir():
        shards = tuple(sorted(path for path in shard_root.glob("*.json") if path.is_file()))
        if shards:
            return shards

    monolith = locale_root / f"{locale}.json"
    return (monolith,) if monolith.is_file() else ()


def _reject_unsupported_locale_artifacts(content_root: Path, source: str) -> None:
    locale_root = content_root / source / "locales"
    if not locale_root.is_dir():
        return
    supported = set(SUPPORTED_CONTENT_LOCALES)
    for path in locale_root.iterdir():
        locale_name = path.stem if path.is_file() and path.suffix == ".json" else path.name
        if (path.is_dir() or path.suffix == ".json") and locale_name not in supported:
            raise ContentValidationError(
                f"unsupported locale artifact for {source}: {path}; expected one of {SUPPORTED_CONTENT_LOCALES}"
            )


def _validate_overlay_field_path(
    registry: ContentRegistry,
    *,
    key: str,
    field_path: str,
    path: Path | str,
) -> None:
    if not isinstance(field_path, str) or not field_path:
        raise ContentValidationError(f"locale overlay {path} contains a blank field path for {key}")
    payload = registry.get(key).model_dump(mode="python")
    try:
        read_localization_path(payload, field_path)
    except (KeyError, ValueError) as exc:
        raise ContentValidationError(
            f"locale overlay {path} references unknown field {key}::{field_path}"
        ) from exc


def _roleplay_parent_key(entry: Any) -> str | None:
    """Return the explicit presentation-reuse parent for a background."""

    raw = entry.data.get("roleplay_suggestions")
    if isinstance(raw, dict):
        inherited = raw.get("inherits_from")
        if isinstance(inherited, str):
            return inherited

    variant = entry.data.get("variant_of")
    if isinstance(variant, dict):
        parent = variant.get("key")
        if isinstance(parent, str):
            return parent
    return None


def _materialize_roleplay_presentation_inheritance(
    registry: ContentRegistry,
    overlays: dict[tuple[str, str], dict[str, dict[str, Any]]],
) -> None:
    """Reuse translated suggested-characteristic text without copying mechanics."""

    backgrounds = {entry.key: entry for entry in registry.list_kind("background")}

    for locale in SUPPORTED_CONTENT_LOCALES:
        resolved: set[str] = set()
        resolving: set[str] = set()

        def resolve(key: str) -> None:
            if key in resolved:
                return
            if key in resolving:
                raise ContentValidationError(
                    f"localized background roleplay inheritance cycle detected at {key}"
                )
            entry = backgrounds.get(key)
            if entry is None:
                return
            parent_key = _roleplay_parent_key(entry)
            if parent_key is None:
                resolved.add(key)
                return
            parent = backgrounds.get(parent_key)
            if parent is None:
                raise ContentValidationError(
                    f"{key}: localized roleplay parent does not exist: {parent_key}"
                )

            resolving.add(key)
            resolve(parent_key)

            child_raw = entry.data.get("roleplay_suggestions")
            parent_raw = parent.data.get("roleplay_suggestions")
            if isinstance(child_raw, dict) and isinstance(parent_raw, dict):
                child_source = parse_stable_key(key).source
                parent_source = parse_stable_key(parent_key).source
                child_fields = overlays.setdefault((child_source, locale), {}).setdefault(key, {})
                parent_fields = overlays.get((parent_source, locale), {}).get(parent_key, {})

                for field in ROLEPLAY_FIELDS:
                    child_values = child_raw.get(field)
                    parent_values = parent_raw.get(field)
                    if not isinstance(child_values, list) or not isinstance(parent_values, list):
                        continue
                    for index, child_value in enumerate(child_values):
                        if index >= len(parent_values) or child_value != parent_values[index]:
                            continue
                        field_path = f"data.roleplay_suggestions.{field}.{index}"
                        if field_path not in child_fields and field_path in parent_fields:
                            child_fields[field_path] = parent_fields[field_path]

            resolving.remove(key)
            resolved.add(key)

        for key in sorted(backgrounds):
            resolve(key)


def load_content_localization_catalog(
    registry: ContentRegistry,
    content_root: Path,
    *,
    policy_path: Path | None = None,
) -> ContentLocalizationCatalog:
    """Load locale overlays and enforce M02-G structural integrity gates.

    Runtime localization files may only use supported locales, existing StableKeys
    and existing canonical field paths. A locale/StableKey/field identity may be
    authored exactly once; duplicate definitions fail even when their values are
    textually identical so shard ownership stays unambiguous.
    """

    policy = LocalizableFieldPolicy.from_path(
        policy_path or content_root / "localization" / "localizable-fields.json"
    )
    overlays: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    for source in registry.enabled_pack_ids:
        _reject_unsupported_locale_artifacts(content_root, source)
        for locale in SUPPORTED_CONTENT_LOCALES:
            paths = _locale_paths(content_root, source, locale)
            if not paths:
                continue

            merged: dict[str, dict[str, Any]] = {}
            field_sources: dict[tuple[str, str], Path] = {}
            for path in paths:
                entries = _read_overlay_file(path, locale)
                for key, fields in entries.items():
                    parsed = parse_stable_key(key)
                    if parsed.source != source:
                        raise ContentValidationError(
                            f"locale overlay {path} contains cross-pack key {key}"
                        )
                    if registry.get_optional(key) is None:
                        raise ContentValidationError(
                            f"locale overlay {path} references unknown content key {key}"
                        )

                    target = merged.setdefault(key, {})
                    for field_path, value in fields.items():
                        _validate_overlay_field_path(
                            registry,
                            key=key,
                            field_path=field_path,
                            path=path,
                        )
                        identity = (key, field_path)
                        if field_path in target:
                            previous = field_sources[identity]
                            qualifier = "conflicting" if target[field_path] != value else "duplicate"
                            raise ContentValidationError(
                                f"{qualifier} locale overlay field {key}::{field_path} "
                                f"in {previous} and {path}"
                            )
                        target[field_path] = value
                        field_sources[identity] = path

            overlays[(source, locale)] = merged

    _materialize_roleplay_presentation_inheritance(registry, overlays)
    return ContentLocalizationCatalog(registry, policy, overlays)
