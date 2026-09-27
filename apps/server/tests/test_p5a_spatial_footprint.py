"""P5-A B1: spatial primitives — size footprints, occupancy, bounds, barriers."""

from __future__ import annotations

import pytest

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


@pytest.mark.parametrize(
    ("size_name", "width", "height"),
    [
        ("tiny", 1, 1),
        ("small", 1, 1),
        ("medium", 1, 1),
        ("large", 2, 2),
        ("huge", 3, 3),
        ("gargantuan", 4, 4),
        # Case/whitespace tolerant.
        ("Medium", 1, 1),
        ("  LARGE  ", 2, 2),
    ],
)
def test_size_to_footprint_table(size_name: str, width: int, height: int) -> None:
    footprint = footprint_for_size_name(size_name)
    assert (footprint.width, footprint.height) == (width, height)


def test_size_footprint_covers_all_entries() -> None:
    assert set(SIZE_FOOTPRINT) == {
        "tiny", "small", "medium", "large", "huge", "gargantuan",
    }


def test_footprint_for_size_name_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unsupported creature size"):
        footprint_for_size_name("colossal")


def test_footprint_for_size_enum_matches_name_lookup() -> None:
    from app.domain.combat.sizes import SizeCategory

    for member in SizeCategory:
        assert footprint_for_size(member) == footprint_for_size_name(member.name)


def test_occupied_cells_1x1_and_2x2() -> None:
    assert occupied_cells(3, 4, Footprint(1, 1)) == (GridCell(3, 4),)
    assert occupied_cells(0, 0, Footprint(2, 2)) == (
        GridCell(0, 0), GridCell(1, 0), GridCell(0, 1), GridCell(1, 1),
    )


def test_is_inside_bounds_edges() -> None:
    assert is_inside_bounds(occupied_cells(0, 0, Footprint(1, 1)), 10, 10)
    assert is_inside_bounds(occupied_cells(9, 9, Footprint(1, 1)), 10, 10)
    # 2x2 anchored at the last cell overflows.
    assert not is_inside_bounds(occupied_cells(9, 9, Footprint(2, 2)), 10, 10)
    assert is_inside_bounds(occupied_cells(8, 8, Footprint(2, 2)), 10, 10)
    assert not is_inside_bounds(occupied_cells(-1, 0, Footprint(1, 1)), 10, 10)


def test_intersects_blocked_cell() -> None:
    blocked = frozenset({GridCell(2, 2)})
    assert intersects_blocked_cell(occupied_cells(2, 2, Footprint(1, 1)), blocked)
    assert intersects_blocked_cell(occupied_cells(1, 1, Footprint(2, 2)), blocked)
    assert not intersects_blocked_cell(occupied_cells(0, 0, Footprint(2, 2)), blocked)


def test_barrier_on_boundary_is_allowed() -> None:
    # A wall along the footprint's outer edge: standing next to it is legal.
    footprint = Footprint(2, 2)
    assert not footprint_straddles_barrier(
        0, 0, footprint, [BarrierSegment(0, 0, 0, 2)]
    )
    assert not footprint_straddles_barrier(
        0, 0, footprint, [BarrierSegment(0, 2, 2, 2)]
    )


def test_barrier_through_interior_blocks() -> None:
    footprint = Footprint(2, 2)
    # Vertical wall at x=1 cuts between the two columns.
    assert footprint_straddles_barrier(
        0, 0, footprint, [BarrierSegment(1, 0, 1, 2)]
    )
    # Horizontal wall at y=1 cuts between the two rows.
    assert footprint_straddles_barrier(
        0, 0, footprint, [BarrierSegment(0, 1, 2, 1)]
    )


def test_barrier_touching_at_corner_is_allowed() -> None:
    footprint = Footprint(2, 2)
    # Zero-length overlap with the interior edge range: only touches the corner.
    assert not footprint_straddles_barrier(
        0, 0, footprint, [BarrierSegment(1, 2, 1, 4)]
    )


def test_can_occupy_happy_path() -> None:
    assert can_occupy(
        1, 1, Footprint(1, 1),
        width_cells=10, height_cells=10,
        blocked_cells=frozenset(),
        barriers=[],
        occupied_by_others=frozenset(),
    )


@pytest.mark.parametrize("anchor", [(9, 9), (-1, 0), (0, -1)])
def test_can_occupy_rejects_out_of_bounds(anchor: tuple[int, int]) -> None:
    assert not can_occupy(
        anchor[0], anchor[1], Footprint(2, 2),
        width_cells=10, height_cells=10,
        blocked_cells=frozenset(),
        barriers=[],
        occupied_by_others=frozenset(),
    )


def test_can_occupy_rejects_blocked_and_overlap_and_barrier() -> None:
    footprint = Footprint(2, 2)
    kwargs = dict(width_cells=10, height_cells=10)
    assert not can_occupy(
        0, 0, footprint, **kwargs,
        blocked_cells=frozenset({GridCell(1, 1)}),
        barriers=[], occupied_by_others=frozenset(),
    )
    assert not can_occupy(
        0, 0, footprint, **kwargs,
        blocked_cells=frozenset(),
        barriers=[], occupied_by_others=frozenset({GridCell(0, 1)}),
    )
    assert not can_occupy(
        0, 0, footprint, **kwargs,
        blocked_cells=frozenset(),
        barriers=[BarrierSegment(1, 0, 1, 2)],
        occupied_by_others=frozenset(),
    )
