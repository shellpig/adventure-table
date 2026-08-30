from __future__ import annotations

from collections.abc import Iterable

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.schemas import ContentEntry


class VariantRelationValidationError(ValueError):
    pass


def validate_variant_relation_kinds(
    source_entries: Iterable[ContentEntry],
    entries: dict[str, ContentEntry],
) -> None:
    """Require variant_of to point at an entry of the same StableKind.

    variant_of is provenance metadata only, but its relation must still be
    structurally valid. A race can therefore point only at a race, a background
    only at a background, and so on. This deliberately adds no inheritance.
    """

    for source_entry in source_entries:
        raw_variant = source_entry.data.get("variant_of")
        if raw_variant is None:
            continue
        if not isinstance(raw_variant, dict):
            raise VariantRelationValidationError(
                f"{source_entry.key}: variant_of must be a content reference"
            )

        source_kind = parse_stable_key(source_entry.key).kind
        try:
            target_key = reference_to_stable_key(raw_variant, kinds={source_kind})
        except ValueError as exc:
            raise VariantRelationValidationError(
                f"{source_entry.key}: invalid variant_of reference: {exc}"
            ) from exc
        if target_key is None:
            raise VariantRelationValidationError(
                f"{source_entry.key}: variant_of must contain a stable content identity"
            )

        target = entries.get(target_key)
        if target is None:
            raise VariantRelationValidationError(
                f"{source_entry.key}: dangling variant_of reference -> {target_key}"
            )
        target_kind = parse_stable_key(target.key).kind
        if target_kind != source_kind:
            raise VariantRelationValidationError(
                f"{source_entry.key}: wrong-kind variant_of {target_key}; "
                f"expected {source_kind}, got {target_kind}"
            )
