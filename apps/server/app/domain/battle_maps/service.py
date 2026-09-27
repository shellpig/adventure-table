from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import cast
from uuid import UUID, uuid4

from app.domain.battle_maps.schemas import (
    MAX_DRAWING_PAYLOAD_BYTES,
    BattleMap,
    BattleMapAssetInvalidError,
    BattleMapCreate,
    BattleMapDoor,
    BattleMapDoorInput,
    BattleMapDoorState,
    BattleMapDrawing,
    BattleMapDrawingInput,
    BattleMapForbiddenError,
    BattleMapInvalidError,
    BattleMapNotFoundError,
    BattleMapObjectsReplace,
    BattleMapPatch,
    BattleMapRevisionConflictError,
    BattleMapShrinkConflictError,
    BattleMapSourceKind,
    BattleMapSummary,
    BattleMapTerrain,
    BattleMapTerrainInput,
    BattleMapTerrainKind,
    BattleMapWall,
    BattleMapWallInput,
    BattleMapWallVisibility,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.battle_maps.repository import (
    BattleMapNotFoundError as PersistenceBattleMapNotFoundError,
)
from app.persistence.battle_maps.repository import (
    BattleMapRepository,
    StoredBattleMap,
    StoredBattleMapDoor,
    StoredBattleMapDrawing,
    StoredBattleMapObjects,
    StoredBattleMapTerrain,
    StoredBattleMapWall,
)
from app.persistence.battle_maps.repository import (
    BattleMapRevisionConflictError as PersistenceBattleMapRevisionConflictError,
)
from app.persistence.room_assets.repository import RoomAssetRepository


def _require_author(context: RoomAccessContext, room_id: UUID) -> None:
    if context.room_id != room_id:
        raise BattleMapNotFoundError(f"Room {room_id} not found")
    if context.authority is RoomAccessAuthority.MEMBER:
        raise BattleMapForbiddenError("Owner or DM authority is required")


def _validate_wall_segment(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    width_cells: int,
    height_cells: int,
    *,
    unit_length: bool,
    label: str,
) -> None:
    horizontal = y1 == y2 and x1 != x2
    vertical = x1 == x2 and y1 != y2
    if not (horizontal or vertical):
        raise BattleMapInvalidError(
            f"{label} must be a horizontal or vertical segment with length >= 1"
        )
    if unit_length and abs(x1 - x2) + abs(y1 - y2) != 1:
        raise BattleMapInvalidError(f"{label} must be exactly one cell edge long")
    for name, value, limit in (
        ("x1", x1, width_cells),
        ("x2", x2, width_cells),
        ("y1", y1, height_cells),
        ("y2", y2, height_cells),
    ):
        if not 0 <= value <= limit:
            raise BattleMapInvalidError(
                f"{label} {name}={value} is outside the 0..{limit} vertex range"
            )


def _validate_terrain_cell(
    x: int, y: int, width_cells: int, height_cells: int
) -> None:
    if not 0 <= x < width_cells or not 0 <= y < height_cells:
        raise BattleMapInvalidError(
            f"terrain cell ({x}, {y}) is outside the "
            f"{width_cells}x{height_cells} map"
        )


def _validate_drawing_payload(payload: dict[str, object]) -> None:
    try:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise BattleMapInvalidError(
            f"drawing payload is not JSON serializable: {exc}"
        ) from exc
    if len(encoded) > MAX_DRAWING_PAYLOAD_BYTES:
        raise BattleMapInvalidError(
            f"drawing payload {len(encoded)} bytes exceeds the "
            f"{MAX_DRAWING_PAYLOAD_BYTES} byte limit"
        )


def _check_unique_ids(label: str, ids: list[UUID]) -> None:
    if len(set(ids)) != len(ids):
        raise BattleMapInvalidError(f"duplicate {label} ids in objects payload")


def battle_map_view(
    stored: StoredBattleMap, objects: StoredBattleMapObjects
) -> BattleMap:
    return BattleMap(
        id=stored.id,
        room_id=stored.room_id,
        name=stored.name,
        source_kind=cast(BattleMapSourceKind, stored.source_kind),
        image_asset_id=stored.image_asset_id,
        width_cells=stored.width_cells,
        height_cells=stored.height_cells,
        grid_pixel_size=stored.grid_pixel_size,
        grid_offset_x=stored.grid_offset_x,
        grid_offset_y=stored.grid_offset_y,
        revision=stored.revision,
        created_at=stored.created_at,
        updated_at=stored.updated_at,
        walls=[
            BattleMapWall(
                id=wall.id,
                x1=wall.x1,
                y1=wall.y1,
                x2=wall.x2,
                y2=wall.y2,
                visibility=cast(BattleMapWallVisibility, wall.visibility),
            )
            for wall in objects.walls
        ],
        doors=[
            BattleMapDoor(
                id=door.id,
                x1=door.x1,
                y1=door.y1,
                x2=door.x2,
                y2=door.y2,
                default_state=cast(BattleMapDoorState, door.default_state),
                visibility=cast(BattleMapWallVisibility, door.visibility),
            )
            for door in objects.doors
        ],
        terrain=[
            BattleMapTerrain(
                x=cell.x,
                y=cell.y,
                terrain_kind=cast(BattleMapTerrainKind, cell.terrain_kind),
            )
            for cell in objects.terrain
        ],
        drawings=[
            BattleMapDrawing(id=drawing.id, payload=drawing.payload)
            for drawing in objects.drawings
        ],
    )


def battle_map_summary_view(stored: StoredBattleMap) -> BattleMapSummary:
    return BattleMapSummary(
        id=stored.id,
        room_id=stored.room_id,
        name=stored.name,
        source_kind=cast(BattleMapSourceKind, stored.source_kind),
        image_asset_id=stored.image_asset_id,
        width_cells=stored.width_cells,
        height_cells=stored.height_cells,
        revision=stored.revision,
        created_at=stored.created_at,
        updated_at=stored.updated_at,
    )


class BattleMapService:
    def __init__(
        self,
        repository: BattleMapRepository,
        asset_repository: RoomAssetRepository,
    ) -> None:
        self.repository = repository
        self.asset_repository = asset_repository

    def create(
        self,
        context: RoomAccessContext,
        *,
        room_id: UUID,
        payload: BattleMapCreate,
    ) -> BattleMap:
        _require_author(context, room_id)
        if payload.source_kind == "blank":
            return self._create_blank(room_id=room_id, payload=payload)
        return self._create_image(room_id=room_id, payload=payload)

    def _create_blank(
        self, *, room_id: UUID, payload: BattleMapCreate
    ) -> BattleMap:
        if payload.image_asset_id is not None:
            raise BattleMapInvalidError("blank maps cannot reference an image asset")
        if (
            payload.grid_pixel_size is not None
            or payload.grid_offset_x is not None
            or payload.grid_offset_y is not None
        ):
            raise BattleMapInvalidError("blank maps do not use grid alignment")
        now = datetime.now(timezone.utc)
        stored = StoredBattleMap(
            id=uuid4(),
            room_id=room_id,
            name=payload.name,
            source_kind="blank",
            image_asset_id=None,
            width_cells=payload.width_cells,
            height_cells=payload.height_cells,
            grid_pixel_size=None,
            grid_offset_x=None,
            grid_offset_y=None,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        with self.repository.engine.begin() as connection:
            self.repository.insert_map_in_transaction(connection, stored)
        return battle_map_view(stored, StoredBattleMapObjects())

    def _create_image(
        self, *, room_id: UUID, payload: BattleMapCreate
    ) -> BattleMap:
        if payload.image_asset_id is None:
            raise BattleMapInvalidError("image maps require image_asset_id")
        asset = self.asset_repository.get(room_id, payload.image_asset_id)
        if asset is None:
            raise BattleMapAssetInvalidError(
                f"image asset {payload.image_asset_id} not found in this room"
            )
        if asset.kind != "battle_map_image":
            raise BattleMapAssetInvalidError(
                f"asset {payload.image_asset_id} is kind '{asset.kind}', "
                "expected 'battle_map_image'"
            )
        now = datetime.now(timezone.utc)
        stored = StoredBattleMap(
            id=uuid4(),
            room_id=room_id,
            name=payload.name,
            source_kind="image",
            image_asset_id=payload.image_asset_id,
            width_cells=payload.width_cells,
            height_cells=payload.height_cells,
            grid_pixel_size=payload.grid_pixel_size,
            grid_offset_x=payload.grid_offset_x,
            grid_offset_y=payload.grid_offset_y,
            revision=1,
            created_at=now,
            updated_at=now,
        )
        with self.repository.engine.begin() as connection:
            self.repository.insert_map_in_transaction(connection, stored)
        return battle_map_view(stored, StoredBattleMapObjects())

    def get(
        self, context: RoomAccessContext, room_id: UUID, map_id: UUID
    ) -> BattleMap:
        _require_author(context, room_id)
        stored = self.repository.get_map(room_id, map_id)
        if stored is None:
            raise BattleMapNotFoundError(f"Battle map {map_id} not found")
        objects = self.repository.get_objects(map_id)
        return battle_map_view(stored, objects)

    def list(
        self, context: RoomAccessContext, room_id: UUID
    ) -> list[BattleMapSummary]:
        _require_author(context, room_id)
        return [
            battle_map_summary_view(stored)
            for stored in self.repository.list_maps(room_id)
        ]

    def patch(
        self,
        context: RoomAccessContext,
        *,
        room_id: UUID,
        map_id: UUID,
        payload: BattleMapPatch,
    ) -> BattleMap:
        _require_author(context, room_id)
        with self.repository.engine.begin() as connection:
            stored = self.repository.get_map(
                room_id, map_id, connection=connection
            )
            if stored is None:
                raise BattleMapNotFoundError(f"Battle map {map_id} not found")

            values: dict[str, object] = {}
            if "name" in payload.model_fields_set:
                values["name"] = payload.name
            if "width_cells" in payload.model_fields_set:
                values["width_cells"] = payload.width_cells
            if "height_cells" in payload.model_fields_set:
                values["height_cells"] = payload.height_cells
            if stored.source_kind == "blank":
                for field_name in (
                    "grid_pixel_size",
                    "grid_offset_x",
                    "grid_offset_y",
                ):
                    if field_name in payload.model_fields_set:
                        raise BattleMapInvalidError(
                            "blank maps do not use grid alignment"
                        )
            else:
                if "grid_pixel_size" in payload.model_fields_set:
                    values["grid_pixel_size"] = payload.grid_pixel_size
                if "grid_offset_x" in payload.model_fields_set:
                    values["grid_offset_x"] = payload.grid_offset_x
                if "grid_offset_y" in payload.model_fields_set:
                    values["grid_offset_y"] = payload.grid_offset_y

            new_width = (
                payload.width_cells
                if payload.width_cells is not None
                else stored.width_cells
            )
            new_height = (
                payload.height_cells
                if payload.height_cells is not None
                else stored.height_cells
            )
            objects = self.repository.get_objects(map_id, connection=connection)
            if new_width < stored.width_cells or new_height < stored.height_cells:
                self._reject_shrink_out_of_bounds(
                    objects, new_width, new_height
                )

            values["updated_at"] = datetime.now(timezone.utc)
            try:
                updated = self.repository.update_map_in_transaction(
                    connection,
                    room_id,
                    map_id,
                    values,
                    expected_revision=payload.expected_revision,
                )
            except PersistenceBattleMapNotFoundError as exc:
                raise BattleMapNotFoundError(str(exc)) from exc
            except PersistenceBattleMapRevisionConflictError as exc:
                raise BattleMapRevisionConflictError(str(exc)) from exc
            return battle_map_view(updated, objects)

    @staticmethod
    def _reject_shrink_out_of_bounds(
        objects: StoredBattleMapObjects, new_width: int, new_height: int
    ) -> None:
        for wall in objects.walls:
            if (
                max(wall.x1, wall.x2) > new_width
                or max(wall.y1, wall.y2) > new_height
            ):
                raise BattleMapShrinkConflictError(
                    f"wall {wall.id} would fall outside the "
                    f"{new_width}x{new_height} map"
                )
        for door in objects.doors:
            if (
                max(door.x1, door.x2) > new_width
                or max(door.y1, door.y2) > new_height
            ):
                raise BattleMapShrinkConflictError(
                    f"door {door.id} would fall outside the "
                    f"{new_width}x{new_height} map"
                )
        for cell in objects.terrain:
            if cell.x >= new_width or cell.y >= new_height:
                raise BattleMapShrinkConflictError(
                    f"terrain cell ({cell.x}, {cell.y}) would fall outside the "
                    f"{new_width}x{new_height} map"
                )

    def replace_objects(
        self,
        context: RoomAccessContext,
        *,
        room_id: UUID,
        map_id: UUID,
        payload: BattleMapObjectsReplace,
    ) -> BattleMap:
        _require_author(context, room_id)
        with self.repository.engine.begin() as connection:
            stored = self.repository.get_map(
                room_id, map_id, connection=connection
            )
            if stored is None:
                raise BattleMapNotFoundError(f"Battle map {map_id} not found")
            objects = self._validated_objects(
                payload,
                stored.width_cells,
                stored.height_cells,
                map_id=map_id,
            )
            try:
                updated = self.repository.replace_objects_in_transaction(
                    connection,
                    room_id,
                    map_id,
                    objects,
                    expected_revision=payload.expected_revision,
                )
            except PersistenceBattleMapNotFoundError as exc:
                raise BattleMapNotFoundError(str(exc)) from exc
            except PersistenceBattleMapRevisionConflictError as exc:
                raise BattleMapRevisionConflictError(str(exc)) from exc
            return battle_map_view(updated, objects)

    @staticmethod
    def _validated_objects(
        payload: BattleMapObjectsReplace,
        width_cells: int,
        height_cells: int,
        *,
        map_id: UUID,
    ) -> StoredBattleMapObjects:
        walls: list[StoredBattleMapWall] = []
        wall_ids: list[UUID] = []
        for index, wall in enumerate(payload.walls):
            _validate_wall_segment(
                wall.x1,
                wall.y1,
                wall.x2,
                wall.y2,
                width_cells,
                height_cells,
                unit_length=False,
                label=f"wall[{index}]",
            )
            wall_id = wall.id or uuid4()
            wall_ids.append(wall_id)
            walls.append(
                StoredBattleMapWall(
                    id=wall_id,
                    battle_map_id=map_id,
                    x1=wall.x1,
                    y1=wall.y1,
                    x2=wall.x2,
                    y2=wall.y2,
                    visibility=wall.visibility,
                )
            )
        _check_unique_ids("wall", wall_ids)

        doors: list[StoredBattleMapDoor] = []
        door_ids: list[UUID] = []
        for index, door in enumerate(payload.doors):
            _validate_wall_segment(
                door.x1,
                door.y1,
                door.x2,
                door.y2,
                width_cells,
                height_cells,
                unit_length=True,
                label=f"door[{index}]",
            )
            door_id = door.id or uuid4()
            door_ids.append(door_id)
            doors.append(
                StoredBattleMapDoor(
                    id=door_id,
                    battle_map_id=map_id,
                    x1=door.x1,
                    y1=door.y1,
                    x2=door.x2,
                    y2=door.y2,
                    default_state=door.default_state,
                    visibility=door.visibility,
                )
            )
        _check_unique_ids("door", door_ids)

        terrain: list[StoredBattleMapTerrain] = []
        seen_cells: set[tuple[int, int]] = set()
        for index, cell in enumerate(payload.terrain):
            _validate_terrain_cell(
                cell.x, cell.y, width_cells, height_cells
            )
            if (cell.x, cell.y) in seen_cells:
                raise BattleMapInvalidError(
                    f"terrain[{index}] duplicates cell ({cell.x}, {cell.y})"
                )
            seen_cells.add((cell.x, cell.y))
            terrain.append(
                StoredBattleMapTerrain(
                    battle_map_id=map_id,
                    x=cell.x,
                    y=cell.y,
                    terrain_kind=cell.terrain_kind,
                )
            )

        drawings: list[StoredBattleMapDrawing] = []
        drawing_ids: list[UUID] = []
        for index, drawing in enumerate(payload.drawings):
            _validate_drawing_payload(drawing.payload)
            drawing_id = drawing.id or uuid4()
            drawing_ids.append(drawing_id)
            drawings.append(
                StoredBattleMapDrawing(
                    id=drawing_id,
                    battle_map_id=map_id,
                    payload=drawing.payload,
                )
            )
        _check_unique_ids("drawing", drawing_ids)

        return StoredBattleMapObjects(
            walls=tuple(walls),
            doors=tuple(doors),
            terrain=tuple(terrain),
            drawings=tuple(drawings),
        )

    def delete(
        self, context: RoomAccessContext, room_id: UUID, map_id: UUID
    ) -> None:
        _require_author(context, room_id)
        deleted = self.repository.delete_map(room_id, map_id)
        if not deleted:
            raise BattleMapNotFoundError(f"Battle map {map_id} not found")


__all__ = ["BattleMapService", "battle_map_summary_view", "battle_map_view"]
