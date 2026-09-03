from __future__ import annotations

import json
from typing import Any

from app.content.identity import reference_to_stable_key
from app.content.m01m_models import M01MRacialSpellAccessData
from app.content.registry import (
    CONTENT_PACKS_ROOT,
    ContentRegistry,
    ContentValidationError,
)


OVERRIDES_PATH = CONTENT_PACKS_ROOT / "rules" / "dnd5e-2014" / "m01m-entry-overrides.json"
PATCHABLE_TARGETS = frozenset({"srd5.1:trait:infernal-legacy"})


def _load_patches() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
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
        if not isinstance(fields, dict) or set(fields) != {"racial_spell_access"}:
            raise ContentValidationError(
                f"M01-M entry override for {key} may only set racial_spell_access"
            )
        raw_access = fields.get("racial_spell_access")
        if not isinstance(raw_access, list) or len(raw_access) != 3:
            raise ContentValidationError(
                "M01-M Infernal Legacy override must contain exactly three spell rows"
            )

        spell_keys: list[str] = []
        for index, raw in enumerate(raw_access):
            try:
                access = M01MRacialSpellAccessData.model_validate(raw)
                spell_key = reference_to_stable_key(
                    access.spell.model_dump(exclude_none=True),
                    kinds={"spell"},
                )
            except ValueError as exc:
                raise ContentValidationError(
                    f"M01-M Infernal Legacy spell row {index} is malformed: {exc}"
                ) from exc
            if spell_key is None or registry.get_optional(spell_key) is None:
                raise ContentValidationError(
                    f"M01-M Infernal Legacy spell row {index} is dangling: {spell_key}"
                )
            spell_keys.append(spell_key)

        expected = [
            "srd5.1:spell:thaumaturgy",
            "srd5.1:spell:hellish-rebuke",
            "srd5.1:spell:darkness",
        ]
        if spell_keys != expected:
            raise ContentValidationError(
                "M01-M Asmodeus baseline must remain Thaumaturgy / Hellish Rebuke / Darkness"
            )
        entry.data.update(fields)
    return registry
