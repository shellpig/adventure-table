from __future__ import annotations

from dataclasses import dataclass

from app.domain.character.schemas import CharacterConcentrationState, CharacterState
from app.domain.combat.resolution import DamageOutcome


@dataclass(frozen=True)
class ConcentrationCheckRequest:
    owner_ref: str
    source_ref: str
    damage_taken: int
    dc: int


@dataclass(frozen=True)
class ConcentrationCheckResolution:
    request: ConcentrationCheckRequest
    total: int
    success: bool
    state: CharacterState
    events: tuple[dict[str, object], ...]


def concentration_dc(damage_taken: int) -> int:
    if damage_taken < 0:
        raise ValueError("damage_taken cannot be negative")
    return max(10, damage_taken // 2)


def concentration_check_for_damage(
    *,
    owner_ref: str,
    current: CharacterConcentrationState | None,
    outcome: DamageOutcome,
) -> ConcentrationCheckRequest | None:
    """Translate semantic damage into a canonical concentration save request."""

    if current is None or outcome.adjusted_total <= 0:
        return None
    return ConcentrationCheckRequest(
        owner_ref=owner_ref,
        source_ref=current.source_ref,
        damage_taken=outcome.adjusted_total,
        dc=concentration_dc(outcome.adjusted_total),
    )


def resolve_concentration_check(
    *,
    request: ConcentrationCheckRequest,
    state: CharacterState,
    d20: int,
    constitution_save_modifier: int,
) -> ConcentrationCheckResolution:
    """Resolve a pending check against canonical Character Current State.

    On failure the concentration pointer and every linked persistent temporary
    effect are removed together in the returned state. The caller persists the
    returned state and event in its existing transaction/idempotency boundary.
    """

    if d20 < 1 or d20 > 20:
        raise ValueError("concentration saving throw d20 must be between 1 and 20")
    current = state.concentration
    if current is None:
        raise ValueError("concentration ended before the pending check resolved")
    if current.source_ref != request.source_ref:
        raise ValueError("pending concentration check is stale")

    total = d20 + constitution_save_modifier
    success = total >= request.dc
    events: list[dict[str, object]] = [
        {
            "type": "concentration_check",
            "owner_ref": request.owner_ref,
            "source_ref": request.source_ref,
            "damage_taken": request.damage_taken,
            "dc": request.dc,
            "total": total,
            "success": success,
        }
    ]
    if success:
        next_state = state.model_copy(deep=True)
    else:
        linked = set(current.effect_ids)
        next_state = state.model_copy(
            update={
                "concentration": None,
                "temporary_effects": [
                    effect for effect in state.temporary_effects if effect.effect_id not in linked
                ],
            },
            deep=True,
        )
        events.append(
            {
                "type": "concentration_ended",
                "owner_ref": request.owner_ref,
                "source_ref": request.source_ref,
                "removed_effect_ids": sorted(linked),
                "reason": "failed_damage_save",
            }
        )

    return ConcentrationCheckResolution(
        request=request,
        total=total,
        success=success,
        state=next_state,
        events=tuple(events),
    )
