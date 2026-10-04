from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.content.identity import parse_stable_key
from app.content.registry import ContentRegistry
from app.domain.battle_maps.placements import (
    PLACEMENT_PROBLEM_INVALID_SIZE,
    PLACEMENT_PROBLEM_TEMPLATE_ARCHIVED,
    PlacementValidationEntry,
    barriers_from_map_objects,
    blocked_cells_from_terrain,
    resolve_placement_size,
    validate_monster_placements,
)
from app.domain.battle_maps.schemas import (
    MAX_DRAWING_PAYLOAD_BYTES,
    BattleMap,
    BattleMapArchive,
    BattleMapAssetInvalidError,
    BattleMapCopy,
    BattleMapCreate,
    BattleMapDoor,
    BattleMapDoorInput,
    BattleMapDoorState,
    BattleMapDrawing,
    BattleMapDrawingInput,
    BattleMapForbiddenError,
    BattleMapInvalidError,
    BattleMapMonsterPlacement,
    BattleMapMonsterPlacementVisibility,
    BattleMapNotFoundError,
    BattleMapObjectsReplace,
    BattleMapPatch,
    BattleMapReferencedError,
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
    MapMonsterPlacementInvalidError,
    MonsterPlacementInput,
    MonsterPlacementProblem,
    MonsterPlacementReferenceNotFoundError,
    MonsterPlacementSourceError,
    MonsterPlacementsReplace,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.battle_maps.repository import (
    BattleMapNotFoundError as PersistenceBattleMapNotFoundError,
    BattleMapReferencedError as PersistenceBattleMapReferencedError,
    BattleMapRepository,
    BattleMapRevisionConflictError as PersistenceBattleMapRevisionConflictError,
    StoredBattleMap,
    StoredBattleMapDoor,
    StoredBattleMapDrawing,
    StoredBattleMapObjects,
    StoredBattleMapTerrain,
    StoredBattleMapWall,
    StoredMonsterPlacement,
)
from app.persistence.combat.tables import monster_templates
from app.persistence.room_assets.repository import RoomAssetRepository


if TYPE_CHECKING:
    from app.domain.combat.resolution import SizeCategory


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


def validate_map_geometry(
    width_cells: int,
    height_cells: int,
    *,
    walls: list[BattleMapWallInput],
    doors: list[BattleMapDoorInput],
    terrain: list[BattleMapTerrainInput],
    drawings: list[BattleMapDrawingInput],
) -> None:
    wall_ids = [wall.id for wall in walls if wall.id is not None]
    _check_unique_ids("wall", wall_ids)
    for index, wall in enumerate(walls):
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
    door_ids = [door.id for door in doors if door.id is not None]
    _check_unique_ids("door", door_ids)
    for index, door in enumerate(doors):
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
    seen_cells: set[tuple[int, int]] = set()
    for index, cell in enumerate(terrain):
        _validate_terrain_cell(cell.x, cell.y, width_cells, height_cells)
        if (cell.x, cell.y) in seen_cells:
            raise BattleMapInvalidError(
                f"terrain[{index}] duplicates cell ({cell.x}, {cell.y})"
            )
        seen_cells.add((cell.x, cell.y))
    drawing_ids = [drawing.id for drawing in drawings if drawing.id is not None]
    _check_unique_ids("drawing", drawing_ids)
    for drawing in drawings:
        _validate_drawing_payload(drawing.payload)


def validated_stored_objects(
    width_cells: int,
    height_cells: int,
    *,
    walls: list[BattleMapWallInput],
    doors: list[BattleMapDoorInput],
    terrain: list[BattleMapTerrainInput],
    drawings: list[BattleMapDrawingInput],
    map_id: UUID,
    keep_client_ids: bool,
) -> StoredBattleMapObjects:
    """Validate geometry and build stored objects.

    Library replace keeps client-supplied object ids; a temporary Tactical map
    (M07-B) always gets Server-assigned ids.
    """
    validate_map_geometry(
        width_cells,
        height_cells,
        walls=walls,
        doors=doors,
        terrain=terrain,
        drawings=drawings,
    )

    def object_id(client_id: UUID | None) -> UUID:
        return client_id if keep_client_ids and client_id is not None else uuid4()

    return StoredBattleMapObjects(
        walls=tuple(
            StoredBattleMapWall(
                id=object_id(wall.id),
                battle_map_id=map_id,
                x1=wall.x1,
                y1=wall.y1,
                x2=wall.x2,
                y2=wall.y2,
                visibility=wall.visibility,
            )
            for wall in walls
        ),
        doors=tuple(
            StoredBattleMapDoor(
                id=object_id(door.id),
                battle_map_id=map_id,
                x1=door.x1,
                y1=door.y1,
                x2=door.x2,
                y2=door.y2,
                default_state=door.default_state,
                visibility=door.visibility,
            )
            for door in doors
        ),
        terrain=tuple(
            StoredBattleMapTerrain(
                battle_map_id=map_id,
                x=cell.x,
                y=cell.y,
                terrain_kind=cell.terrain_kind,
            )
            for cell in terrain
        ),
        drawings=tuple(
            StoredBattleMapDrawing(
                id=object_id(drawing.id),
                battle_map_id=map_id,
                payload=drawing.payload,
            )
            for drawing in drawings
        ),
    )


def battle_map_view(
    stored: StoredBattleMap,
    objects: StoredBattleMapObjects,
    placements: tuple[StoredMonsterPlacement, ...] = (),
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
        archived_at=stored.archived_at,
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
        monster_placements=[
            BattleMapMonsterPlacement(
                id=placement.id,
                template_key=placement.template_key,
                custom_template_id=placement.custom_template_id,
                anchor_x=placement.anchor_x,
                anchor_y=placement.anchor_y,
                visibility=cast(
                    BattleMapMonsterPlacementVisibility, placement.visibility
                ),
                sort_order=placement.sort_order,
            )
            for placement in placements
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
        archived_at=stored.archived_at,
    )


@dataclass(frozen=True)
class _PlacementSource:
    """One placement whose template reference still needs resolving."""

    placement_id: UUID
    template_key: str | None
    custom_template_id: UUID | None
    anchor_x: int
    anchor_y: int
    visibility: str
    sort_order: int


@dataclass(frozen=True)
class _ResolvedPlacement:
    """A placement with its template row looked up and size resolved."""

    placement_id: UUID
    template_key: str | None
    custom_template_id: UUID | None
    anchor_x: int
    anchor_y: int
    visibility: str
    sort_order: int
    size: SizeCategory | None  # None means the template size value is unparseable
    archived_source: bool


def _saved_custom_refs(
    placements: tuple[StoredMonsterPlacement, ...],
) -> frozenset[tuple[UUID, UUID]]:
    return frozenset(
        (placement.id, placement.custom_template_id)
        for placement in placements
        if placement.custom_template_id is not None
    )


class BattleMapService:
    def __init__(
        self,
        repository: BattleMapRepository,
        asset_repository: RoomAssetRepository,
        table_event_service: TableEventService,
        *,
        content_registry: ContentRegistry,
    ) -> None:
        self.repository = repository
        self.asset_repository = asset_repository
        self.table_event_service = table_event_service
        self.content_registry = content_registry

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

    def _require_actor_dm(self, actor: TableActorContext, room_id: UUID) -> None:
        if actor.room_id != room_id:
            raise BattleMapNotFoundError(f"Room {room_id} not found")
        self.table_event_service.require_actor_current(actor)
        if not (actor.role == "dm" and actor.is_current_dm):
            raise TableEventActorUnauthorizedError(
                "Only the current Session DM can view battle maps"
            )

    def get(
        self, context: RoomAccessContext, room_id: UUID, map_id: UUID
    ) -> BattleMap:
        _require_author(context, room_id)
        return self._get_internal(room_id, map_id)

    def get_for_actor(
        self, actor: TableActorContext, map_id: UUID
    ) -> BattleMap:
        self._require_actor_dm(actor, actor.room_id)
        return self._get_internal(actor.room_id, map_id)

    def _get_internal(self, room_id: UUID, map_id: UUID) -> BattleMap:
        stored = self.repository.get_map(room_id, map_id)
        if stored is None:
            raise BattleMapNotFoundError(f"Battle map {map_id} not found")
        objects = self.repository.get_objects(map_id)
        placements = self.repository.get_placements(map_id)
        return battle_map_view(stored, objects, placements=placements)

    def list(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[BattleMapSummary]:
        _require_author(context, room_id)
        return self._list_internal(room_id, include_archived=include_archived)

    def list_for_actor(
        self, actor: TableActorContext, *, include_archived: bool = False
    ) -> list[BattleMapSummary]:
        self._require_actor_dm(actor, actor.room_id)
        return self._list_internal(actor.room_id, include_archived=include_archived)

    def _list_internal(
        self, room_id: UUID, *, include_archived: bool
    ) -> list[BattleMapSummary]:
        return [
            battle_map_summary_view(stored)
            for stored in self.repository.list_maps(
                room_id, include_archived=include_archived
            )
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
            if new_width != stored.width_cells or new_height != stored.height_cells:
                self._reject_conflicting_placements(
                    connection,
                    room_id,
                    map_id,
                    width_cells=new_width,
                    height_cells=new_height,
                    objects=objects,
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
            placements = self.repository.get_placements(
                map_id, connection=connection
            )
            return battle_map_view(updated, objects, placements=placements)

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
            # Geometry-only edit: never clears placements, but a geometry
            # change that breaks saved placements rejects the whole replace.
            self._reject_conflicting_placements(
                connection,
                room_id,
                map_id,
                width_cells=stored.width_cells,
                height_cells=stored.height_cells,
                objects=objects,
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
            placements = self.repository.get_placements(
                map_id, connection=connection
            )
            return battle_map_view(updated, objects, placements=placements)

    def replace_monster_placements(
        self,
        context: RoomAccessContext,
        *,
        room_id: UUID,
        map_id: UUID,
        payload: MonsterPlacementsReplace,
    ) -> BattleMap:
        """Replace the map's whole monster placement set (M07-C).

        Placements are part of the map revision: the replace runs in one
        transaction, bumps the map revision, and rejects the whole batch when
        any placement has a source or geometry problem.
        """
        _require_author(context, room_id)
        self._check_duplicate_placement_ids(payload.placements)
        with self.repository.engine.begin() as connection:
            stored = self.repository.get_map(
                room_id, map_id, connection=connection, for_update=True
            )
            if stored is None:
                raise BattleMapNotFoundError(f"Battle map {map_id} not found")
            if stored.revision != payload.expected_revision:
                raise BattleMapRevisionConflictError(
                    f"Battle map {map_id} revision conflict: "
                    f"expected {payload.expected_revision}, "
                    f"current {stored.revision}"
                )
            old_placements = self.repository.get_placements(
                map_id, connection=connection
            )
            foreign_ids = self.repository.placement_ids_on_other_maps(
                connection,
                map_id,
                [item.id for item in payload.placements if item.id is not None],
            )
            if foreign_ids:
                raise MonsterPlacementSourceError(
                    "monster placement ids belong to another map: "
                    + ", ".join(str(placement_id) for placement_id in sorted(foreign_ids))
                )
            sources = [
                _PlacementSource(
                    placement_id=item.id or uuid4(),
                    template_key=item.template_key,
                    custom_template_id=item.custom_template_id,
                    anchor_x=item.anchor_x,
                    anchor_y=item.anchor_y,
                    visibility=item.visibility,
                    sort_order=item.sort_order,
                )
                for item in payload.placements
            ]
            resolved = self._resolve_placement_sources(
                connection,
                room_id,
                sources,
                saved_custom_refs=_saved_custom_refs(old_placements),
                lock_templates=True,
            )
            objects = self.repository.get_objects(map_id, connection=connection)
            problems = self._validate_resolved_placements(
                resolved,
                width_cells=stored.width_cells,
                height_cells=stored.height_cells,
                objects=objects,
            )
            if problems:
                raise MapMonsterPlacementInvalidError(problems)
            self.repository.replace_placements_in_transaction(
                connection,
                map_id,
                tuple(
                    StoredMonsterPlacement(
                        id=item.placement_id,
                        battle_map_id=map_id,
                        template_key=item.template_key,
                        custom_template_id=item.custom_template_id,
                        anchor_x=item.anchor_x,
                        anchor_y=item.anchor_y,
                        visibility=item.visibility,
                        sort_order=item.sort_order,
                    )
                    for item in resolved
                ),
            )
            try:
                updated = self.repository.update_map_in_transaction(
                    connection,
                    room_id,
                    map_id,
                    {"updated_at": datetime.now(timezone.utc)},
                    expected_revision=payload.expected_revision,
                )
            except PersistenceBattleMapNotFoundError as exc:
                raise BattleMapNotFoundError(str(exc)) from exc
            except PersistenceBattleMapRevisionConflictError as exc:
                raise BattleMapRevisionConflictError(str(exc)) from exc
            new_placements = self.repository.get_placements(
                map_id, connection=connection
            )
            return battle_map_view(updated, objects, placements=new_placements)

    @staticmethod
    def _check_duplicate_placement_ids(
        placements: list[MonsterPlacementInput],
    ) -> None:
        seen: set[UUID] = set()
        for item in placements:
            if item.id is None:
                continue
            if item.id in seen:
                raise MonsterPlacementSourceError(
                    f"duplicate monster placement id {item.id} in replace payload"
                )
            seen.add(item.id)

    def _template_rows(
        self,
        connection: Connection,
        custom_template_ids: set[UUID],
        *,
        for_update: bool,
    ) -> dict[UUID, dict[str, object]]:
        if not custom_template_ids:
            return {}
        query = (
            select(
                monster_templates.c.id,
                monster_templates.c.room_id,
                monster_templates.c.archived_at,
                monster_templates.c.rules,
            )
            .where(monster_templates.c.id.in_(sorted(custom_template_ids)))
            .order_by(monster_templates.c.id)
        )
        if for_update:
            query = query.with_for_update()
        return {
            row["id"]: dict(row)
            for row in connection.execute(query).mappings()
        }

    def _resolve_placement_sources(
        self,
        connection: Connection,
        room_id: UUID,
        sources: list[_PlacementSource],
        *,
        saved_custom_refs: frozenset[tuple[UUID, UUID]],
        lock_templates: bool,
    ) -> list[_ResolvedPlacement]:
        """Resolve template references to sizes.

        Lock order follows the M07 design contract: the map row is already
        locked by the caller; custom template rows are locked here ordered by
        template id. A missing built-in key or a missing / cross-Room custom
        template is a 404; a newly added (or changed-to) archived custom
        template is reported as a placement problem, while an unchanged
        archived reference already saved on the map stays allowed. "Unchanged"
        is per placement: the same placement id must already reference that
        template, so a new placement cannot add another archived reference.
        """
        custom_ids = {
            source.custom_template_id
            for source in sources
            if source.custom_template_id is not None
        }
        rows = self._template_rows(
            connection, custom_ids, for_update=lock_templates
        )
        resolved: list[_ResolvedPlacement] = []
        for source in sources:
            if source.template_key is not None:
                entry = self.content_registry.get_optional(source.template_key)
                if entry is None:
                    raise MonsterPlacementReferenceNotFoundError(
                        f"monster template '{source.template_key}' not found"
                    )
                if parse_stable_key(entry.key).kind != "monster":
                    raise MonsterPlacementSourceError(
                        f"content entry '{source.template_key}' is not a monster"
                    )
                data = entry.data if isinstance(entry.data, dict) else {}
                size = resolve_placement_size(data.get("size"))
                archived_source = False
            else:
                template_id = source.custom_template_id
                assert template_id is not None
                row = rows.get(template_id)
                if row is None or row["room_id"] != room_id:
                    raise MonsterPlacementReferenceNotFoundError(
                        f"monster template '{template_id}' not found in this room"
                    )
                rules = row["rules"] if isinstance(row["rules"], dict) else {}
                size = resolve_placement_size(rules.get("size"))
                archived_source = (
                    row["archived_at"] is not None
                    and (source.placement_id, template_id) not in saved_custom_refs
                )
            resolved.append(
                _ResolvedPlacement(
                    placement_id=source.placement_id,
                    template_key=source.template_key,
                    custom_template_id=source.custom_template_id,
                    anchor_x=source.anchor_x,
                    anchor_y=source.anchor_y,
                    visibility=source.visibility,
                    sort_order=source.sort_order,
                    size=size,
                    archived_source=archived_source,
                )
            )
        return resolved

    def _resolve_existing_placements(
        self,
        connection: Connection,
        room_id: UUID,
        placements: tuple[StoredMonsterPlacement, ...],
    ) -> list[_ResolvedPlacement]:
        """Resolve sizes for already-saved placements (geometry re-validation).

        Existing references keep their archived status; no template row locks
        are taken because templates are not mutated here.
        """
        sources = [
            _PlacementSource(
                placement_id=placement.id,
                template_key=placement.template_key,
                custom_template_id=placement.custom_template_id,
                anchor_x=placement.anchor_x,
                anchor_y=placement.anchor_y,
                visibility=placement.visibility,
                sort_order=placement.sort_order,
            )
            for placement in placements
        ]
        return self._resolve_placement_sources(
            connection,
            room_id,
            sources,
            saved_custom_refs=_saved_custom_refs(placements),
            lock_templates=False,
        )

    def _validate_resolved_placements(
        self,
        resolved: list[_ResolvedPlacement],
        *,
        width_cells: int,
        height_cells: int,
        objects: StoredBattleMapObjects,
    ) -> list[MonsterPlacementProblem]:
        """Collect every placement problem without stopping at the first."""
        problems: list[MonsterPlacementProblem] = []
        entries: list[PlacementValidationEntry] = []
        for item in resolved:
            if item.archived_source:
                problems.append(
                    MonsterPlacementProblem(
                        placement_id=item.placement_id,
                        code=PLACEMENT_PROBLEM_TEMPLATE_ARCHIVED,
                    )
                )
            if item.size is None:
                problems.append(
                    MonsterPlacementProblem(
                        placement_id=item.placement_id,
                        code=PLACEMENT_PROBLEM_INVALID_SIZE,
                    )
                )
            else:
                entries.append(
                    PlacementValidationEntry(
                        placement_id=item.placement_id,
                        size=item.size,
                        anchor_x=item.anchor_x,
                        anchor_y=item.anchor_y,
                    )
                )
        barriers = barriers_from_map_objects(objects.walls, objects.doors)
        blocked = blocked_cells_from_terrain(objects.terrain)
        for problem in validate_monster_placements(
            entries,
            width_cells=width_cells,
            height_cells=height_cells,
            barriers=barriers,
            blocked_cells=blocked,
        ):
            problems.append(
                MonsterPlacementProblem(
                    placement_id=problem.placement_id, code=problem.code
                )
            )
        return problems

    def _reject_conflicting_placements(
        self,
        connection: Connection,
        room_id: UUID,
        map_id: UUID,
        *,
        width_cells: int,
        height_cells: int,
        objects: StoredBattleMapObjects,
    ) -> None:
        """Reject a geometry/dimension change that breaks saved placements."""
        placements = self.repository.get_placements(
            map_id, connection=connection
        )
        if not placements:
            return
        resolved = self._resolve_existing_placements(
            connection, room_id, placements
        )
        problems = self._validate_resolved_placements(
            resolved,
            width_cells=width_cells,
            height_cells=height_cells,
            objects=objects,
        )
        if problems:
            raise MapMonsterPlacementInvalidError(problems)

    def copy(
        self,
        context: RoomAccessContext,
        *,
        room_id: UUID,
        map_id: UUID,
        payload: BattleMapCopy,
    ) -> BattleMap:
        _require_author(context, room_id)
        with self.repository.engine.begin() as connection:
            stored = self.repository.get_map(
                room_id, map_id, connection=connection, for_update=True
            )
            if stored is None:
                raise BattleMapNotFoundError(f"Battle map {map_id} not found")
            if stored.revision != payload.expected_revision:
                raise BattleMapRevisionConflictError(
                    f"Battle map {map_id} revision conflict: "
                    f"expected {payload.expected_revision}, current {stored.revision}"
                )
            objects = self.repository.get_objects(
                map_id, connection=connection
            )
            now = datetime.now(timezone.utc)
            new_map_id = uuid4()
            name = payload.name or f"{stored.name} (Copy)"
            new_stored = StoredBattleMap(
                id=new_map_id,
                room_id=room_id,
                name=name,
                source_kind=stored.source_kind,
                image_asset_id=stored.image_asset_id,
                width_cells=stored.width_cells,
                height_cells=stored.height_cells,
                grid_pixel_size=stored.grid_pixel_size,
                grid_offset_x=stored.grid_offset_x,
                grid_offset_y=stored.grid_offset_y,
                revision=1,
                created_at=now,
                updated_at=now,
                archived_at=None,
            )
            self.repository.insert_map_in_transaction(connection, new_stored)
            new_objects = StoredBattleMapObjects(
                walls=tuple(
                    StoredBattleMapWall(
                        id=uuid4(),
                        battle_map_id=new_map_id,
                        x1=w.x1,
                        y1=w.y1,
                        x2=w.x2,
                        y2=w.y2,
                        visibility=w.visibility,
                    )
                    for w in objects.walls
                ),
                doors=tuple(
                    StoredBattleMapDoor(
                        id=uuid4(),
                        battle_map_id=new_map_id,
                        x1=d.x1,
                        y1=d.y1,
                        x2=d.x2,
                        y2=d.y2,
                        default_state=d.default_state,
                        visibility=d.visibility,
                    )
                    for d in objects.doors
                ),
                terrain=tuple(
                    StoredBattleMapTerrain(
                        battle_map_id=new_map_id,
                        x=t.x,
                        y=t.y,
                        terrain_kind=t.terrain_kind,
                    )
                    for t in objects.terrain
                ),
                drawings=tuple(
                    StoredBattleMapDrawing(
                        id=uuid4(),
                        battle_map_id=new_map_id,
                        payload=deepcopy(dr.payload),
                    )
                    for dr in objects.drawings
                ),
            )
            self.repository.insert_objects_in_transaction(
                connection, new_map_id, new_objects
            )
            # M07-C: copy placements with fresh placement ids, keeping the
            # original template references (archived references stay allowed).
            new_placements = self.repository.copy_placements_in_transaction(
                connection, map_id, new_map_id
            )
        return battle_map_view(new_stored, new_objects, placements=new_placements)

    def archive(
        self,
        context: RoomAccessContext,
        *,
        room_id: UUID,
        map_id: UUID,
        payload: BattleMapArchive,
    ) -> BattleMap:
        _require_author(context, room_id)
        with self.repository.engine.begin() as connection:
            stored = self.repository.get_map(
                room_id, map_id, connection=connection, for_update=True
            )
            if stored is None:
                raise BattleMapNotFoundError(f"Battle map {map_id} not found")
            try:
                updated = self.repository.archive_map_in_transaction(
                    connection,
                    room_id=room_id,
                    map_id=map_id,
                    expected_revision=payload.expected_revision,
                )
            except PersistenceBattleMapNotFoundError as exc:
                raise BattleMapNotFoundError(str(exc)) from exc
            except PersistenceBattleMapRevisionConflictError as exc:
                raise BattleMapRevisionConflictError(str(exc)) from exc
            objects = self.repository.get_objects(
                map_id, connection=connection
            )
            placements = self.repository.get_placements(
                map_id, connection=connection
            )
            return battle_map_view(updated, objects, placements=placements)

    @staticmethod
    def _validated_objects(
        payload: BattleMapObjectsReplace,
        width_cells: int,
        height_cells: int,
        *,
        map_id: UUID,
    ) -> StoredBattleMapObjects:
        return validated_stored_objects(
            width_cells,
            height_cells,
            walls=payload.walls,
            doors=payload.doors,
            terrain=payload.terrain,
            drawings=payload.drawings,
            map_id=map_id,
            keep_client_ids=True,
        )

    def delete(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        map_id: UUID,
        *,
        expected_revision: int,
    ) -> None:
        _require_author(context, room_id)
        try:
            deleted = self.repository.delete_map(
                room_id, map_id, expected_revision=expected_revision
            )
        except PersistenceBattleMapNotFoundError as exc:
            raise BattleMapNotFoundError(str(exc)) from exc
        except PersistenceBattleMapRevisionConflictError as exc:
            raise BattleMapRevisionConflictError(str(exc)) from exc
        except PersistenceBattleMapReferencedError as exc:
            raise BattleMapReferencedError(str(exc)) from exc
        if not deleted:
            raise BattleMapNotFoundError(f"Battle map {map_id} not found")


__all__ = [
    "BattleMapService",
    "battle_map_summary_view",
    "battle_map_view",
    "validate_map_geometry",
    "validated_stored_objects",
]
