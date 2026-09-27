"""P5-C spatial targeting (backend only).

Pure functions: no dice, no DB, no events. Attack and targeted-spell range
validation must build only on ``grid_distance`` and the sight-line test
below, so distance semantics cannot drift from movement (P5-B).

The hard blocker rule is deliberately lenient: a target is blocked only when
EVERY source-cell-center to target-cell-center segment properly crosses a
wall or a closed/locked door edge. One visible pair is enough to be legal.
Corner grazes (touching a barrier endpoint) do not block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal

from app.domain.combat.resolution import AttackKind, ResolvedAttack
from app.domain.spatial.pathing import grid_distance
from app.domain.spatial.primitives import BarrierSegment, GridCell


class CombatTargetOutOfRangeError(RuntimeError):
    """Tactical spatial rejection: target outside reach/range (HTTP 409 combat_target_out_of_range)."""


class CombatTargetBlockedError(RuntimeError):
    """Tactical spatial rejection: hard blocker on every sight line (HTTP 409 combat_target_blocked)."""


Audience = Literal["dm", "player"]
"""DM sees full-truth blockers; players get a public-safe blocker kind."""

BlockerKind = Literal[
    "wall", "closed_door", "locked_door", "hidden_wall", "hidden_door",
]


@dataclass(frozen=True)
class BarrierView:
    """One sight blocker with its full-truth kind.

    ``kind`` is never shown to players directly; use
    :func:`public_blocker_kind` before exposing it.
    """

    segment: BarrierSegment
    kind: BlockerKind


@dataclass(frozen=True)
class SpatialTargetingResult:
    legal: bool
    distance_feet: int | None
    range_band: str  # "reach" | "normal" | "long" | "out_of_range" | "unknown"
    blocked: bool
    blocker_kind: str | None  # public-safe: "wall" | "closed_door" | "locked_door"
    requires_dm_adjudication: bool
    is_long_range: bool
    target_within_5ft: bool


def public_blocker_kind(kind: BlockerKind, *, audience: Audience) -> str | None:
    """Project a full-truth blocker kind to what the audience may learn.

    Players must never learn a hidden wall/door's identity or position from
    a targeting rejection; it reads as a plain wall. DMs see full truth.
    """
    if audience == "dm":
        return kind
    if kind in ("hidden_wall", "hidden_door"):
        return "wall"
    return kind


def _orientation(ax: int, ay: int, bx: int, by: int, cx: int, cy: int) -> int:
    return (by - ay) * (cx - ax) - (bx - ax) * (cy - ay)


def _segments_properly_cross(
    a1: tuple[int, int], a2: tuple[int, int],
    b1: tuple[int, int], b2: tuple[int, int],
) -> bool:
    """True only when the segments cross at an interior point of both.

    Endpoint touches (corner grazes) do not count as crossing. All inputs
    are integer coordinates in x2-scaled space, so this is exact.
    """
    o1 = _orientation(*a1, *a2, *b1)
    o2 = _orientation(*a1, *a2, *b2)
    o3 = _orientation(*b1, *b2, *a1)
    o4 = _orientation(*b1, *b2, *a2)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def _cell_center_x2(cell: GridCell) -> tuple[int, int]:
    return (2 * cell.x + 1, 2 * cell.y + 1)


def _barrier_endpoints_x2(barrier: BarrierSegment) -> tuple[tuple[int, int], tuple[int, int]]:
    return ((2 * barrier.x1, 2 * barrier.y1), (2 * barrier.x2, 2 * barrier.y2))


def _sight_line_blocked(
    source: GridCell, target: GridCell, barriers: tuple[BarrierView, ...]
) -> BarrierView | None:
    """Return the first barrier properly crossing the center-to-center line."""
    a1 = _cell_center_x2(source)
    a2 = _cell_center_x2(target)
    for barrier in barriers:
        b1, b2 = _barrier_endpoints_x2(barrier.segment)
        if _segments_properly_cross(a1, a2, b1, b2):
            return barrier
    return None


def is_target_blocked(
    source_cells: Iterable[GridCell],
    target_cells: Iterable[GridCell],
    barriers: tuple[BarrierView, ...],
) -> BarrierView | None:
    """Hard blocker check. Returns a blocking barrier, or None when visible.

    The target is blocked only when every source/target cell-center pair is
    crossed by some barrier. Deterministic: barriers are checked in order.
    """
    source = tuple(source_cells)
    target = tuple(target_cells)
    first_blocker: BarrierView | None = None
    for s_cell in source:
        for t_cell in target:
            blocker = _sight_line_blocked(s_cell, t_cell, barriers)
            if blocker is None:
                return None
            if first_blocker is None:
                first_blocker = blocker
    return first_blocker


def is_within_reach(
    source_cells: Iterable[GridCell],
    target_cells: Iterable[GridCell],
    attack: ResolvedAttack,
) -> bool:
    """Shared reach query (P5-E opportunity attacks build on this).

    Reach is melee reach only: a ranged band is never reach, so an attack
    without ``reach_feet`` never threatens. Never triggers reactions; it is a
    pure distance question.
    """
    if attack.reach_feet is None:
        return False
    return grid_distance(tuple(source_cells), tuple(target_cells)).feet <= attack.reach_feet


def validate_attack_target(
    *,
    source_cells: tuple[GridCell, ...],
    target_cells: tuple[GridCell, ...],
    attack: ResolvedAttack,
    barriers: tuple[BarrierView, ...],
    audience: Audience,
) -> SpatialTargetingResult:
    """P5-C attack spatial validation. Pure: no dice, no DB."""
    distance = grid_distance(source_cells, target_cells)
    feet = distance.feet
    within_5ft = feet <= 5
    is_melee = attack.attack_kind is AttackKind.MELEE
    requires_dm_adjudication = False
    legal_band = False
    if is_melee:
        if attack.reach_feet is None:
            range_band = "unknown"
            requires_dm_adjudication = True
        elif feet <= attack.reach_feet:
            range_band = "reach"
            legal_band = True
        elif (
            attack.range_normal_feet is not None
            and feet <= (attack.range_long_feet or attack.range_normal_feet)
        ):
            # Thrown melee weapon used at range.
            range_band = "normal" if feet <= attack.range_normal_feet else "long"
            legal_band = True
        else:
            range_band = "out_of_range"
    elif attack.range_normal_feet is None:
        range_band = "out_of_range"
        requires_dm_adjudication = True
    elif feet <= attack.range_normal_feet:
        range_band = "normal"
        legal_band = True
    elif attack.range_long_feet is not None and feet <= attack.range_long_feet:
        range_band = "long"
        legal_band = True
    else:
        range_band = "out_of_range"
    blocker = is_target_blocked(source_cells, target_cells, barriers) if legal_band else None
    blocked = blocker is not None
    return SpatialTargetingResult(
        legal=legal_band and not blocked,
        distance_feet=feet,
        range_band=range_band,
        blocked=blocked,
        blocker_kind=public_blocker_kind(blocker.kind, audience=audience) if blocker else None,
        requires_dm_adjudication=requires_dm_adjudication,
        is_long_range=range_band == "long",
        target_within_5ft=within_5ft,
    )


def validate_spell_target(
    *,
    source_cells: tuple[GridCell, ...],
    target_cells: tuple[GridCell, ...],
    range_feet: int,
    barriers: tuple[BarrierView, ...],
    audience: Audience,
) -> SpatialTargetingResult:
    """P5-C targeted-spell spatial validation (non-AoE). Pure: no dice, no DB."""
    distance = grid_distance(source_cells, target_cells)
    feet = distance.feet
    legal_band = feet <= range_feet
    blocker = is_target_blocked(source_cells, target_cells, barriers) if legal_band else None
    blocked = blocker is not None
    return SpatialTargetingResult(
        legal=legal_band and not blocked,
        distance_feet=feet,
        range_band="normal" if legal_band else "out_of_range",
        blocked=blocked,
        blocker_kind=public_blocker_kind(blocker.kind, audience=audience) if blocker else None,
        requires_dm_adjudication=False,
        is_long_range=False,
        target_within_5ft=feet <= 5,
    )


_SPELL_RANGE_FEET_RE = re.compile(r"^\s*(\d+)\s*feet\s*$", re.IGNORECASE)
_SPELL_RANGE_MILE_RE = re.compile(r"^\s*(\d+)\s*miles?\s*$", re.IGNORECASE)

SpellRangeSpec = tuple[str, int | None]
"""(kind, feet): kind in "self" | "touch" | "feet" | "unknown". Touch is 5 ft."""


def parse_spell_range(range_text: str | None) -> SpellRangeSpec:
    """Parse SRD spell range text into a spatial spec. Unknowns stay DM-adjudicated."""
    if not isinstance(range_text, str):
        return "unknown", None
    folded = range_text.strip().casefold()
    if folded == "self":
        return "self", 0
    if folded == "touch":
        return "touch", 5
    match = _SPELL_RANGE_FEET_RE.match(range_text)
    if match:
        return "feet", int(match.group(1))
    match = _SPELL_RANGE_MILE_RE.match(range_text)
    if match:
        return "feet", int(match.group(1)) * 5280
    return "unknown", None


__all__ = [
    "Audience",
    "BarrierView",
    "BlockerKind",
    "CombatTargetBlockedError",
    "CombatTargetOutOfRangeError",
    "SpatialTargetingResult",
    "SpellRangeSpec",
    "is_target_blocked",
    "is_within_reach",
    "parse_spell_range",
    "public_blocker_kind",
    "validate_attack_target",
    "validate_spell_target",
]
