"""Shared spatial primitives (P5-A).

Pure functions over the square grid; no DB access. Movement, range, reach and
AoE must all build on these so diagonal/footprint semantics cannot drift.
P5-A only needs footprint / bounds / occupancy; distance and path arrive in
later steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from app.domain.combat.resolution import SizeCategory


@dataclass(frozen=True)
class GridCell:
    """One square-grid cell. Cell (x, y) covers [x, x+1) x [y, y+1)."""

    x: int
    y: int


@dataclass(frozen=True)
class Footprint:
    """Creature space in cells. Anchor is the top-left occupied cell."""

    width: int
    height: int


@dataclass(frozen=True)
class BarrierSegment:
    """Axis-aligned segment on grid vertices (wall or non-open door)."""

    x1: int
    y1: int
    x2: int
    y2: int


# Spec 4.2: fixed first-edition footprints. Keyed by lowercase size name so this
# module stays free of combat imports at runtime.
SIZE_FOOTPRINT: dict[str, Footprint] = {
    "tiny": Footprint(1, 1),
    "small": Footprint(1, 1),
    "medium": Footprint(1, 1),
    "large": Footprint(2, 2),
    "huge": Footprint(3, 3),
    "gargantuan": Footprint(4, 4),
}


def footprint_for_size_name(name: str) -> Footprint:
    try:
        return SIZE_FOOTPRINT[name.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported creature size: {name!r}") from exc


def footprint_for_size(size: SizeCategory) -> Footprint:
    """Footprint for a SizeCategory enum member (uses its member name)."""
    return footprint_for_size_name(size.name)


def occupied_cells(
    anchor_x: int, anchor_y: int, footprint: Footprint
) -> tuple[GridCell, ...]:
    return tuple(
        GridCell(x=anchor_x + dx, y=anchor_y + dy)
        for dy in range(footprint.height)
        for dx in range(footprint.width)
    )


def is_inside_bounds(
    cells: Iterable[GridCell], width_cells: int, height_cells: int
) -> bool:
    return all(
        0 <= cell.x < width_cells and 0 <= cell.y < height_cells for cell in cells
    )


def intersects_blocked_cell(
    cells: Iterable[GridCell], blocked_cells: frozenset[GridCell]
) -> bool:
    return any(cell in blocked_cells for cell in cells)


def _overlaps_positive(lo_a: int, hi_a: int, lo_b: int, hi_b: int) -> bool:
    return max(lo_a, lo_b) < min(hi_a, hi_b)


def footprint_straddles_barrier(
    anchor_x: int,
    anchor_y: int,
    footprint: Footprint,
    barriers: Iterable[BarrierSegment],
) -> bool:
    """True when a barrier runs along an *interior* edge of the footprint.

    Walls on the footprint boundary are fine (a creature may stand next to a
    wall); only a barrier cutting between two occupied cells blocks placement.
    Non-axis-aligned segments are ignored (map validation rejects them).
    """
    # Interior grid lines of the footprint bounding box.
    vertical_edges = tuple(
        (anchor_x + dx, anchor_y, anchor_y + footprint.height)
        for dx in range(1, footprint.width)
    )
    horizontal_edges = tuple(
        (anchor_y + dy, anchor_x, anchor_x + footprint.width)
        for dy in range(1, footprint.height)
    )
    for barrier in barriers:
        if barrier.x1 == barrier.x2 and barrier.y1 != barrier.y2:
            bx = barrier.x1
            lo, hi = sorted((barrier.y1, barrier.y2))
            for ex, elo, ehi in vertical_edges:
                if bx == ex and _overlaps_positive(lo, hi, elo, ehi):
                    return True
        elif barrier.y1 == barrier.y2 and barrier.x1 != barrier.x2:
            by = barrier.y1
            lo, hi = sorted((barrier.x1, barrier.x2))
            for ey, elo, ehi in horizontal_edges:
                if by == ey and _overlaps_positive(lo, hi, elo, ehi):
                    return True
    return False


def can_occupy(
    anchor_x: int,
    anchor_y: int,
    footprint: Footprint,
    *,
    width_cells: int,
    height_cells: int,
    blocked_cells: frozenset[GridCell],
    barriers: Iterable[BarrierSegment],
    occupied_by_others: frozenset[GridCell],
) -> bool:
    """Full placement legality check for one footprint anchor."""
    cells = occupied_cells(anchor_x, anchor_y, footprint)
    return (
        is_inside_bounds(cells, width_cells, height_cells)
        and not intersects_blocked_cell(cells, blocked_cells)
        and not footprint_straddles_barrier(anchor_x, anchor_y, footprint, barriers)
        and not any(cell in occupied_by_others for cell in cells)
    )


__all__ = [
    "BarrierSegment",
    "Footprint",
    "GridCell",
    "SIZE_FOOTPRINT",
    "can_occupy",
    "footprint_for_size",
    "footprint_for_size_name",
    "footprint_straddles_barrier",
    "intersects_blocked_cell",
    "is_inside_bounds",
    "occupied_cells",
]
