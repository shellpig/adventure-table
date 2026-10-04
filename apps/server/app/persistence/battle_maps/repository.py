from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, Engine

from app.persistence.battle_maps.tables import (
    battle_map_doors,
    battle_map_drawings,
    battle_map_monster_placements,
    battle_map_terrain,
    battle_map_walls,
    battle_maps,
)
from app.persistence.combat_boards.tables import combat_boards


@dataclass(frozen=True)
class StoredBattleMap:
    id: UUID
    room_id: UUID
    name: str
    source_kind: str
    image_asset_id: UUID | None
    width_cells: int
    height_cells: int
    grid_pixel_size: int | None
    grid_offset_x: int | None
    grid_offset_y: int | None
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


@dataclass(frozen=True)
class StoredBattleMapWall:
    id: UUID
    battle_map_id: UUID
    x1: int
    y1: int
    x2: int
    y2: int
    visibility: str


@dataclass(frozen=True)
class StoredBattleMapDoor:
    id: UUID
    battle_map_id: UUID
    x1: int
    y1: int
    x2: int
    y2: int
    default_state: str
    visibility: str


@dataclass(frozen=True)
class StoredBattleMapTerrain:
    battle_map_id: UUID
    x: int
    y: int
    terrain_kind: str


@dataclass(frozen=True)
class StoredBattleMapDrawing:
    id: UUID
    battle_map_id: UUID
    payload: dict[str, object]


@dataclass(frozen=True)
class StoredMonsterPlacement:
    id: UUID
    battle_map_id: UUID
    template_key: str | None
    custom_template_id: UUID | None
    anchor_x: int
    anchor_y: int
    visibility: str
    sort_order: int


@dataclass(frozen=True)
class StoredBattleMapObjects:
    walls: tuple[StoredBattleMapWall, ...] = field(default_factory=tuple)
    doors: tuple[StoredBattleMapDoor, ...] = field(default_factory=tuple)
    terrain: tuple[StoredBattleMapTerrain, ...] = field(default_factory=tuple)
    drawings: tuple[StoredBattleMapDrawing, ...] = field(default_factory=tuple)


class BattleMapNotFoundError(Exception):
    pass


class BattleMapRevisionConflictError(Exception):
    pass


class BattleMapReferencedError(Exception):
    pass


class BattleMapRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def insert_map_in_transaction(
        self, connection: Connection, stored: StoredBattleMap
    ) -> StoredBattleMap:
        connection.execute(insert(battle_maps).values(**stored.__dict__))
        return stored

    def get_map(
        self,
        room_id: UUID,
        map_id: UUID,
        *,
        connection: Connection | None = None,
        for_update: bool = False,
    ) -> StoredBattleMap | None:
        query = select(battle_maps).where(
            battle_maps.c.room_id == room_id,
            battle_maps.c.id == map_id,
        )
        if for_update:
            query = query.with_for_update()
        if connection is not None:
            row = connection.execute(query).mappings().one_or_none()
            return StoredBattleMap(**dict(row)) if row is not None else None
        with self.engine.connect() as conn:
            row = conn.execute(query).mappings().one_or_none()
            return StoredBattleMap(**dict(row)) if row is not None else None

    def list_maps(
        self, room_id: UUID, *, include_archived: bool = False
    ) -> tuple[StoredBattleMap, ...]:
        query = select(battle_maps).where(battle_maps.c.room_id == room_id)
        if not include_archived:
            query = query.where(battle_maps.c.archived_at.is_(None))
        query = query.order_by(battle_maps.c.created_at, battle_maps.c.id)
        with self.engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return tuple(StoredBattleMap(**dict(row)) for row in rows)

    def update_map_in_transaction(
        self,
        connection: Connection,
        room_id: UUID,
        map_id: UUID,
        values: dict[str, object],
        *,
        expected_revision: int,
    ) -> StoredBattleMap:
        result = connection.execute(
            update(battle_maps)
            .where(
                battle_maps.c.room_id == room_id,
                battle_maps.c.id == map_id,
                battle_maps.c.revision == expected_revision,
            )
            .values(revision=battle_maps.c.revision + 1, **values)
        )
        if result.rowcount == 0:
            existing = connection.execute(
                select(battle_maps.c.revision).where(
                    battle_maps.c.room_id == room_id,
                    battle_maps.c.id == map_id,
                )
            ).mappings().one_or_none()
            if existing is None:
                raise BattleMapNotFoundError(f"Battle map {map_id} not found")
            raise BattleMapRevisionConflictError(
                f"Battle map {map_id} revision conflict: "
                f"expected {expected_revision}, current {existing['revision']}"
            )
        row = (
            connection.execute(
                select(battle_maps).where(
                    battle_maps.c.room_id == room_id,
                    battle_maps.c.id == map_id,
                )
            )
            .mappings()
            .one()
        )
        return StoredBattleMap(**dict(row))

    def archive_map_in_transaction(
        self,
        connection: Connection,
        room_id: UUID,
        map_id: UUID,
        *,
        expected_revision: int,
    ) -> StoredBattleMap:
        now = datetime.now(timezone.utc)
        return self.update_map_in_transaction(
            connection,
            room_id,
            map_id,
            {"archived_at": now, "updated_at": now},
            expected_revision=expected_revision,
        )

    def delete_map(
        self, room_id: UUID, map_id: UUID, *, expected_revision: int
    ) -> bool:
        with self.engine.begin() as connection:
            return self.delete_map_in_transaction(
                connection, room_id, map_id, expected_revision=expected_revision
            )

    def delete_map_in_transaction(
        self,
        connection: Connection,
        room_id: UUID,
        map_id: UUID,
        *,
        expected_revision: int,
    ) -> bool:
        row = connection.execute(
            select(battle_maps.c.id, battle_maps.c.revision)
            .where(
                battle_maps.c.room_id == room_id,
                battle_maps.c.id == map_id,
            )
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise BattleMapNotFoundError(f"Battle map {map_id} not found")
        if row["revision"] != expected_revision:
            raise BattleMapRevisionConflictError(
                f"Battle map {map_id} revision conflict: expected {expected_revision}, current {row['revision']}"
            )
        has_ref = connection.scalar(
            select(combat_boards.c.combat_id)
            .where(combat_boards.c.source_battle_map_id == map_id)
            .limit(1)
        )
        if has_ref is not None:
            raise BattleMapReferencedError(
                f"Battle map {map_id} is referenced by combat board and cannot be deleted"
            )
        connection.execute(
            delete(battle_map_monster_placements).where(
                battle_map_monster_placements.c.battle_map_id == map_id
            )
        )
        connection.execute(
            delete(battle_map_drawings).where(
                battle_map_drawings.c.battle_map_id == map_id
            )
        )
        connection.execute(
            delete(battle_map_terrain).where(
                battle_map_terrain.c.battle_map_id == map_id
            )
        )
        connection.execute(
            delete(battle_map_doors).where(
                battle_map_doors.c.battle_map_id == map_id
            )
        )
        connection.execute(
            delete(battle_map_walls).where(
                battle_map_walls.c.battle_map_id == map_id
            )
        )
        result = connection.execute(
            delete(battle_maps).where(
                battle_maps.c.room_id == room_id,
                battle_maps.c.id == map_id,
            )
        )
        return bool(result.rowcount > 0)

    def get_placements(
        self,
        map_id: UUID,
        *,
        connection: Connection | None = None,
    ) -> tuple[StoredMonsterPlacement, ...]:
        query = (
            select(battle_map_monster_placements)
            .where(battle_map_monster_placements.c.battle_map_id == map_id)
            .order_by(
                battle_map_monster_placements.c.sort_order,
                battle_map_monster_placements.c.id,
            )
        )
        if connection is not None:
            rows = connection.execute(query).mappings().all()
        else:
            with self.engine.connect() as conn:
                rows = conn.execute(query).mappings().all()
        return tuple(StoredMonsterPlacement(**dict(row)) for row in rows)

    def placement_ids_on_other_maps(
        self,
        connection: Connection,
        map_id: UUID,
        placement_ids: list[UUID],
    ) -> frozenset[UUID]:
        if not placement_ids:
            return frozenset()
        rows = connection.execute(
            select(battle_map_monster_placements.c.id).where(
                battle_map_monster_placements.c.id.in_(placement_ids),
                battle_map_monster_placements.c.battle_map_id != map_id,
            )
        ).scalars()
        return frozenset(rows)

    def replace_placements_in_transaction(
        self,
        connection: Connection,
        map_id: UUID,
        placements: tuple[StoredMonsterPlacement, ...],
    ) -> None:
        connection.execute(
            delete(battle_map_monster_placements).where(
                battle_map_monster_placements.c.battle_map_id == map_id
            )
        )
        if placements:
            connection.execute(
                insert(battle_map_monster_placements),
                [placement.__dict__ for placement in placements],
            )

    def copy_placements_in_transaction(
        self,
        connection: Connection,
        source_map_id: UUID,
        new_map_id: UUID,
    ) -> tuple[StoredMonsterPlacement, ...]:
        """Copy every placement to a new map, assigning fresh placement ids."""
        copied = tuple(
            StoredMonsterPlacement(
                id=uuid4(),
                battle_map_id=new_map_id,
                template_key=placement.template_key,
                custom_template_id=placement.custom_template_id,
                anchor_x=placement.anchor_x,
                anchor_y=placement.anchor_y,
                visibility=placement.visibility,
                sort_order=placement.sort_order,
            )
            for placement in self.get_placements(
                source_map_id, connection=connection
            )
        )
        if copied:
            connection.execute(
                insert(battle_map_monster_placements),
                [placement.__dict__ for placement in copied],
            )
        return copied

    def get_objects(
        self,
        map_id: UUID,
        *,
        connection: Connection | None = None,
    ) -> StoredBattleMapObjects:
        def _load(conn: Connection) -> StoredBattleMapObjects:
            walls = (
                conn.execute(
                    select(battle_map_walls)
                    .where(battle_map_walls.c.battle_map_id == map_id)
                    .order_by(battle_map_walls.c.id)
                )
                .mappings()
                .all()
            )
            doors = (
                conn.execute(
                    select(battle_map_doors)
                    .where(battle_map_doors.c.battle_map_id == map_id)
                    .order_by(battle_map_doors.c.id)
                )
                .mappings()
                .all()
            )
            terrain = (
                conn.execute(
                    select(battle_map_terrain)
                    .where(battle_map_terrain.c.battle_map_id == map_id)
                    .order_by(battle_map_terrain.c.y, battle_map_terrain.c.x)
                )
                .mappings()
                .all()
            )
            drawings = (
                conn.execute(
                    select(battle_map_drawings)
                    .where(battle_map_drawings.c.battle_map_id == map_id)
                    .order_by(battle_map_drawings.c.id)
                )
                .mappings()
                .all()
            )
            return StoredBattleMapObjects(
                walls=tuple(StoredBattleMapWall(**dict(row)) for row in walls),
                doors=tuple(StoredBattleMapDoor(**dict(row)) for row in doors),
                terrain=tuple(StoredBattleMapTerrain(**dict(row)) for row in terrain),
                drawings=tuple(
                    StoredBattleMapDrawing(**dict(row)) for row in drawings
                ),
            )

        if connection is not None:
            return _load(connection)
        with self.engine.connect() as conn:
            return _load(conn)

    def replace_objects_in_transaction(
        self,
        connection: Connection,
        room_id: UUID,
        map_id: UUID,
        objects: StoredBattleMapObjects,
        *,
        expected_revision: int,
    ) -> StoredBattleMap:
        stored = self.update_map_in_transaction(
            connection,
            room_id,
            map_id,
            {},
            expected_revision=expected_revision,
        )
        connection.execute(
            delete(battle_map_drawings).where(
                battle_map_drawings.c.battle_map_id == map_id
            )
        )
        connection.execute(
            delete(battle_map_terrain).where(
                battle_map_terrain.c.battle_map_id == map_id
            )
        )
        connection.execute(
            delete(battle_map_doors).where(
                battle_map_doors.c.battle_map_id == map_id
            )
        )
        connection.execute(
            delete(battle_map_walls).where(
                battle_map_walls.c.battle_map_id == map_id
            )
        )
        self.insert_objects_in_transaction(connection, map_id, objects)
        return stored

    def insert_objects_in_transaction(
        self,
        connection: Connection,
        map_id: UUID,
        objects: StoredBattleMapObjects,
    ) -> None:
        if objects.walls:
            connection.execute(
                insert(battle_map_walls),
                [wall.__dict__ for wall in objects.walls],
            )
        if objects.doors:
            connection.execute(
                insert(battle_map_doors),
                [door.__dict__ for door in objects.doors],
            )
        if objects.terrain:
            connection.execute(
                insert(battle_map_terrain),
                [cell.__dict__ for cell in objects.terrain],
            )
        if objects.drawings:
            connection.execute(
                insert(battle_map_drawings),
                [drawing.__dict__ for drawing in objects.drawings],
            )


__all__ = [
    "BattleMapNotFoundError",
    "BattleMapReferencedError",
    "BattleMapRepository",
    "BattleMapRevisionConflictError",
    "StoredBattleMap",
    "StoredBattleMapDoor",
    "StoredBattleMapDrawing",
    "StoredBattleMapObjects",
    "StoredBattleMapTerrain",
    "StoredBattleMapWall",
    "StoredMonsterPlacement",
]
