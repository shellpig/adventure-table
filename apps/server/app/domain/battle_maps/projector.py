"""Audience projection for Battle Map Definitions (P5-A).

The DM projection is the full definition. The player projection redacts
secrets server-side: hidden walls are omitted entirely, hidden doors are
projected as opaque wall segments (coordinates only, no id, no state, no
visibility), and player-side walls never carry an id.
"""

from __future__ import annotations

from typing import Literal, overload

from app.domain.battle_maps.schemas import (
    BattleMap,
    ProjectedBattleMap,
    ProjectedBattleMapDoor,
    ProjectedBattleMapWall,
)


@overload
def project_battle_map(
    definition: BattleMap, audience: Literal["dm"] = ...
) -> BattleMap: ...


@overload
def project_battle_map(
    definition: BattleMap, audience: Literal["player"]
) -> ProjectedBattleMap: ...


def project_battle_map(
    definition: BattleMap,
    audience: Literal["dm", "player"] = "dm",
) -> BattleMap | ProjectedBattleMap:
    if audience == "dm":
        return definition
    walls: list[ProjectedBattleMapWall] = []
    doors: list[ProjectedBattleMapDoor] = []
    for wall in definition.walls:
        if wall.visibility == "hidden":
            continue
        walls.append(
            ProjectedBattleMapWall(x1=wall.x1, y1=wall.y1, x2=wall.x2, y2=wall.y2)
        )
    for door in definition.doors:
        if door.visibility == "hidden":
            walls.append(
                ProjectedBattleMapWall(
                    x1=door.x1, y1=door.y1, x2=door.x2, y2=door.y2
                )
            )
            continue
        doors.append(
            ProjectedBattleMapDoor(
                id=door.id,
                x1=door.x1,
                y1=door.y1,
                x2=door.x2,
                y2=door.y2,
                state=door.default_state,
            )
        )
    return ProjectedBattleMap(
        id=definition.id,
        room_id=definition.room_id,
        name=definition.name,
        source_kind=definition.source_kind,
        image_asset_id=definition.image_asset_id,
        width_cells=definition.width_cells,
        height_cells=definition.height_cells,
        grid_pixel_size=definition.grid_pixel_size,
        grid_offset_x=definition.grid_offset_x,
        grid_offset_y=definition.grid_offset_y,
        revision=definition.revision,
        audience="player",
        walls=walls,
        doors=doors,
        terrain=list(definition.terrain),
        drawings=list(definition.drawings),
    )


__all__ = ["project_battle_map"]
