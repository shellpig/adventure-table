from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.content.registry import ContentRegistry, ContentValidationError
from app.paths import resolve_rules_root


PATCHABLE_SOURCES = frozenset({"srd5.1"})



def _overrides_path() -> Path:
    return (resolve_rules_root() / "m01j-entry-overrides.json").resolve()


def _load_patches() -> dict[str, dict[str, Any]]:
    path = _overrides_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentValidationError(f"cannot read M01-J entry overrides: {exc}") from exc
    patches = payload.get("patches")
    if not isinstance(patches, dict):
        raise ContentValidationError("M01-J entry overrides must contain a patch map")
    return patches


def apply_m01j_entry_overrides(registry: ContentRegistry) -> ContentRegistry:
    """Apply M01-J's additive field patches to already-installed SRD entries.

    M01-J needs a handful of SRD subclasses, features and level rows to carry
    extra mechanics (shared fighting-style pools, Champion's second style, the
    Land/Lore grant choices). The vendored ``srd5.1`` corpus is never edited in
    place, so those fields live here and are merged at load time.
    """

    for key, fields in _load_patches().items():
        source = key.split(":", 1)[0]
        if source not in PATCHABLE_SOURCES:
            raise ContentValidationError(
                f"M01-J entry override targets a non-patchable pack: {key}"
            )
        entry = registry.get_optional(key)
        if entry is None:
            raise ContentValidationError(f"M01-J entry override targets unknown entry: {key}")
        if not isinstance(fields, dict) or not fields:
            raise ContentValidationError(f"M01-J entry override for {key} must set fields")
        entry.data.update(fields)
    return registry
