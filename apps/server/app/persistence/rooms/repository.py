from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.domain.rooms.schemas import RoomAccessAuthority
from app.persistence.rooms.tables import room_access_sessions, rooms
from app.persistence.rooms.workspace import RoomWorkspaceAssociationConflictError


class RoomPersistenceConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredRoom:
    id: UUID
    code: str
    name: str
    password_salt: bytes
    password_hash: bytes
    owner_key_hash: bytes
    dm_key_hash: bytes
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredAccessSession:
    id: UUID
    room_id: UUID
    authority: RoomAccessAuthority
    token_hash: bytes
    display_name: str | None
    created_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None


class RoomRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_room_with_access(
        self,
        *,
        room: StoredRoom,
        access: StoredAccessSession,
        on_first_room: Callable[[Connection, UUID], None] | None = None,
    ) -> None:
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(rooms).values(**room.__dict__))
                values = dict(access.__dict__)
                values["authority"] = access.authority.value
                connection.execute(insert(room_access_sessions).values(**values))
                if on_first_room is not None:
                    room_count = int(
                        connection.scalar(select(func.count()).select_from(rooms)) or 0
                    )
                    if room_count == 1:
                        on_first_room(connection, room.id)
        except (IntegrityError, RoomWorkspaceAssociationConflictError) as exc:
            # A concurrent first-Room bootstrap can race while claiming the same
            # legacy Character/Draft rows. Treat that like the other allocation
            # conflicts so RoomService retries the whole transaction. The retry
            # sees the competing Room once it commits and will not guess a new
            # target for already-scoped legacy data.
            raise RoomPersistenceConflictError(str(exc)) from exc

    def count_rooms(self) -> int:
        with self.engine.connect() as connection:
            return int(connection.scalar(select(func.count()).select_from(rooms)) or 0)

    def get_room_by_code(self, code: str) -> StoredRoom | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(rooms).where(rooms.c.code == code)).mappings().one_or_none()
        return StoredRoom(**dict(row)) if row is not None else None

    def get_room(self, room_id: UUID) -> StoredRoom | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(rooms).where(rooms.c.id == room_id)).mappings().one_or_none()
        return StoredRoom(**dict(row)) if row is not None else None

    def create_access_session(self, access: StoredAccessSession) -> None:
        values = dict(access.__dict__)
        values["authority"] = access.authority.value
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(room_access_sessions).values(**values))
        except IntegrityError as exc:
            raise RoomPersistenceConflictError(str(exc)) from exc

    def get_access_session_by_token_hash(self, token_hash: bytes) -> StoredAccessSession | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(room_access_sessions).where(room_access_sessions.c.token_hash == token_hash)
            ).mappings().one_or_none()
        if row is None:
            return None
        values = dict(row)
        values["authority"] = RoomAccessAuthority(values["authority"])
        return StoredAccessSession(**values)

    def touch_access_session(self, session_id: UUID, now: datetime) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(room_access_sessions)
                .where(
                    room_access_sessions.c.id == session_id,
                    room_access_sessions.c.revoked_at.is_(None),
                )
                .values(last_seen_at=now)
            )
        return result.rowcount == 1


__all__ = ["RoomPersistenceConflictError", "RoomRepository", "StoredAccessSession", "StoredRoom"]
