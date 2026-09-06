from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, event, insert, select

from app.db import metadata
from app.persistence.builder_drafts import character_build_drafts
from app.persistence.characters import characters
from app.persistence.rooms.tables import room_builder_drafts, room_characters, rooms
from app.persistence.rooms.workspace import (
    RoomWorkspaceAssociationConflictError,
    RoomWorkspaceRepository,
)


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


def _seed_room(connection, room_id: UUID, code: str) -> None:
    now = datetime.now(timezone.utc)
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code=code,
            name=f"Room {code}",
            password_salt=b"s" * 32,
            password_hash=b"p" * 64,
            owner_key_hash=b"o" * 32,
            dm_key_hash=b"d" * 32,
            created_at=now,
            updated_at=now,
        )
    )


def _seed_character_and_draft(connection, character_id: UUID, draft_id: UUID) -> None:
    connection.execute(
        insert(characters).values(
            id=character_id,
            name="Workspace fixture",
            ruleset="dnd5e-2014",
            current_version_id=None,
            archived_at=None,
        )
    )
    connection.execute(
        insert(character_build_drafts).values(
            id=draft_id,
            mode="create",
            character_id=None,
            base_version_id=None,
            revision=1,
            draft_payload={},
            confirmed_character_id=None,
            confirmed_version_id=None,
            confirmed_at=None,
        )
    )


def test_character_and_draft_can_belong_to_only_one_room() -> None:
    engine = _engine()
    repository = RoomWorkspaceRepository(engine)
    room_a = uuid4()
    room_b = uuid4()
    character_id = uuid4()
    draft_id = uuid4()
    try:
        with engine.begin() as connection:
            _seed_room(connection, room_a, "AAAAAAAAAA")
            _seed_room(connection, room_b, "BBBBBBBBBB")
            _seed_character_and_draft(connection, character_id, draft_id)

        repository.attach_character(room_id=room_a, character_id=character_id)
        repository.attach_draft(room_id=room_a, draft_id=draft_id)

        with pytest.raises(RoomWorkspaceAssociationConflictError):
            repository.attach_character(room_id=room_b, character_id=character_id)
        with pytest.raises(RoomWorkspaceAssociationConflictError):
            repository.attach_draft(room_id=room_b, draft_id=draft_id)

        assert repository.character_room_id(character_id) == room_a
        assert repository.draft_room_id(draft_id) == room_a
    finally:
        engine.dispose()


def test_association_rejects_missing_core_rows_and_rolls_back() -> None:
    engine = _engine()
    repository = RoomWorkspaceRepository(engine)
    room_id = uuid4()
    missing_character_id = uuid4()
    missing_draft_id = uuid4()
    try:
        with engine.begin() as connection:
            _seed_room(connection, room_id, "CCCCCCCCCC")

        with pytest.raises(RoomWorkspaceAssociationConflictError):
            repository.attach_character(
                room_id=room_id,
                character_id=missing_character_id,
            )
        with pytest.raises(RoomWorkspaceAssociationConflictError):
            repository.attach_draft(room_id=room_id, draft_id=missing_draft_id)

        with engine.connect() as connection:
            assert connection.execute(select(room_characters)).all() == []
            assert connection.execute(select(room_builder_drafts)).all() == []
    finally:
        engine.dispose()


def test_core_delete_cascades_workspace_association() -> None:
    engine = _engine()
    repository = RoomWorkspaceRepository(engine)
    room_id = uuid4()
    character_id = uuid4()
    draft_id = uuid4()
    try:
        with engine.begin() as connection:
            _seed_room(connection, room_id, "DDDDDDDDDD")
            _seed_character_and_draft(connection, character_id, draft_id)
        repository.attach_character(room_id=room_id, character_id=character_id)
        repository.attach_draft(room_id=room_id, draft_id=draft_id)

        with engine.begin() as connection:
            connection.execute(
                delete(character_build_drafts).where(character_build_drafts.c.id == draft_id)
            )
            connection.execute(delete(characters).where(characters.c.id == character_id))

        with engine.connect() as connection:
            assert connection.execute(select(room_characters)).all() == []
            assert connection.execute(select(room_builder_drafts)).all() == []
    finally:
        engine.dispose()
