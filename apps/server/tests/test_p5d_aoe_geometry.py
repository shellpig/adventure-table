"""P5-D D1: AoE geometry golden fixture + normalization + boundary semantics.

Covers 測試指南 D.1-D.3 (backend only, no DB):
- D.1 AoE 幾何純函數；shape normalize 讀 spell content ``data.area_of_effect``
  （sphere/cylinder→circle、cube→square、cone→cone、line→line）；golden fixture
  round-trip（P5-F renderer 會重用此 fixture）
- D.2 邊界全部 ``<=``：半徑／長度邊界、cone 楔形邊界、line 半寬邊界、奇偶尺寸
- D.3 多格 creature 任一 occupied cell 即 candidate；affected cells 限 board bounds；
  origin 必須是整數 grid vertex
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.spatial.aoe import (
    AoeCombatant,
    affected_cells,
    cell_in_template,
    make_aoe_template,
    normalize_area_of_effect,
    resolve_aoe_candidates,
)
from app.domain.spatial.pathing import vertex_cell_distance
from app.domain.spatial.primitives import GridCell

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "p5d_aoe_golden.json"


def _load_cases() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())["cases"]


def test_golden_fixture_round_trip() -> None:
    """Every golden case reproduces its recorded affected cells exactly."""
    cases = _load_cases()
    assert len(cases) >= 7
    kinds = {case["shape"]["kind"] for case in cases}
    assert {"circle", "square", "cone", "line"} <= kinds
    for case in cases:
        shape = case["shape"]
        template = make_aoe_template(
            shape["kind"],
            shape["size_feet"],
            origin_x=shape["origin"][0],
            origin_y=shape["origin"][1],
            aim=tuple(shape["aim"]) if shape["aim"] else None,
            direction=shape["direction"],
        )
        cells = affected_cells(
            template,
            width_cells=case["board"]["width_cells"],
            height_cells=case["board"]["height_cells"],
        )
        assert [[cell.x, cell.y] for cell in cells] == case["affected_cells"], (
            f"golden mismatch: {case['name']}"
        )


@pytest.mark.parametrize(
    ("raw_type", "size", "kind", "size_feet"),
    [
        ("sphere", 20, "circle", 20),
        ("cylinder", 10, "circle", 10),
        ("cube", 15, "square", 15),
        ("cone", 15, "cone", 15),
        ("line", 100, "line", 100),
        ("Sphere", 20, "circle", 20),  # case-insensitive
    ],
)
def test_normalize_area_of_effect(
    raw_type: str, size: int, kind: str, size_feet: int
) -> None:
    assert normalize_area_of_effect({"type": raw_type, "size": size}) == (
        kind,
        size_feet,
    )


@pytest.mark.parametrize(
    "area",
    [
        {"type": "burst", "size": 20},  # unknown type
        {"type": "sphere", "size": 0},  # non-positive
        {"type": "sphere", "size": -5},
        {"type": "sphere", "size": 2.5},  # non-integer
        {"type": "sphere"},  # missing size
        {"size": 20},  # missing type
        "sphere",  # not a mapping
    ],
)
def test_normalize_area_of_effect_rejects_bad_input(area: object) -> None:
    with pytest.raises(ValueError):
        normalize_area_of_effect(area)  # type: ignore[arg-type]


def test_make_aoe_template_validates_placement() -> None:
    with pytest.raises(ValueError):
        make_aoe_template("circle", 20, origin_x=10.5, origin_y=10)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        make_aoe_template("circle", 20, origin_x=10, origin_y=10, aim=(11, 10))
    with pytest.raises(ValueError):
        make_aoe_template("square", 15, origin_x=5, origin_y=5)  # missing direction
    with pytest.raises(ValueError):
        make_aoe_template("cone", 15, origin_x=5, origin_y=5)  # missing aim
    with pytest.raises(ValueError):
        make_aoe_template("line", 30, origin_x=5, origin_y=5, aim=(5, 5))  # aim == origin


def test_vertex_cell_distance_shared_diagonal_cost() -> None:
    # Cell (0,0) center (0.5, 0.5): one diagonal step -> 5 ft.
    assert vertex_cell_distance((0, 0), GridCell(x=0, y=0)).feet == 5
    # Cell (1,1) center (1.5, 1.5): two diagonal steps -> 5 + 10 = 15 ft.
    assert vertex_cell_distance((0, 0), GridCell(x=1, y=1)).feet == 15
    # Cell (2,0) center (2.5, 0.5): 1 diagonal + 2 orthogonal -> 5 + 10 = 15 ft.
    assert vertex_cell_distance((0, 0), GridCell(x=2, y=0)).feet == 15


def test_circle_radius_boundary_inclusive() -> None:
    template = make_aoe_template("circle", 20, origin_x=10, origin_y=10)
    # Cell (13,10): center (13.5, 10.5), steps (4,1) -> 15 + 5 = 20 ft, on boundary.
    assert cell_in_template(template, 13, 10)
    # Cell (14,10): center (14.5, 10.5), steps (5,1) -> 20 + 5 = 25 ft, outside.
    assert not cell_in_template(template, 14, 10)


def test_circle_odd_radius_boundary() -> None:
    template = make_aoe_template("circle", 15, origin_x=10, origin_y=10)
    # Cell (12,10): center (12.5, 10.5), steps (3,1) -> 10 + 5 = 15 ft, on boundary.
    assert cell_in_template(template, 12, 10)
    # Cell (13,10): 20 ft, outside.
    assert not cell_in_template(template, 13, 10)


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ("se", {(10, 10), (11, 10), (10, 11), (11, 11)}),
        ("nw", {(8, 8), (9, 8), (8, 9), (9, 9)}),
        ("ne", {(10, 8), (11, 8), (10, 9), (11, 9)}),
        ("sw", {(8, 10), (9, 10), (8, 11), (9, 11)}),
    ],
)
def test_square_quadrants(direction: str, expected: set[tuple[int, int]]) -> None:
    # 10 ft side = 2 cells; origin (10,10) is the square's corner.
    template = make_aoe_template(
        "square", 10, origin_x=10, origin_y=10, direction=direction  # type: ignore[arg-type]
    )
    got = {
        (cell.x, cell.y)
        for cell in affected_cells(template, width_cells=30, height_cells=30)
    }
    assert got == expected


def test_square_side_uses_feet_not_cells() -> None:
    # 15 ft side = 3x3 cells, not 15x15.
    template = make_aoe_template(
        "square", 15, origin_x=5, origin_y=15, direction="ne"
    )
    cells = affected_cells(template, width_cells=30, height_cells=20)
    assert len(cells) == 9


def test_cone_wedge_boundary() -> None:
    # Aim east from (0,0); wedge is axis +/- atan(1/2): 2*cross <= dot.
    template = make_aoe_template("cone", 40, origin_x=0, origin_y=0, aim=(1, 0))
    # Cell (5,2): center (5.5, 2.5): dot=5.5, 2*cross=5.0 -> inside wedge.
    assert cell_in_template(template, 5, 2)
    # Cell (4,2): center (4.5, 2.5): dot=4.5, 2*cross=5.0 -> outside wedge.
    assert not cell_in_template(template, 4, 2)
    # Behind the apex is never inside.
    assert not cell_in_template(template, -1, 0)


def test_cone_length_boundary() -> None:
    template = make_aoe_template("cone", 15, origin_x=5, origin_y=5, aim=(6, 5))
    # Straight ahead, cell (7,5): center (7.5, 5.5), steps (3,1) -> 15 ft, on boundary.
    assert cell_in_template(template, 7, 5)
    # Cell (8,5): 20 ft, beyond length.
    assert not cell_in_template(template, 8, 5)


def test_line_half_width_boundary_inclusive() -> None:
    # 5 ft wide -> half-width 2.5 ft; axis on the y=0 grid line, so the two
    # adjacent rows sit exactly 0.5 cells = 2.5 ft away: the boundary itself.
    template = make_aoe_template("line", 20, origin_x=0, origin_y=1, aim=(1, 1))
    # Cell (2,0): center (2.5, 0.5), perpendicular exactly 2.5 ft -> inside.
    assert cell_in_template(template, 2, 0)
    # Cell (2,1): center (2.5, 1.5), perpendicular exactly 2.5 ft -> inside.
    assert cell_in_template(template, 2, 1)
    # Cell (2,2): center (2.5, 2.5), perpendicular 7.5 ft -> outside.
    assert not cell_in_template(template, 2, 2)
    # Cell (2,-1): center (2.5, -0.5), perpendicular 7.5 ft -> outside.
    assert not cell_in_template(template, 2, -1)


def test_line_length_boundary() -> None:
    template = make_aoe_template("line", 20, origin_x=0, origin_y=0, aim=(1, 0))
    # Cell (3,0): projection 3.5 cells * 5 = 17.5 ft, inside.
    assert cell_in_template(template, 3, 0)
    # Cell (4,0): projection 4.5 cells * 5 = 22.5 ft, beyond length.
    assert not cell_in_template(template, 4, 0)
    # Behind the origin vertex is never inside.
    assert not cell_in_template(template, -1, 0)


def test_line_width_uses_feet_not_cells() -> None:
    # 100 ft line on a 30-wide board: 20 cells long x 2 rows wide = 40 cells.
    template = make_aoe_template("line", 100, origin_x=5, origin_y=5, aim=(6, 5))
    cells = affected_cells(template, width_cells=30, height_cells=20)
    assert len(cells) == 40


def test_affected_cells_clip_to_board_bounds() -> None:
    template = make_aoe_template("circle", 20, origin_x=0, origin_y=0)
    cells = affected_cells(template, width_cells=3, height_cells=3)
    assert cells
    assert all(0 <= cell.x < 3 and 0 <= cell.y < 3 for cell in cells)
    # Unclipped, the same template covers more cells.
    unclipped = affected_cells(template, width_cells=30, height_cells=30)
    assert len(unclipped) > len(cells)


def test_resolve_aoe_candidates_multi_cell_creature() -> None:
    template = make_aoe_template("circle", 20, origin_x=10, origin_y=10)
    large = AoeCombatant(
        entry_id="b",
        cells=(GridCell(x=0, y=0), GridCell(x=13, y=10)),  # one cell on the boundary
    )
    far = AoeCombatant(entry_id="a", cells=(GridCell(x=0, y=0),))
    assert resolve_aoe_candidates(
        template, (large, far), width_cells=30, height_cells=30
    ) == ("b",)
    # Deterministic order regardless of input order.
    assert resolve_aoe_candidates(
        template, (far, large), width_cells=30, height_cells=30
    ) == ("b",)
    assert (
        resolve_aoe_candidates(template, (), width_cells=30, height_cells=30) == ()
    )
