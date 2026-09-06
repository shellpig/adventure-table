from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.persistence.builder_drafts import character_build_drafts
from app.persistence.character_imports import character_import_records
from app.persistence.characters import (
    character_states,
    character_versions,
    characters,
)
from app.persistence.rooms.tables import room_builder_drafts, room_characters, rooms


class RoomWorkspaceAssociationConflictError(RuntimeError):
    """Raised when a Character or Draft cannot be associated with a Room."""


@dataclass(frozen=True)
class LegacyWorkspaceCounts:
    characters: int
    drafts: int


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
                insert(room_characters).values(room_id=room_id, character_id=character_id)
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
                insert(room_builder_drafts).values(room_id=room_id, draft_id=draft_id)
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
            self.attach_character_in_transaction(connection, room_id=room_id, character_id=character_id)
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
            self.attach_draft_in_transaction(connection, room_id=room_id, draft_id=draft_id)
            return
        if existing != room_id:
            raise RoomWorkspaceAssociationConflictError(
                f"draft {draft_id} already belongs to another Room"
            )

    @staticmethod
    def _legacy_counts_in_transaction(connection: Connection) -> LegacyWorkspaceCounts:
        unscoped_character = ~select(room_characters.c.character_id).where(
            room_characters.c.character_id == characters.c.id
        ).exists()
        unscoped_draft = ~select(room_builder_drafts.c.draft_id).where(
            room_builder_drafts.c.draft_id == character_build_drafts.c.id
        ).exists()
        character_count = int(
            connection.scalar(
                select(func.count()).select_from(characters).where(unscoped_character)
            )
            or 0
        )
        draft_count = int(
            connection.scalar(
                select(func.count())
                .select_from(character_build_drafts)
                .where(unscoped_draft)
            )
            or 0
        )
        return LegacyWorkspaceCounts(characters=character_count, drafts=draft_count)

    def legacy_counts(self) -> LegacyWorkspaceCounts:
        with self.engine.connect() as connection:
            return self._legacy_counts_in_transaction(connection)

    def claim_all_unscoped_in_transaction(
        self,
        connection: Connection,
        room_id: UUID,
    ) -> LegacyWorkspaceCounts:
        character_ids = tuple(
            connection.scalars(
                select(characters.c.id).where(
                    ~select(room_characters.c.character_id).where(
                        room_characters.c.character_id == characters.c.id
                    ).exists()
                )
            ).all()
        )
        draft_ids = tuple(
            connection.scalars(
                select(character_build_drafts.c.id).where(
                    ~select(room_builder_drafts.c.draft_id).where(
                        room_builder_drafts.c.draft_id == character_build_drafts.c.id
                    ).exists()
                )
            ).all()
        )
        for character_id in character_ids:
            self.attach_character_in_transaction(
                connection,
                room_id=room_id,
                character_id=character_id,
            )
        for draft_id in draft_ids:
            self.attach_draft_in_transaction(
                connection,
                room_id=room_id,
                draft_id=draft_id,
            )
        return LegacyWorkspaceCounts(characters=len(character_ids), drafts=len(draft_ids))

    def claim_all_unscoped(self, room_id: UUID) -> LegacyWorkspaceCounts:
        with self.engine.begin() as connection:
            return self.claim_all_unscoped_in_transaction(connection, room_id)

    def hard_delete_room(self, room_id: UUID) -> LegacyWorkspaceCounts:
        with self.engine.begin() as connection:
            character_ids = tuple(
                connection.scalars(
                    select(room_characters.c.character_id).where(
                        room_characters.c.room_id == room_id
                    )
                ).all()
            )
            draft_ids = tuple(
                connection.scalars(
                    select(room_builder_drafts.c.draft_id).where(
                        room_builder_drafts.c.room_id == room_id
                    )
                ).all()
            )
            if draft_ids:
                connection.execute(
                    delete(character_import_records).where(
                        character_import_records.c.draft_id.in_(draft_ids)
                    )
                )
                connection.execute(
                    delete(character_build_drafts).where(
                        character_build_drafts.c.id.in_(draft_ids)
                    )
                )
            if character_ids:
                connection.execute(
                    delete(character_import_records).where(
                        character_import_records.c.character_id.in_(character_ids)
                    )
                )
                connection.execute(
                    delete(character_states).where(
                        character_states.c.character_id.in_(character_ids)
                    )
                )
                connection.execute(
                    update(characters)
                    .where(characters.c.id.in_(character_ids))
                    .values(current_version_id=None)
                )
                connection.execute(
                    delete(character_versions).where(
                        character_versions.c.character_id.in_(character_ids)
                    )
                )
                connection.execute(
                    delete(characters).where(characters.c.id.in_(character_ids))
                )
            connection.execute(delete(rooms).where(rooms.c.id == room_id))
            return LegacyWorkspaceCounts(
                characters=len(character_ids),
                drafts=len(draft_ids),
            )

    def attach_character(self, *, room_id: UUID, character_id: UUID) -> None:
        with self.engine.begin() as connection:
            self.attach_character_in_transaction(connection, room_id=room_id, character_id=character_id)

    def attach_draft(self, *, room_id: UUID, draft_id: UUID) -> None:
        with self.engine.begin() as connection:
            self.attach_draft_in_transaction(connection, room_id=room_id, draft_id=draft_id)

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
    "LegacyWorkspaceCounts",
    "RoomWorkspaceAssociationConflictError",
    "RoomWorkspaceRepository",
]
