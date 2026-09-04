from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.content.identity import reference_to_stable_key
from app.content.m01m_models import M01MRacialSpellAccessData
from app.content.registry import ContentRegistry, ContentValidationError
from app.paths import resolve_rules_root


PATCHABLE_TARGETS = frozenset({"srd5.1:trait:infernal-legacy"})


def _overrides_path() -> Path:
    return (resolve_rules_root() / "m01m-entry-overrides.json").resolve()


def _load_patches() -> dict[str, dict[str, Any]]:
    path = _overrides_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentValidationError(f"cannot read M01-M entry overrides: {exc}") from exc
    if payload.get("phase") != "M01-M" or payload.get("ruleset") != "dnd5e-2014":
        raise ContentValidationError("M01-M entry overrides have wrong phase/ruleset")
    patches = payload.get("patches")
    if not isinstance(patches, dict):
        raise ContentValidationError("M01-M entry overrides must contain a patch map")
    if set(patches) != PATCHABLE_TARGETS:
        raise ContentValidationError(
            "M01-M entry overrides must patch exactly the canonical Infernal Legacy trait"
        )
    return patches


def apply_m01m_entry_overrides(registry: ContentRegistry) -> ContentRegistry:
    """Add typed Asmodeus baseline spell metadata without changing SRD identity.

    Standard SRD/PHB Tiefling is the canonical MTF Asmodeus identity. The vendored
    SRD trait carries the prose but predates the project's racial-spell substrate,
    so M01-M adds only machine-readable casting metadata at registry load time.
    Race-variant replacement then removes the same trait grant, which naturally
    removes these baseline spell entries before a non-Asmodeus/SCAG replacement
    is compiled.
    """

    for key, fields in _load_patches().items():
        entry = registry.get_optional(key)
        if entry is None:
            raise ContentValidationError(f"M01-M entry override targets unknown entry: {key}")
        if not isinstance(fields, dict) or not fields:
            raise ContentValidationError(f"M01-M entry override for {key} must set fields")
        entry.data.update(fields)

        raw_access = entry.data.get("racial_spell_access", [])
        if not isinstance(raw_access, list):
            raise ContentValidationError(f"M01-M racial spell metadata must be a list: {key}")
        try:
            typed_access = tuple(M01MRacialSpellAccessData.model_validate(row) for row in raw_access)
        except (TypeError, ValueError) as exc:
            raise ContentValidationError(f"M01-M invalid racial spell metadata for {key}: {exc}") from exc
        for access in typed_access:
            spell_ref = reference_to_stable_key(access.spell, kinds={"spell"})
            if spell_ref is None or registry.get_optional(spell_ref) is None:
                raise ContentValidationError(
                    f"M01-M racial spell metadata targets missing spell: {spell_ref}"
                )
    return registry
