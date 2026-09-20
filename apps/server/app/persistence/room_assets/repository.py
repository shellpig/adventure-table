from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, exists, insert, select
from sqlalchemy.engine import Connection, Engine

from app.persistence.adventures.tables import adventure_entry_assets
from app.persistence.room_assets.tables import room_assets


@dataclass(frozen=True)
class StoredRoomAsset:
    id: UUID
    room_id: UUID
    kind: str
    storage_key: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    visibility: str
    created_at: datetime


class RoomAssetRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _asset(row) -> StoredRoomAsset | None:
        return StoredRoomAsset(**dict(row)) if row is not None else None

    def insert_in_transaction(
        self,
        connection: Connection,
        stored: StoredRoomAsset,
    ) -> None:
        connection.execute(insert(room_assets).values(**stored.__dict__))

    def insert(self, stored: StoredRoomAsset) -> None:
        with self.engine.begin() as connection:
            self.insert_in_transaction(connection, stored)

    def get(self, room_id: UUID, asset_id: UUID) -> StoredRoomAsset | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(room_assets).where(
                    room_assets.c.room_id == room_id,
                    room_assets.c.id == asset_id,
                )
            ).mappings().one_or_none()
            return self._asset(row)

    def list_for_room(
        self,
        room_id: UUID,
        kind: str | None = None,
    ) -> tuple[StoredRoomAsset, ...]:
        with self.engine.connect() as connection:
            query = select(room_assets).where(room_assets.c.room_id == room_id)
            if kind is not None:
                query = query.where(room_assets.c.kind == kind)
            query = query.order_by(room_assets.c.created_at, room_assets.c.id)
            rows = connection.execute(query).mappings().all()
            return tuple(StoredRoomAsset(**dict(row)) for row in rows)

    def delete(self, room_id: UUID, asset_id: UUID) -> StoredRoomAsset | None:
        with self.engine.begin() as connection:
            row = connection.execute(
                select(room_assets).where(
                    room_assets.c.room_id == room_id,
                    room_assets.c.id == asset_id,
                )
            ).mappings().one_or_none()
            if row is None:
                return None
            stored = StoredRoomAsset(**dict(row))
            connection.execute(
                delete(room_assets).where(
                    room_assets.c.room_id == room_id,
                    room_assets.c.id == asset_id,
                )
            )
            return stored

    def is_referenced(self, asset_id: UUID) -> bool:
        with self.engine.connect() as connection:
            return bool(
                connection.scalar(
                    select(
                        exists().where(adventure_entry_assets.c.asset_id == asset_id)
                    )
                )
            )


__all__ = ["RoomAssetRepository", "StoredRoomAsset"]
