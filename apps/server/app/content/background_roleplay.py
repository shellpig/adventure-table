from __future__ import annotations

from app.content.identity import parse_stable_key
from app.content.registry import ContentRegistry, ContentValidationError


ROLEPLAY_FIELDS = (
    "personality_traits",
    "ideals",
    "bonds",
    "flaws",
)


def _validate_roleplay_fields(
    background_key: str,
    suggestions: dict[str, object],
) -> None:
    for field in ROLEPLAY_FIELDS:
        value = suggestions.get(field)
        if value is None:
            continue
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ContentValidationError(
                f"{background_key}: roleplay_suggestions.{field} must be a list of non-empty strings"
            )


def apply_background_roleplay_inheritance(
    registry: ContentRegistry,
) -> ContentRegistry:
    """Resolve roleplay-table reuse without inheriting background mechanics.

    M01-C backgrounds may point at another background solely to reuse its
    personality/ideal/bond/flaw suggestions. The resolver copies only those four
    presentation fields. Skills, tools, languages, equipment, features, variants,
    and every other mechanical field remain owned by the selected background.
    """

    backgrounds = {entry.key: entry for entry in registry.list_kind("background")}
    resolved: set[str] = set()
    resolving: set[str] = set()

    def resolve(background_key: str) -> None:
        if background_key in resolved:
            return
        if background_key in resolving:
            raise ContentValidationError(
                f"background roleplay inheritance cycle detected at {background_key}"
            )
        background = backgrounds.get(background_key)
        if background is None:
            raise ContentValidationError(
                f"unknown background roleplay inheritance source: {background_key}"
            )

        raw = background.data.get("roleplay_suggestions")
        if raw is None:
            resolved.add(background_key)
            return
        if not isinstance(raw, dict):
            raise ContentValidationError(
                f"{background_key}: roleplay_suggestions must be an object"
            )
        _validate_roleplay_fields(background_key, raw)

        inherited_ref = raw.get("inherits_from")
        if inherited_ref is None:
            resolved.add(background_key)
            return
        if not isinstance(inherited_ref, str):
            raise ContentValidationError(
                f"{background_key}: roleplay_suggestions.inherits_from must be a StableKey string"
            )
        try:
            parsed = parse_stable_key(inherited_ref, kinds={"background"})
        except ValueError as exc:
            raise ContentValidationError(
                f"{background_key}: invalid roleplay inheritance source {inherited_ref}: {exc}"
            ) from exc
        if parsed.kind != "background" or inherited_ref not in backgrounds:
            raise ContentValidationError(
                f"{background_key}: unknown background roleplay inheritance source {inherited_ref}"
            )

        resolving.add(background_key)
        resolve(inherited_ref)
        parent = backgrounds[inherited_ref]
        parent_raw = parent.data.get("roleplay_suggestions")
        if not isinstance(parent_raw, dict):
            raise ContentValidationError(
                f"{background_key}: inherited background {inherited_ref} has no roleplay suggestions"
            )

        materialized = dict(raw)
        for field in ROLEPLAY_FIELDS:
            if field in materialized:
                continue
            inherited_values = parent_raw.get(field)
            if inherited_values is not None:
                materialized[field] = list(inherited_values)
        _validate_roleplay_fields(background_key, materialized)
        background.data["roleplay_suggestions"] = materialized
        resolving.remove(background_key)
        resolved.add(background_key)

    for key in sorted(backgrounds):
        resolve(key)
    return registry
