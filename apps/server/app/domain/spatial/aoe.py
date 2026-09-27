"""AoE template geometry: shape normalization and affected-cell resolution (P5-D D1).

Pure functions over the square grid; no dice, no DB. One cell is always 5 ft
(spec 4.1). The origin is always an integer grid vertex, inclusion is decided
by cell centers, and every boundary comparison is ``<=``.

Shape normalization comes from spell content ``data.area_of_effect`` only —
callers must never hardcode spell names::

    sphere / cylinder -> circle (radius = size)
    cube            -> square (side = size)
    cone            -> cone   (length = size)
    line            -> line   (length = size, width fixed at 5 ft)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Mapping

from app.domain.spatial.pathing import FEET_PER_CELL, vertex_cell_distance
from app.domain.spatial.primitives import GridCell

AoeShapeKind = Literal["circle", "square", "cone", "line"]
#: Square quadrant, screen convention (north is -y on the board grid):
#: "ne" extends +x/-y, "nw" extends -x/-y, "se" extends +x/+y, "sw" extends -x/+y.
SquareDirection = Literal["ne", "nw", "se", "sw"]

#: Fixed width of the ``line`` template in feet (P5-D D1).
AOE_LINE_WIDTH_FEET = 5

#: Half-angle of the cone wedge: the cone axis plus ``atan(1/2)`` on each side.
CONE_HALF_ANGLE = math.atan(0.5)


@dataclass(frozen=True)
class AoeTemplate:
    """Normalized AoE template placed on the grid.

    ``origin_x``/``origin_y`` are always an integer grid vertex. ``aim`` is the
    (possibly fractional) aim point for ``cone``/``line`` — any angle is
    allowed. ``direction`` is the quadrant for ``square`` (origin is one corner).
    """

    kind: AoeShapeKind
    size_feet: int
    origin_x: int
    origin_y: int
    aim_x: float | None = None
    aim_y: float | None = None
    direction: SquareDirection | None = None


@dataclass(frozen=True)
class AoeCombatant:
    """A combatant's occupied cells for candidate resolution."""

    entry_id: str
    cells: tuple[GridCell, ...]


_RAW_TO_KIND: dict[str, AoeShapeKind] = {
    "sphere": "circle",
    "cylinder": "circle",
    "cube": "square",
    "cone": "cone",
    "line": "line",
}

_SQUARE_DIRECTIONS: tuple[SquareDirection, ...] = ("ne", "nw", "se", "sw")


def normalize_area_of_effect(
    area_of_effect: Mapping[str, object],
) -> tuple[AoeShapeKind, int]:
    """Normalize spell content ``data.area_of_effect`` to ``(shape, size_feet)``.

    Raises ``ValueError`` for missing/unknown types or non-positive sizes.
    """
    if not isinstance(area_of_effect, Mapping):
        raise ValueError("area_of_effect must be a mapping with type and size")
    raw_type = area_of_effect.get("type")
    kind = (
        _RAW_TO_KIND.get(str(raw_type).lower())
        if isinstance(raw_type, str)
        else None
    )
    if kind is None:
        raise ValueError(f"Unsupported area_of_effect type: {raw_type!r}")
    size = area_of_effect.get("size")
    if isinstance(size, bool) or not isinstance(size, (int, float)):
        raise ValueError(f"area_of_effect size must be a number, got {size!r}")
    if size <= 0 or float(size) != int(size):
        raise ValueError(f"area_of_effect size must be a positive integer, got {size!r}")
    return kind, int(size)


def make_aoe_template(
    kind: AoeShapeKind,
    size_feet: int,
    *,
    origin_x: int,
    origin_y: int,
    aim: tuple[float, float] | None = None,
    direction: SquareDirection | None = None,
) -> AoeTemplate:
    """Build a validated AoE template. Raises ``ValueError`` on bad placement."""
    if (
        not isinstance(origin_x, int)
        or not isinstance(origin_y, int)
        or isinstance(origin_x, bool)
        or isinstance(origin_y, bool)
    ):
        raise ValueError("AoE origin must be an integer grid vertex")
    if not isinstance(size_feet, int) or isinstance(size_feet, bool) or size_feet <= 0:
        raise ValueError("AoE size must be a positive integer number of feet")
    if kind == "circle":
        if aim is not None or direction is not None:
            raise ValueError("circle templates take no aim or direction")
        return AoeTemplate(
            kind=kind, size_feet=size_feet, origin_x=origin_x, origin_y=origin_y
        )
    if kind == "square":
        if direction not in _SQUARE_DIRECTIONS:
            raise ValueError("square templates require a quadrant direction")
        if aim is not None:
            raise ValueError("square templates take no aim point")
        return AoeTemplate(
            kind=kind, size_feet=size_feet, origin_x=origin_x, origin_y=origin_y,
            direction=direction,
        )
    if kind in ("cone", "line"):
        if aim is None:
            raise ValueError(f"{kind} templates require an aim point")
        aim_x, aim_y = aim
        if not isinstance(aim_x, (int, float)) or not isinstance(aim_y, (int, float)):
            raise ValueError("AoE aim must be a numeric point")
        if float(aim_x) == origin_x and float(aim_y) == origin_y:
            raise ValueError("AoE aim must differ from the origin vertex")
        if direction is not None:
            raise ValueError(f"{kind} templates take no quadrant direction")
        return AoeTemplate(
            kind=kind, size_feet=size_feet, origin_x=origin_x, origin_y=origin_y,
            aim_x=float(aim_x), aim_y=float(aim_y),
        )
    raise ValueError(f"Unsupported AoE shape: {kind!r}")


def _cell_center(cell_x: int, cell_y: int) -> tuple[float, float]:
    return cell_x + 0.5, cell_y + 0.5


def _in_circle(template: AoeTemplate, cell_x: int, cell_y: int) -> bool:
    distance = vertex_cell_distance(
        (template.origin_x, template.origin_y), GridCell(x=cell_x, y=cell_y)
    )
    return distance.feet <= template.size_feet


def _in_square(template: AoeTemplate, cell_x: int, cell_y: int) -> bool:
    assert template.direction is not None
    center_x, center_y = _cell_center(cell_x, cell_y)
    # Grid coordinates are cell units; size_feet is feet (one cell = 5 ft).
    side_cells = template.size_feet / FEET_PER_CELL
    # Screen convention: north is -y.
    if "e" in template.direction:
        low_x, high_x = template.origin_x, template.origin_x + side_cells
    else:
        low_x, high_x = template.origin_x - side_cells, template.origin_x
    if "s" in template.direction:
        low_y, high_y = template.origin_y, template.origin_y + side_cells
    else:
        low_y, high_y = template.origin_y - side_cells, template.origin_y
    return low_x <= center_x <= high_x and low_y <= center_y <= high_y


def _axis_unit(template: AoeTemplate) -> tuple[float, float]:
    assert template.aim_x is not None and template.aim_y is not None
    dx = template.aim_x - template.origin_x
    dy = template.aim_y - template.origin_y
    length = math.hypot(dx, dy)
    return dx / length, dy / length


def _in_cone(template: AoeTemplate, cell_x: int, cell_y: int) -> bool:
    if not _in_circle(template, cell_x, cell_y):
        return False
    center_x, center_y = _cell_center(cell_x, cell_y)
    vx = center_x - template.origin_x
    vy = center_y - template.origin_y
    ux, uy = _axis_unit(template)
    dot = ux * vx + uy * vy
    if dot <= 0:
        return False
    # Within +/- atan(1/2) of the axis  <=>  |cross| / dot <= 1/2.
    cross = abs(ux * vy - uy * vx)
    return 2.0 * cross <= dot


def _in_line(template: AoeTemplate, cell_x: int, cell_y: int) -> bool:
    center_x, center_y = _cell_center(cell_x, cell_y)
    vx = center_x - template.origin_x
    vy = center_y - template.origin_y
    ux, uy = _axis_unit(template)
    projection = ux * vx + uy * vy
    # Projection/perpendicular are cell units; size and half-width are feet.
    if projection < 0 or projection * FEET_PER_CELL > template.size_feet:
        return False
    perpendicular = abs(ux * vy - uy * vx)
    return perpendicular * FEET_PER_CELL <= AOE_LINE_WIDTH_FEET / 2.0


def cell_in_template(template: AoeTemplate, cell_x: int, cell_y: int) -> bool:
    """True when the center of ``(cell_x, cell_y)`` falls inside the template."""
    if template.kind == "circle":
        return _in_circle(template, cell_x, cell_y)
    if template.kind == "square":
        return _in_square(template, cell_x, cell_y)
    if template.kind == "cone":
        return _in_cone(template, cell_x, cell_y)
    if template.kind == "line":
        return _in_line(template, cell_x, cell_y)
    raise ValueError(f"Unsupported AoE shape: {template.kind!r}")


def affected_cells(
    template: AoeTemplate, *, width_cells: int, height_cells: int
) -> tuple[GridCell, ...]:
    """All board cells whose center falls inside the template.

    Always clipped to the board bounds; cells are returned in ``(y, x)`` order.
    """
    if width_cells <= 0 or height_cells <= 0:
        raise ValueError("Board dimensions must be positive")
    return tuple(
        GridCell(x=x, y=y)
        for y in range(height_cells)
        for x in range(width_cells)
        if cell_in_template(template, x, y)
    )


def resolve_aoe_candidates(
    template: AoeTemplate,
    combatants: tuple[AoeCombatant, ...],
    *,
    width_cells: int,
    height_cells: int,
) -> tuple[str, ...]:
    """Entry ids of combatants with any occupied cell inside the template.

    Multi-cell creatures count as candidates when any of their cells is
    affected. Returned in ``entry_id`` order for determinism.
    """
    affected = set(affected_cells(
        template, width_cells=width_cells, height_cells=height_cells
    ))
    return tuple(
        sorted(
            combatant.entry_id
            for combatant in combatants
            if any(cell in affected for cell in combatant.cells)
        )
    )


__all__ = [
    "AOE_LINE_WIDTH_FEET",
    "CONE_HALF_ANGLE",
    "AoeCombatant",
    "AoeShapeKind",
    "AoeTemplate",
    "SquareDirection",
    "affected_cells",
    "cell_in_template",
    "make_aoe_template",
    "normalize_area_of_effect",
    "resolve_aoe_candidates",
]
