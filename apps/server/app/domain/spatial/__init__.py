"""Shared spatial primitives: grid cells, footprints, occupancy checks."""

from app.domain.spatial.primitives import (
    BarrierSegment,
    Footprint,
    GridCell,
    SIZE_FOOTPRINT,
    can_occupy,
    footprint_for_size,
    footprint_for_size_name,
    footprint_straddles_barrier,
    intersects_blocked_cell,
    is_inside_bounds,
    occupied_cells,
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
