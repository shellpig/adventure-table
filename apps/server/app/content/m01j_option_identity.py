from __future__ import annotations

from app.content.m01j_reference_content import M01JReferenceRegistry
from app.content.registry import ContentRegistry, ContentValidationError


RUNE_KNIGHT_REF = "tce:subclass:rune-knight"
_RUNE_CANONICAL_NAMES = {
    "山丘符文": "Hill Rune",
    "風暴符文": "Storm Rune",
}


def apply_m01j_option_identity_normalization(registry: ContentRegistry) -> ContentRegistry:
    """Keep docs-derived localized headings out of canonical option identity names."""

    if not isinstance(registry, M01JReferenceRegistry):
        raise ContentValidationError("M01-J option identity normalization requires M01JReferenceRegistry")

    subclass = registry.get(RUNE_KNIGHT_REF)
    choices = subclass.data.get("persistent_choices", [])
    rune_choice = next(
        (
            choice
            for choice in choices
            if isinstance(choice, dict) and choice.get("choice_key") == "rune-carver"
        ),
        None,
    )
    if rune_choice is None:
        raise ContentValidationError("M01-J Rune Knight is missing the rune-carver choice")

    minimum_levels = rune_choice.get("option_minimum_levels", {})
    if not isinstance(minimum_levels, dict):
        raise ContentValidationError("M01-J Rune Knight option level metadata is invalid")
    gated_refs = {
        ref
        for ref, minimum_level in minimum_levels.items()
        if isinstance(ref, str) and minimum_level == 7
    }
    if len(gated_refs) != 2:
        raise ContentValidationError(
            f"M01-J Rune Knight expected two level-7 rune options, got {len(gated_refs)}"
        )

    normalized_names: set[str] = set()
    for ref in gated_refs:
        entry = registry.get(ref)
        heading = entry.data.get("reference_heading_zh")
        if not isinstance(heading, str):
            raise ContentValidationError(f"{ref}: missing verified Chinese rune heading")
        canonical_name = next(
            (name for marker, name in _RUNE_CANONICAL_NAMES.items() if marker in heading),
            None,
        )
        if canonical_name is None:
            raise ContentValidationError(f"{ref}: unknown level-7 Rune Knight heading {heading!r}")

        data = dict(entry.data)
        data["name"] = canonical_name
        normalized = entry.model_copy(update={"name": canonical_name, "data": data})
        if ref in registry.supplemental:
            registry.supplemental[ref] = normalized
        else:
            registry.overrides[ref] = normalized
        normalized_names.add(canonical_name)

    if normalized_names != set(_RUNE_CANONICAL_NAMES.values()):
        raise ContentValidationError(
            f"M01-J Rune Knight canonical rune names are incomplete: {sorted(normalized_names)}"
        )
    return registry
