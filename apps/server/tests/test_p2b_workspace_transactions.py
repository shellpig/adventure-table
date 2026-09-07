from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character_builder.schemas import BuilderDraftCreateInput, BuilderDraftPayload
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.persistence.builder_drafts import character_build_drafts
from app.persistence.characters import (
    CharacterRepository,
    characters,
    character_states,
    character_versions,
)
from app.persistence.rooms.tables import room_builder_drafts, room_characters, rooms
from app.persistence.rooms.workspace import (
    RoomWorkspaceAssociationConflictError,
    RoomWorkspaceRepository,
)
from app.persistence.transaction_bound import TransactionBoundEngine


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


def _seed_room(engine, room_id: UUID, code: str = "EEEEEEEEEE") -> None:
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code=code,
                name="P2-B transaction room",
                password_salt=b"s" * 32,
                password_hash=b"p" * 64,
                owner_key_hash=b"o" * 32,
                dm_key_hash=b"d" * 32,
                created_at=now,
                updated_at=now,
            )
        )


def _count(engine, table) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(table)) or 0)


class _FailDraftAssociation(RoomWorkspaceRepository):
    @staticmethod
    def attach_draft_in_transaction(connection, *, room_id, draft_id) -> None:
        raise RoomWorkspaceAssociationConflictError("injected draft association failure")


class _FailCharacterAssociation(RoomWorkspaceRepository):
    def ensure_character_in_transaction(self, connection, *, room_id, character_id) -> None:
        raise RoomWorkspaceAssociationConflictError("injected character association failure")


def test_create_draft_and_room_association_commit_together() -> None:
    engine = _engine()
    registry = load_default_content_registry()
    room_id = uuid4()
    _seed_room(engine, room_id)
    service = RoomCharacterWorkspaceService(engine, registry)
    try:
        view = service.create_draft(
            room_id,
            BuilderDraftCreateInput(
                draft_payload=BuilderDraftPayload(
                    basic={"name": "Scoped draft"},
                    target_level=1,
                )
            ),
        )
        assert service.workspace_repository.draft_room_id(view.draft.id) == room_id
        assert _count(engine, character_build_drafts) == 1
        assert _count(engine, room_builder_drafts) == 1
    finally:
        engine.dispose()


def test_create_draft_rolls_back_when_room_association_fails() -> None:
    engine = _engine()
    registry = load_default_content_registry()
    room_id = uuid4()
    _seed_room(engine, room_id)
    service = RoomCharacterWorkspaceService(
        engine,
        registry,
        workspace_repository=_FailDraftAssociation(engine),
    )
    try:
        with pytest.raises(RoomWorkspaceAssociationConflictError):
            service.create_draft(
                room_id,
                BuilderDraftCreateInput(
                    draft_payload=BuilderDraftPayload(
                        basic={"name": "Must roll back"},
                        target_level=1,
                    )
                ),
            )
        assert _count(engine, character_build_drafts) == 0
        assert _count(engine, room_builder_drafts) == 0
    finally:
        engine.dispose()


def test_bound_core_confirm_rolls_back_character_and_confirm_marker_with_outer_failure() -> None:
    engine = _engine()
    registry = load_default_content_registry()
    room_id = uuid4()
    draft_id = uuid4()
    _seed_room(engine, room_id)
    payload = BuilderDraftPayload(target_level=10)
    with engine.begin() as connection:
        connection.execute(
            insert(character_build_drafts).values(
                id=draft_id,
                mode="create",
                character_id=None,
                base_version_id=None,
                revision=1,
                draft_payload=payload.model_dump(mode="json"),
                confirmed_character_id=None,
                confirmed_version_id=None,
                confirmed_at=None,
            )
        )
        RoomWorkspaceRepository.attach_draft_in_transaction(
            connection,
            room_id=room_id,
            draft_id=draft_id,
        )

    build = build_p0_fighter_wizard_fixture()
    state = build_p0_fighter_wizard_state(build)
    try:
        with pytest.raises(RoomWorkspaceAssociationConflictError):
            with engine.begin() as connection:
                bound_engine = cast(Engine, TransactionBoundEngine(connection))
                repository = CharacterRepository(bound_engine, registry)
                character = repository.create_character_from_builder_draft(
                    draft_id=draft_id,
                    expected_revision=1,
                    name=P0_FIXTURE_NAME,
                    build=build,
                    state=state,
                )
                _FailCharacterAssociation(engine).ensure_character_in_transaction(
                    connection,
                    room_id=room_id,
                    character_id=character.id,
                )

        assert _count(engine, characters) == 0
        assert _count(engine, character_versions) == 0
        assert _count(engine, character_states) == 0
        assert _count(engine, room_characters) == 0
        with engine.connect() as connection:
            row = connection.execute(
                select(
                    character_build_drafts.c.confirmed_character_id,
                    character_build_drafts.c.confirmed_version_id,
                    character_build_drafts.c.confirmed_at,
                ).where(character_build_drafts.c.id == draft_id)
            ).mappings().one()
        assert row["confirmed_character_id"] is None
        assert row["confirmed_version_id"] is None
        assert row["confirmed_at"] is None
    finally:
        engine.dispose()
