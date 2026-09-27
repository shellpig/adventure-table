"""Grid pathing: distance, step cost, barrier crossing, and path validation (P5-B).

Pure functions over the square grid; no DB access. Built on
``app.domain.spatial.primitives`` so movement, range, reach, and AoE share one
diagonal/footprint implementation. One cell is always 5 ft (spec 4.1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.spatial.primitives import (
    BarrierSegment,
    Footprint,
    GridCell,
    _overlaps_positive,
    footprint_straddles_barrier,
    intersects_blocked_cell,
    is_inside_bounds,
    occupied_cells,
)

FEET_PER_CELL = 5


@dataclass(frozen=True)
class GridPath:
    """Authoritative movement path: adjacent anchor cells, start included."""

    anchors: tuple[GridCell, ...]


@dataclass(frozen=True)
class DistanceResult:
    """5/10-alternating grid distance between two occupied-cell sets."""

    feet: int
    diagonal_steps: int


def _alternating_diagonal_cost(diagonals: int) -> int:
    # 1 diagonal = 5 ft, 2 = 15 ft, 3 = 20 ft, 4 = 30 ft, ...
    return FEET_PER_CELL * diagonals + FEET_PER_CELL * (diagonals // 2)


def cell_distance(from_cell: GridCell, to_cell: GridCell) -> DistanceResult:
    """5/10-alternating distance between two cells (sequence restarts here)."""
    dx = abs(from_cell.x - to_cell.x)
    dy = abs(from_cell.y - to_cell.y)
    diagonals = min(dx, dy)
    orthogonal = max(dx, dy) - diagonals
    return DistanceResult(
        feet=orthogonal * FEET_PER_CELL + _alternating_diagonal_cost(diagonals),
        diagonal_steps=diagonals,
    )


def vertex_cell_distance(vertex: tuple[int, int], cell: GridCell) -> DistanceResult:
    """5/10-alternating distance from an integer grid vertex to a cell center.

    The axial step counts are ``ceil(|delta|)`` of the vertex-to-center offsets,
    then the shared 5/10 alternating rule applies (P5-D D1 AoE geometry).
    """
    ox, oy = vertex
    steps_x = math.ceil(abs((cell.x + 0.5) - ox))
    steps_y = math.ceil(abs((cell.y + 0.5) - oy))
    diagonals = min(steps_x, steps_y)
    orthogonal = max(steps_x, steps_y) - diagonals
    return DistanceResult(
        feet=orthogonal * FEET_PER_CELL + _alternating_diagonal_cost(diagonals),
        diagonal_steps=diagonals,
    )


def grid_distance(
    from_cells: tuple[GridCell, ...] | frozenset[GridCell],
    to_cells: tuple[GridCell, ...] | frozenset[GridCell],
) -> DistanceResult:
    """Minimum 5/10-alternating distance over two occupied-cell sets.

    General distance queries recompute the diagonal sequence from the
    measurement start; they never consume turn movement parity (design 4.1).
    """
    best: DistanceResult | None = None
    for start in from_cells:
        for end in to_cells:
            candidate = cell_distance(start, end)
            if best is None or candidate.feet < best.feet:
                best = candidate
    if best is None:
        raise ValueError("grid_distance requires non-empty cell sets")
    return best


def step_cost(*, diagonal: bool, diagonal_steps_used: int, difficult: bool) -> int:
    """Cost of one 5 ft step.

    Diagonal steps alternate 5/10 by the turn's diagonal parity: the first
    diagonal of the turn costs 5, the second 10, and so on. Difficult terrain
    (including another creature's space) doubles the step cost.
    """
    if diagonal_steps_used < 0:
        raise ValueError("diagonal_steps_used cannot be negative")
    cost = FEET_PER_CELL
    if diagonal and diagonal_steps_used % 2 == 1:
        cost = 2 * FEET_PER_CELL
    return cost * 2 if difficult else cost


def _edge_blocked(
    x1: int, y1: int, x2: int, y2: int, barriers: tuple[BarrierSegment, ...]
) -> bool:
    """True when a barrier overlaps the grid edge between two vertices."""
    for barrier in barriers:
        if barrier.x1 == barrier.x2 and x1 == x2 and barrier.x1 == x1:
            lo, hi = sorted((barrier.y1, barrier.y2))
            if _overlaps_positive(lo, hi, min(y1, y2), max(y1, y2)):
                return True
        elif barrier.y1 == barrier.y2 and y1 == y2 and barrier.y1 == y1:
            lo, hi = sorted((barrier.x1, barrier.x2))
            if _overlaps_positive(lo, hi, min(x1, x2), max(x1, x2)):
                return True
    return False


def crosses_wall_or_closed_door(
    from_cell: GridCell,
    to_cell: GridCell,
    barriers: tuple[BarrierSegment, ...],
    blocked_cells: frozenset[GridCell],
) -> bool:
    """True when the step crosses a wall/closed-door edge.

    A diagonal step may not cut the corner: it is blocked when either
    orthogonal sub-step crosses a barrier or either corner cell is blocked
    terrain.
    """
    dx = to_cell.x - from_cell.x
    dy = to_cell.y - from_cell.y
    if dx != 0 and dy == 0:
        edge_x = from_cell.x + 1 if dx > 0 else from_cell.x
        return _edge_blocked(edge_x, from_cell.y, edge_x, from_cell.y + 1, barriers)
    if dy != 0 and dx == 0:
        edge_y = from_cell.y + 1 if dy > 0 else from_cell.y
        return _edge_blocked(from_cell.x, edge_y, from_cell.x + 1, edge_y, barriers)
    if abs(dx) == 1 and abs(dy) == 1:
        step_x = 1 if dx > 0 else -1
        step_y = 1 if dy > 0 else -1
        if GridCell(from_cell.x + step_x, from_cell.y) in blocked_cells:
            return True
        if GridCell(from_cell.x, from_cell.y + step_y) in blocked_cells:
            return True
        if crosses_wall_or_closed_door(
            from_cell, GridCell(from_cell.x + step_x, from_cell.y), barriers, blocked_cells
        ):
            return True
        return crosses_wall_or_closed_door(
            from_cell, GridCell(from_cell.x, from_cell.y + step_y), barriers, blocked_cells
        )
    raise ValueError(f"non-adjacent step: {from_cell} -> {to_cell}")


@dataclass(frozen=True)
class PathCreature:
    """Another combatant's occupied space for creature-space rules."""

    cells: frozenset[GridCell]
    hostile_to_mover: bool
    size_rank: int


@dataclass(frozen=True)
class PathValidationRequest:
    start: GridCell
    anchors: tuple[GridCell, ...]
    footprint: Footprint
    mover_size_rank: int
    width_cells: int
    height_cells: int
    blocked_cells: frozenset[GridCell]
    difficult_cells: frozenset[GridCell]
    barriers: tuple[BarrierSegment, ...]
    creatures: tuple[PathCreature, ...]
    budget_feet: int
    diagonal_steps_used: int


@dataclass(frozen=True)
class PathStep:
    anchor: GridCell
    cost_feet: int
    difficult: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PathValidationResult:
    valid: bool
    steps: tuple[PathStep, ...]
    used_feet: int
    diagonal_steps: int
    failure: str | None
    failure_step_index: int | None


def validate_movement_path(request: PathValidationRequest) -> PathValidationResult:
    """Step-by-step movement legality against a board snapshot.

    Checks adjacency, bounds, blocked terrain, wall/closed-door edges
    (including diagonal corner cutting), the full footprint sweep, D&D 2014
    creature-space rules, and the remaining turn budget. Pure: no DB access.
    """

    def invalid(reason: str, index: int | None) -> PathValidationResult:
        return PathValidationResult(
            valid=False, steps=(), used_feet=0, diagonal_steps=0,
            failure=reason, failure_step_index=index,
        )

    anchors = request.anchors
    if len(anchors) < 2:
        return invalid("empty_path", None)
    if anchors[0] != request.start:
        return invalid("path_start_mismatch", 0)

    steps: list[PathStep] = []
    used_feet = 0
    diagonal_parity = request.diagonal_steps_used
    new_diagonals = 0
    last_index = len(anchors) - 1

    for index in range(1, len(anchors)):
        previous = anchors[index - 1]
        current = anchors[index]
        dx = current.x - previous.x
        dy = current.y - previous.y
        if (dx, dy) == (0, 0) or max(abs(dx), abs(dy)) != 1:
            return invalid("not_adjacent", index)
        diagonal = dx != 0 and dy != 0

        cells = occupied_cells(current.x, current.y, request.footprint)
        if not is_inside_bounds(cells, request.width_cells, request.height_cells):
            return invalid("out_of_bounds", index)
        if intersects_blocked_cell(cells, request.blocked_cells):
            return invalid("blocked_terrain", index)
        if footprint_straddles_barrier(
            current.x, current.y, request.footprint, request.barriers
        ):
            return invalid("wall_or_door", index)
        if diagonal:
            # Corner cutting is checked for every cell of the footprint, not
            # just the anchor: a Large mover stepping (0,0)->(1,1) sweeps its
            # leading-edge corners (2,0) and (0,2) as well.
            for cell in occupied_cells(previous.x, previous.y, request.footprint):
                if crosses_wall_or_closed_door(
                    cell, GridCell(cell.x + dx, cell.y + dy),
                    request.barriers, request.blocked_cells,
                ):
                    return invalid("wall_or_door", index)
        elif crosses_wall_or_closed_door(
            previous, current, request.barriers, request.blocked_cells
        ):
            return invalid("wall_or_door", index)

        difficult = any(cell in request.difficult_cells for cell in cells)
        warnings: list[str] = []
        if difficult:
            warnings.append("difficult_terrain")
        occupied = set(cells)
        for creature in request.creatures:
            if occupied.isdisjoint(creature.cells):
                continue
            if index == last_index:
                return invalid("end_on_occupied", index)
            if creature.hostile_to_mover and abs(creature.size_rank - request.mover_size_rank) < 2:
                return invalid("creature_blocked", index)
            if "creature_space" not in warnings:
                warnings.append("creature_space")
            difficult = True

        cost = step_cost(
            diagonal=diagonal, diagonal_steps_used=diagonal_parity, difficult=difficult
        )
        if diagonal:
            diagonal_parity += 1
            new_diagonals += 1
        used_feet += cost
        if used_feet > request.budget_feet:
            return invalid("budget_exceeded", index)
        steps.append(PathStep(
            anchor=current, cost_feet=cost, difficult=difficult,
            warnings=tuple(warnings),
        ))

    return PathValidationResult(
        valid=True, steps=tuple(steps), used_feet=used_feet,
        diagonal_steps=new_diagonals, failure=None, failure_step_index=None,
    )


__all__ = [
    "FEET_PER_CELL",
    "DistanceResult",
    "GridPath",
    "PathCreature",
    "PathStep",
    "PathValidationRequest",
    "PathValidationResult",
    "cell_distance",
    "crosses_wall_or_closed_door",
    "grid_distance",
    "step_cost",
    "validate_movement_path",
]
