from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.content.registry import ContentRegistry, ContentValidationError


EXPECTED_TABLE_COUNTS = {
    "personality_traits": 8,
    "ideals": 6,
    "bonds": 6,
    "flaws": 6,
}


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentValidationError(f"cannot load PHB background roleplay tables: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContentValidationError("PHB background roleplay tables must be a JSON object")
    return payload


def _expand_table(
    index: str,
    raw: object,
    key_map: dict[str, str],
) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        raise ContentValidationError(f"PHB background {index} roleplay table must be an object")

    expanded: dict[str, list[str]] = {}
    for short_key, field_name in key_map.items():
        values = raw.get(short_key)
        expected_count = EXPECTED_TABLE_COUNTS.get(field_name)
        if expected_count is None:
            raise ContentValidationError(f"unsupported roleplay table field: {field_name}")
        if not isinstance(values, list) or len(values) != expected_count:
            raise ContentValidationError(
                f"PHB background {index} {field_name} must contain {expected_count} entries"
            )
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ContentValidationError(
                f"PHB background {index} {field_name} entries must be non-empty strings"
            )
        expanded[field_name] = [value.strip() for value in values]

    if set(expanded) != set(EXPECTED_TABLE_COUNTS):
        raise ContentValidationError(
            f"PHB background {index} roleplay table fields are incomplete"
        )
    return expanded


def apply_phb_background_roleplay(
    registry: ContentRegistry,
    *,
    content_root: Path,
) -> ContentRegistry:
    """Overlay optional PHB roleplay suggestions onto normalized backgrounds.

    Mechanical variant behavior is deliberately untouched. The PHB source document
    instructs its five variants to use the parent background's suggested
    characteristics, so the sidecar names that roleplay-only table source explicitly.
    Every runtime background entry receives its own expanded arrays.
    """

    path = content_root / "phb2014" / "background-roleplay.json"
    payload = _load_payload(path)

    key_map = payload.get("table_keys")
    tables = payload.get("tables")
    variants = payload.get("variant_table_sources", {})
    if not isinstance(key_map, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in key_map.items()
    ):
        raise ContentValidationError("PHB roleplay table_keys must map strings to strings")
    if not isinstance(tables, dict) or not isinstance(variants, dict):
        raise ContentValidationError("PHB roleplay tables and variant_table_sources must be objects")

    expanded: dict[str, dict[str, list[str]]] = {}
    for index, raw_table in tables.items():
        if not isinstance(index, str):
            raise ContentValidationError("PHB roleplay table indexes must be strings")
        expanded[index] = _expand_table(index, raw_table, key_map)

    for variant_index, source_index in variants.items():
        if not isinstance(variant_index, str) or not isinstance(source_index, str):
            raise ContentValidationError("PHB roleplay variant mappings must be strings")
        source_table = expanded.get(source_index)
        if source_table is None:
            raise ContentValidationError(
                f"PHB roleplay variant {variant_index} references unknown table {source_index}"
            )
        expanded[variant_index] = {
            field: list(values) for field, values in source_table.items()
        }

    backgrounds = registry.list_kind("background", source="phb2014")
    expected_indexes = {entry.index for entry in backgrounds}
    if set(expanded) != expected_indexes:
        missing = sorted(expected_indexes - set(expanded))
        extra = sorted(set(expanded) - expected_indexes)
        raise ContentValidationError(
            f"PHB roleplay table coverage mismatch: missing={missing}, extra={extra}"
        )

    for entry in backgrounds:
        # ContentEntry instances are shared by the registry's indexes; updating this
        # optional data dictionary therefore keeps get/list views consistent without
        # altering stable identity, grants, or variant mechanics.
        entry.data["roleplay_suggestions"] = {
            field: list(values) for field, values in expanded[entry.index].items()
        }

    return registry
