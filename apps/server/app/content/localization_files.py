from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.content.identity import parse_stable_key
from app.content.localization import (
    SUPPORTED_CONTENT_LOCALES,
    ContentLocalizationCatalog,
    LocalizableFieldPolicy,
)
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
    """Return monolith first, then review-friendly shards in deterministic order."""

    locale_root = content_root / source / "locales"
    paths: list[Path] = []
    monolith = locale_root / f"{locale}.json"
    if monolith.is_file():
        paths.append(monolith)
    shard_root = locale_root / locale
    if shard_root.is_dir():
        paths.extend(sorted(path for path in shard_root.glob("*.json") if path.is_file()))
    return tuple(paths)


def load_content_localization_catalog(
    registry: ContentRegistry,
    content_root: Path,
    *,
    policy_path: Path | None = None,
) -> ContentLocalizationCatalog:
    """Load static locale overlays, including optional per-kind human-review shards.

    Translation wording is deliberately not validated here. The loader only
    protects structural identity: locale, StableKey source, canonical key
    existence, and conflicting duplicate fields. A reviewer may therefore leave
    mixed-language draft text in a shard without making runtime unusable.
    """

    policy = LocalizableFieldPolicy.from_path(
        policy_path or content_root / "localization" / "localizable-fields.json"
    )
    overlays: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

    for source in registry.enabled_pack_ids:
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
                        identity = (key, field_path)
                        if field_path in target and target[field_path] != value:
                            previous = field_sources[identity]
                            raise ContentValidationError(
                                "conflicting locale overlay field "
                                f"{key}::{field_path} in {previous} and {path}"
                            )
                        target[field_path] = value
                        field_sources[identity] = path

            overlays[(source, locale)] = merged

    return ContentLocalizationCatalog(registry, policy, overlays)
