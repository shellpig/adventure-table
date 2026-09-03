"""Shared draft helpers for the M01-M MTF / Tiefling matrices.

Every M01-M matrix needs the same thing: a complete draft that sits on one
ancestry, optionally with a top-level race variant and a chosen option in each
of its replacement groups. Building that by hand in four test modules would be
four copies of the same twelve lines.

The HTTP / restart plumbing is reused from ``m01k_support`` rather than copied;
it is generic builder infrastructure that happens to have been written first for
M01-K, and M01-L already reuses it the same way.
"""

from __future__ import annotations

from typing import Any

import m01k_support as S

from app.domain.character_builder.schemas import (
    BuilderChoiceSelection,
    BuilderDraftPayload,
    BuilderReferenceSelection,
)


TIEFLING = "srd5.1:race:tiefling"
SCAG_TIEFLING_VARIANT = "scag:race-variant:tiefling-variants"
ELF = "srd5.1:race:elf"
DWARF = "srd5.1:race:dwarf"
GITH = "mtf:race:gith"

ABILITY_GROUP = "ability-package"
LEGACY_GROUP = "legacy"


def group_choice_id(variant_ref: str, group_id: str) -> str:
    """Deterministic identity of one replacement group inside a race variant."""

    from app.domain.character_builder.choices import deterministic_choice_id

    return deterministic_choice_id("race-variant", variant_ref, group_id)


def base_payload(
    *,
    race: str,
    level: int = 1,
    abilities: dict[str, int] | None = None,
    name: str = "M01-M Hero",
) -> BuilderDraftPayload:
    return S.payload(
        S.class_levels(
            "fighter",
            level,
            first_hp=10,
            later_hp=6,
            subclass_ref="srd5.1:subclass:champion",
        ),
        name=name,
        race=race,
        abilities=abilities,
    )


def with_subrace(payload: BuilderDraftPayload, subrace_ref: str) -> BuilderDraftPayload:
    return payload.model_copy(
        update={"subrace_selection": BuilderReferenceSelection(reference_id=subrace_ref)}
    )


def with_variant(
    payload: BuilderDraftPayload,
    variant_ref: str | None,
    *,
    options: dict[str, str] | None = None,
) -> BuilderDraftPayload:
    """Select a top-level race variant and one option per named replacement group."""

    updated = payload.model_copy(
        update={
            "race_variant_selection": (
                BuilderReferenceSelection(reference_id=variant_ref)
                if variant_ref is not None
                else None
            )
        }
    )
    if not options:
        return updated
    assert variant_ref is not None
    selections = {}
    for group_id, option_id in options.items():
        choice_id = group_choice_id(variant_ref, group_id)
        selections[choice_id] = BuilderChoiceSelection(
            choice_id=choice_id,
            source_ref=variant_ref,
            selected_option_ids=(option_id,),
        )
    return S.with_selections(updated, selections)


def complete(payload: BuilderDraftPayload, content=None):
    """Fill every remaining required choice and compile. Returns (result, payload)."""

    content = content or S.registry()
    filled = S.auto_fill(payload, content, skip_sources=set())
    filled = S.fill_spell_choices(filled, content)
    result, _ = S.compile_payload(filled, content)
    return result, filled


def ancestry(
    *,
    race: str,
    subrace: str | None = None,
    variant: str | None = None,
    options: dict[str, str] | None = None,
    level: int = 1,
    abilities: dict[str, int] | None = None,
    content=None,
):
    content = content or S.registry()
    payload = base_payload(race=race, level=level, abilities=abilities)
    if subrace is not None:
        payload = with_subrace(payload, subrace)
    if variant is not None or options is not None:
        payload = with_variant(payload, variant, options=options)
    return complete(payload, content)


def grant_refs(result) -> list[str]:
    return [grant.reference_id for grant in result.resolved_summary.grants if grant.reference_id]


def effective_abilities(result) -> dict[str, int]:
    return {entry.ability: entry.effective for entry in result.resolved_summary.ability_scores}


def spell_access(result) -> dict[str, Any]:
    build = result.build_candidate
    assert build is not None
    return {entry.spell_key: entry for entry in build.spell_access_entries}


def http_ready_payload(payload: BuilderDraftPayload, content=None) -> dict[str, Any]:
    """Fill a payload remaining required choices and render it for the API."""

    content = content or S.registry()
    filled = S.auto_fill(payload, content, skip_sources=set())
    filled = S.fill_spell_choices(filled, content)
    return filled.model_dump(mode="json")


def http_create_character(client, payload: BuilderDraftPayload, content=None) -> dict[str, Any]:
    view = S.http_create_draft(client, http_ready_payload(payload, content))
    assert [issue["code"] for issue in view["validation"]["issues"]] == []
    return S.http_confirm(client, view)
