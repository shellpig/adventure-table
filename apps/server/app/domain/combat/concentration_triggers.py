from __future__ import annotations

from dataclasses import dataclass

from app.domain.combat.effect_resolver import (
    ActiveEffect,
    Concentration,
    ConcentrationTransition,
    concentration_dc,
    resolve_concentration_damage,
)
from app.domain.combat.resolution import DamageOutcome


@dataclass(frozen=True)
class ConcentrationCheckRequest:
    owner_ref: str
    source_ref: str
    damage_taken: int
    dc: int


def concentration_check_for_damage(
    *, owner_ref: str, current: Concentration | None, outcome: DamageOutcome
) -> ConcentrationCheckRequest | None:
    """Translate the P4-C semantic damage boundary into a P4-D check request.

    ``adjusted_total`` is used deliberately: immunity that reduces the damage
    instance to zero creates no check, while damage absorbed by temporary hit
    points still counts as damage taken and therefore does create a check.
    """

    if current is None or outcome.adjusted_total <= 0:
        return None
    if current.owner_ref != owner_ref:
        raise ValueError("concentration owner does not match damaged creature")
    return ConcentrationCheckRequest(
        owner_ref=owner_ref,
        source_ref=current.source_ref,
        damage_taken=outcome.adjusted_total,
        dc=concentration_dc(outcome.adjusted_total),
    )


def resolve_concentration_check(
    *,
    request: ConcentrationCheckRequest,
    current: Concentration | None,
    effects: tuple[ActiveEffect, ...],
    d20: int,
    constitution_save_modifier: int,
) -> ConcentrationTransition:
    if current is None:
        raise ValueError("concentration ended before the pending check resolved")
    if current.owner_ref != request.owner_ref or current.source_ref != request.source_ref:
        raise ValueError("pending concentration check is stale")
    transition = resolve_concentration_damage(
        current=current,
        effects=effects,
        damage_taken=request.damage_taken,
        d20=d20,
        constitution_save_modifier=constitution_save_modifier,
    )
    check = transition.events[0] if transition.events else None
    if check is not None and check.get("dc") != request.dc:
        raise ValueError("concentration check DC changed during resolution")
    return transition
