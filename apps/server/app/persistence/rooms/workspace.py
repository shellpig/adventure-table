from __future__ import annotations

from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.persistence.builder_drafts import character_build_drafts
from app.persistence.characters import characters
from app.persistence.rooms.tables import room_builder_drafts, room_characters


class RoomWorkspaceAssociationConflictError(RuntimeError):
    """Raised when a Character or Draft cannot be associated with a Room."""


class RoomWorkspaceRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def character_room_id_in_transaction(
        connection: Connection,
        character_id: UUID,
    ) -> UUID | None:
        return connection.scalar(
            select(room_characters.c.room_id).where(
                room_characters.c.character_id == character_id
            )
        )

    @staticmethod
    def draft_room_id_in_transaction(
        connection: Connection,
        draft_id: UUID,
    ) -> UUID | None:
        return connection.scalar(
            select(room_builder_drafts.c.room_id).where(
                room_builder_drafts.c.draft_id == draft_id
            )
        )

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

    def ensure_character_in_transaction(
        self,
        connection: Connection,
        *,
        room_id: UUID,
        character_id: UUID,
    ) -> None:
        existing = self.character_room_id_in_transaction(connection, character_id)
        if existing is None:
            self.attach_character_in_transaction(
                connection,
                room_id=room_id,
                character_id=character_id,
            )
            return
        if existing != room_id:
            raise RoomWorkspaceAssociationConflictError(
                f"character {character_id} already belongs to another Room"
            )

    def ensure_draft_in_transaction(
        self,
        connection: Connection,
        *,
        room_id: UUID,
        draft_id: UUID,
    ) -> None:
        existing = self.draft_room_id_in_transaction(connection, draft_id)
        if existing is None:
            self.attach_draft_in_transaction(
                connection,
                room_id=room_id,
                draft_id=draft_id,
            )
            return
        if existing != room_id:
            raise RoomWorkspaceAssociationConflictError(
                f"draft {draft_id} already belongs to another Room"
            )

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
            return self.character_room_id_in_transaction(connection, character_id)

    def draft_room_id(self, draft_id: UUID) -> UUID | None:
        with self.engine.connect() as connection:
            return self.draft_room_id_in_transaction(connection, draft_id)

    def list_character_ids(self, room_id: UUID, *, archived: bool = False) -> tuple[UUID, ...]:
        archived_condition = (
            characters.c.archived_at.is_not(None)
            if archived
            else characters.c.archived_at.is_(None)
        )
        query = (
            select(room_characters.c.character_id)
            .join(characters, characters.c.id == room_characters.c.character_id)
            .where(room_characters.c.room_id == room_id, archived_condition)
            .order_by(characters.c.name, characters.c.id)
        )
        with self.engine.connect() as connection:
            return tuple(connection.scalars(query).all())

    def list_draft_ids(
        self,
        room_id: UUID,
        *,
        character_id: UUID | None = None,
        create_only: bool = False,
    ) -> tuple[UUID, ...]:
        query = (
            select(room_builder_drafts.c.draft_id)
            .join(
                character_build_drafts,
                character_build_drafts.c.id == room_builder_drafts.c.draft_id,
            )
            .where(
                room_builder_drafts.c.room_id == room_id,
                character_build_drafts.c.confirmed_character_id.is_(None),
            )
            .order_by(character_build_drafts.c.updated_at.desc())
        )
        if character_id is not None:
            query = query.where(character_build_drafts.c.character_id == character_id)
        if create_only:
            query = query.where(character_build_drafts.c.mode == "create")
        with self.engine.connect() as connection:
            return tuple(connection.scalars(query).all())


__all__ = [
    "RoomWorkspaceAssociationConflictError",
    "RoomWorkspaceRepository",
]
