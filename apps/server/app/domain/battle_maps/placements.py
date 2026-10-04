"""M07-C map monster placement validation (C1).

Pure functions shared by the library placement editor (``BattleMapService``)
and the atomic Tactical load (C2). No DB access: callers resolve template
sizes and map geometry, then run :func:`validate_monster_placements` over the
whole batch. Every problem is reported (placement id + code); validation never
stops at the first failure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.domain.spatial.primitives import (
    BarrierSegment,
    Footprint,
    GridCell,
    footprint_for_size,
    footprint_straddles_barrier,
    intersects_blocked_cell,
    is_inside_bounds,
    occupied_cells,
)

if TYPE_CHECKING:
    from app.domain.combat.resolution import SizeCategory
    from app.persistence.battle_maps.repository import (
        StoredBattleMapDoor,
        StoredBattleMapTerrain,
        StoredBattleMapWall,
    )

# Problem codes returned by the batch validator. ``template_archived`` and
# ``invalid_size`` are source problems attached by the service; the geometry
# codes come from this module's pure check.
PLACEMENT_PROBLEM_OUT_OF_BOUNDS = "out_of_bounds"
PLACEMENT_PROBLEM_BLOCKED_TERRAIN = "blocked_terrain"
PLACEMENT_PROBLEM_WALL_OR_DOOR_BLOCKED = "wall_or_door_blocked"
PLACEMENT_PROBLEM_OVERLAPPING = "overlapping_placement"
PLACEMENT_PROBLEM_TEMPLATE_ARCHIVED = "template_archived"
PLACEMENT_PROBLEM_INVALID_SIZE = "invalid_size"


@dataclass(frozen=True)
class PlacementValidationEntry:
    """One placement with its template size already resolved."""

    placement_id: UUID
    size: SizeCategory
    anchor_x: int
    anchor_y: int


@dataclass(frozen=True)
class PlacementProblem:
    placement_id: UUID
    code: str


def resolve_placement_size(raw_size: object) -> SizeCategory | None:
    """Resolve a template ``size`` value to a SizeCategory.

    A missing/blank size falls back to Medium, mirroring
    ``app.domain.combat.sizes.resolve_entry_size`` (Quick enemies and legacy
    instances without a recorded size place as Medium rather than failing the
    whole batch). Returns None when the value is present but unparseable; the
    caller reports an ``invalid_size`` problem for that placement.
    """
    # Imported lazily: app.domain.combat.resolution is a heavy combat module,
    # and this validator must stay importable from battle-map-only contexts.
    from app.domain.combat.resolution import SizeCategory

    if raw_size is None:
        return SizeCategory.MEDIUM
    if isinstance(raw_size, str):
        if not raw_size.strip():
            return SizeCategory.MEDIUM
        try:
            return SizeCategory[raw_size.strip().upper().replace(" ", "_")]
        except KeyError:
            return None
    return None


def barriers_from_map_objects(
    walls: Sequence[StoredBattleMapWall],
    doors: Sequence[StoredBattleMapDoor],
) -> tuple[BarrierSegment, ...]:
    """Walls plus non-open doors as placement barriers.

    Mirrors ``CombatBoardService._barriers``: every wall blocks, and any door
    whose default state is not ``open`` blocks (hidden doors included).
    """
    barriers = [
        BarrierSegment(x1=wall.x1, y1=wall.y1, x2=wall.x2, y2=wall.y2)
        for wall in walls
    ]
    barriers.extend(
        BarrierSegment(x1=door.x1, y1=door.y1, x2=door.x2, y2=door.y2)
        for door in doors
        if door.default_state != "open"
    )
    return tuple(barriers)


def blocked_cells_from_terrain(
    terrain: Sequence[StoredBattleMapTerrain],
) -> frozenset[GridCell]:
    return frozenset(
        GridCell(x=cell.x, y=cell.y)
        for cell in terrain
        if cell.terrain_kind == "blocked"
    )


def validate_monster_placements(
    entries: Sequence[PlacementValidationEntry],
    *,
    width_cells: int,
    height_cells: int,
    barriers: Sequence[BarrierSegment],
    blocked_cells: frozenset[GridCell],
) -> list[PlacementProblem]:
    """Validate a whole placement batch against one map geometry.

    Checks every entry for out-of-bounds footprints, blocked terrain, walls /
    non-open doors cutting through the footprint interior, and pairwise batch
    overlap. Returns one problem per (placement, code); a placement may carry
    several problems and validation continues past the first failure.
    """
    problems: list[PlacementProblem] = []
    footprints: dict[UUID, Footprint] = {}
    cells: dict[UUID, tuple[GridCell, ...]] = {}
    for entry in entries:
        footprint = footprint_for_size(entry.size)
        footprints[entry.placement_id] = footprint
        occupied = occupied_cells(entry.anchor_x, entry.anchor_y, footprint)
        cells[entry.placement_id] = occupied
        if not is_inside_bounds(occupied, width_cells, height_cells):
            problems.append(
                PlacementProblem(
                    placement_id=entry.placement_id,
                    code=PLACEMENT_PROBLEM_OUT_OF_BOUNDS,
                )
            )
        if intersects_blocked_cell(occupied, blocked_cells):
            problems.append(
                PlacementProblem(
                    placement_id=entry.placement_id,
                    code=PLACEMENT_PROBLEM_BLOCKED_TERRAIN,
                )
            )
        if footprint_straddles_barrier(
            entry.anchor_x, entry.anchor_y, footprint, barriers
        ):
            problems.append(
                PlacementProblem(
                    placement_id=entry.placement_id,
                    code=PLACEMENT_PROBLEM_WALL_OR_DOOR_BLOCKED,
                )
            )
    for index, first in enumerate(entries):
        first_cells = set(cells[first.placement_id])
        for second in entries[index + 1 :]:
            if first_cells & set(cells[second.placement_id]):
                problems.append(
                    PlacementProblem(
                        placement_id=first.placement_id,
                        code=PLACEMENT_PROBLEM_OVERLAPPING,
                    )
                )
                problems.append(
                    PlacementProblem(
                        placement_id=second.placement_id,
                        code=PLACEMENT_PROBLEM_OVERLAPPING,
                    )
                )
    return problems


__all__ = [
    "PLACEMENT_PROBLEM_BLOCKED_TERRAIN",
    "PLACEMENT_PROBLEM_INVALID_SIZE",
    "PLACEMENT_PROBLEM_OUT_OF_BOUNDS",
    "PLACEMENT_PROBLEM_OVERLAPPING",
    "PLACEMENT_PROBLEM_TEMPLATE_ARCHIVED",
    "PLACEMENT_PROBLEM_WALL_OR_DOOR_BLOCKED",
    "PlacementProblem",
    "PlacementValidationEntry",
    "barriers_from_map_objects",
    "blocked_cells_from_terrain",
    "resolve_placement_size",
    "validate_monster_placements",
]
