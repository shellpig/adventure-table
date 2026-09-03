from __future__ import annotations

from app.content.registry import ContentRegistry
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.schemas import (
    BuilderDraft,
    BuilderIssue,
    BuilderIssueSeverity,
)


RACE_VARIANT_CHOICE_PREFIX = "race-variant:"


def validate_race_variant_selection_ownership(
    draft: BuilderDraft,
    registry: ContentRegistry,
) -> tuple[BuilderIssue, ...]:
    """Reject branch selections owned by a different top-level race variant.

    M01-E deliberately allows inactive child selections from the *same* variant
    to remain in a Draft because stale branches are ignored by compilation. M01-M
    adds multiple mutually-exclusive top-level Tiefling variants, so selections
    owned by another top-level variant are a different boundary: accepting them
    would make an explicitly forged cross-variant payload appear valid.

    Ordinary UI switches prune the previous variant branch in the service layer.
    This validation remains the server-authoritative final gate for clients that
    explicitly submit cross-variant branch selections.
    """

    active_selection = draft.draft_payload.race_variant_selection
    active_ref = active_selection.reference_id if active_selection is not None else None
    active_prefix = (
        f"{deterministic_choice_id('race-variant', active_ref)}:"
        if active_ref is not None
        else None
    )

    issues: list[BuilderIssue] = []
    for choice_id in draft.draft_payload.choice_selections:
        if not choice_id.startswith(RACE_VARIANT_CHOICE_PREFIX):
            continue
        if active_prefix is not None and choice_id.startswith(active_prefix):
            continue

        # Keep related_refs limited to real installed identities. A forged
        # choice id can be arbitrary text and must not masquerade as content
        # provenance in error presentation.
        related_refs = (
            (active_ref,)
            if active_ref is not None and registry.get_optional(active_ref) is not None
            else ()
        )
        issues.append(
            BuilderIssue(
                code="cross_variant_choice_selection",
                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                path=f"draft_payload.choice_selections.{choice_id}",
                message=(
                    "Race-variant branch selections must belong to the currently "
                    "selected ancestry variant."
                ),
                related_refs=related_refs,
            )
        )

    return tuple(issues)
