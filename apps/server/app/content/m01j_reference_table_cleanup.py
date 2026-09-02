from __future__ import annotations

from app.content.identity import reference_to_stable_key
from app.content.m01j_reference_content import M01JReferenceRegistry
from app.content.registry import ContentRegistry, ContentValidationError


_FOUR_ELEMENTS_MAX_KI_ARTIFACTS = frozenset({"3", "4", "5", "6"})


def _validate_resolved_spell_reference_kinds(registry: M01JReferenceRegistry) -> None:
    """Reject localized fuzzy matches that resolve to a non-spell entity."""

    for subclass in registry.list_kind("subclass"):
        for field in ("spells", "expanded_spells"):
            rows = subclass.data.get(field, [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                raw_spell = row.get("spell")
                if raw_spell is None:
                    continue
                if not isinstance(raw_spell, dict):
                    raise ContentValidationError(
                        f"{subclass.key}:{field}: resolved spell reference must be an object"
                    )
                try:
                    spell_ref = reference_to_stable_key(raw_spell, kinds={"spell"})
                except ValueError as exc:
                    raise ContentValidationError(
                        f"{subclass.key}:{field}: resolved reference is not a spell: {raw_spell!r}"
                    ) from exc
                if spell_ref is None or registry.get_optional(spell_ref) is None:
                    raise ContentValidationError(
                        f"{subclass.key}:{field}: resolved spell is missing from registry: {raw_spell!r}"
                    )


def apply_m01j_reference_table_cleanup(registry: ContentRegistry) -> ContentRegistry:
    """Clean parser-only table artifacts and validate generated spell identity kinds.

    The temporary monk reference contains a "Spells and Ki" table whose second
    header is "maximum ki spent on a single spell". The generic docs parser sees
    the word "spell" in that header and otherwise mistakes the numeric 3/4/5/6
    values for spell names. Keep this correction deliberately narrow: only the
    known Four Elements rows, only unresolved numeric rows, and never a row that
    already carries a resolved spell identity.
    """

    if not isinstance(registry, M01JReferenceRegistry):
        raise ContentValidationError("M01-J table cleanup requires M01JReferenceRegistry")

    subclass = registry.get("phb2014:subclass:four-elements")
    raw_rows = subclass.data.get("spells", [])
    if not isinstance(raw_rows, list):
        raise ContentValidationError("Four Elements generated spells metadata must be a list")

    cleaned: list[object] = []
    removed: set[str] = set()
    for row in raw_rows:
        if not isinstance(row, dict):
            cleaned.append(row)
            continue

        unresolved = row.get("unresolved_spell_name")
        if unresolved in _FOUR_ELEMENTS_MAX_KI_ARTIFACTS:
            if row.get("spell") is not None:
                raise ContentValidationError(
                    f"Four Elements max-ki parser artifact unexpectedly resolved: {unresolved}"
                )
            removed.add(str(unresolved))
            continue
        cleaned.append(row)

    if removed and removed != _FOUR_ELEMENTS_MAX_KI_ARTIFACTS:
        raise ContentValidationError(
            "Four Elements max-ki parser artifact set drifted: "
            f"expected={sorted(_FOUR_ELEMENTS_MAX_KI_ARTIFACTS)}, actual={sorted(removed)}"
        )

    if removed:
        data = dict(subclass.data)
        data["spells"] = cleaned
        registry.overrides[subclass.key] = subclass.model_copy(update={"data": data})

    _validate_resolved_spell_reference_kinds(registry)
    return registry
