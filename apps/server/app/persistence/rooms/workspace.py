from __future__ import annotations

from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.persistence.rooms.tables import room_builder_drafts, room_characters


class RoomWorkspaceAssociationConflictError(RuntimeError):
    """Raised when a Character or Draft cannot be associated with a Room."""


class RoomWorkspaceRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def attach_character_in_transaction(
        connection: Connection,
        *,
        room_id: UUID,
        character_id: UUID,
    ) -> None:
        try:
            connection.execute(
                insert(room_characters).values(
                    room_id=room_id,
                    character_id=character_id,
                )
            )
        except IntegrityError as exc:
            raise RoomWorkspaceAssociationConflictError(
                f"character {character_id} cannot be associated with room {room_id}"
            ) from exc

    @staticmethod
    def attach_draft_in_transaction(
        connection: Connection,
        *,
        room_id: UUID,
        draft_id: UUID,
    ) -> None:
        try:
            connection.execute(
                insert(room_builder_drafts).values(
                    room_id=room_id,
                    draft_id=draft_id,
                )
            )
        except IntegrityError as exc:
            raise RoomWorkspaceAssociationConflictError(
                f"draft {draft_id} cannot be associated with room {room_id}"
            ) from exc

    def attach_character(self, *, room_id: UUID, character_id: UUID) -> None:
        with self.engine.begin() as connection:
            self.attach_character_in_transaction(
                connection,
                room_id=room_id,
                character_id=character_id,
            )

    def attach_draft(self, *, room_id: UUID, draft_id: UUID) -> None:
        with self.engine.begin() as connection:
            self.attach_draft_in_transaction(
                connection,
                room_id=room_id,
                draft_id=draft_id,
            )

    def character_room_id(self, character_id: UUID) -> UUID | None:
        with self.engine.connect() as connection:
            return connection.scalar(
                select(room_characters.c.room_id).where(
                    room_characters.c.character_id == character_id
                )
            )

    def draft_room_id(self, draft_id: UUID) -> UUID | None:
        with self.engine.connect() as connection:
            return connection.scalar(
                select(room_builder_drafts.c.room_id).where(
                    room_builder_drafts.c.draft_id == draft_id
                )
            )


__all__ = [
    "RoomWorkspaceAssociationConflictError",
    "RoomWorkspaceRepository",
]
