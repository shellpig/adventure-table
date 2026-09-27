"""P5-A: battle-map Player projection wall order is source-independent."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.domain.battle_maps.projector import project_battle_map
from app.domain.battle_maps.schemas import BattleMap, BattleMapDoor, BattleMapWall


def _definition(*, walls: list[BattleMapWall], doors: list[BattleMapDoor]) -> BattleMap:
    now = datetime.now(timezone.utc)
    return BattleMap(
        id=uuid4(), room_id=uuid4(), name="Cave", source_kind="blank",
        image_asset_id=None, width_cells=20, height_cells=15,
        grid_pixel_size=None, grid_offset_x=None, grid_offset_y=None,
        revision=3, created_at=now, updated_at=now,
        walls=walls, doors=doors,
    )


def _wall(x1: int, y1: int, x2: int, y2: int) -> BattleMapWall:
    return BattleMapWall(id=uuid4(), x1=x1, y1=y1, x2=x2, y2=y2, visibility="public")


def _hidden_door(x1: int, y1: int, x2: int, y2: int) -> BattleMapDoor:
    return BattleMapDoor(
        id=uuid4(), x1=x1, y1=y1, x2=x2, y2=y2,
        default_state="closed", visibility="hidden",
    )


def test_player_walls_sorted_and_source_independent() -> None:
    # Same segments, different insertion orders — the Player projection must be
    # identical so wall order cannot leak which segments are hidden doors.
    definition_a = _definition(
        walls=[_wall(9, 0, 9, 3), _wall(0, 0, 5, 0)],
        doors=[_hidden_door(5, 0, 9, 0), _hidden_door(0, 3, 0, 9)],
    )
    definition_b = _definition(
        walls=[_wall(0, 0, 5, 0), _wall(9, 0, 9, 3)],
        doors=[_hidden_door(0, 3, 0, 9), _hidden_door(5, 0, 9, 0)],
    )
    projected_a = project_battle_map(definition_a, audience="player")
    projected_b = project_battle_map(definition_b, audience="player")

    coords_a = [(w.x1, w.y1, w.x2, w.y2) for w in projected_a.walls]
    coords_b = [(w.x1, w.y1, w.x2, w.y2) for w in projected_b.walls]
    assert coords_a == sorted(coords_a)
    assert coords_a == coords_b
    assert coords_a == [(0, 0, 5, 0), (0, 3, 0, 9), (5, 0, 9, 0), (9, 0, 9, 3)]

    # Hidden-door walls carry no id; hidden walls are omitted entirely.
    assert all(not hasattr(w, "id") for w in projected_a.walls)
    hidden_wall_definition = _definition(
        walls=[BattleMapWall(
            id=uuid4(), x1=1, y1=1, x2=2, y2=2, visibility="hidden",
        )],
        doors=[],
    )
    assert project_battle_map(hidden_wall_definition, audience="player").walls == []
