from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import Engine

from app.persistence.builder_drafts import character_build_drafts
from app.persistence.characters import characters
from app.persistence.rooms.tables import room_builder_drafts, room_characters, rooms
from app.persistence.rooms.workspace import (
    RoomWorkspaceAssociationConflictError,
    RoomWorkspaceRepository,
)


POSTGRES_URL = os.environ.get("P2_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P2_POSTGRES_URL is only supplied by the P2 Non-E2E PostgreSQL job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    return config


def _reset_and_upgrade() -> Engine:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_config(), "heads")
    return engine


@pytest.fixture()
def postgres_engine():
    engine = _reset_and_upgrade()
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_room(connection, room_id: UUID, code: str) -> None:
    now = datetime.now(timezone.utc)
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code=code,
            name=f"P2-B PostgreSQL {code}",
            password_salt=b"s" * 32,
            password_hash=b"p" * 64,
            owner_key_hash=b"o" * 32,
            dm_key_hash=b"d" * 32,
            created_at=now,
            updated_at=now,
        )
    )


def _seed_character(connection, character_id: UUID) -> None:
    connection.execute(
        insert(characters).values(
            id=character_id,
            name="P2-B concurrent character",
            ruleset="dnd5e-2014",
            current_version_id=None,
            archived_at=None,
        )
    )


def _seed_draft(connection, draft_id: UUID) -> None:
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


@pytest.mark.parametrize("resource_kind", ["character", "draft"])
def test_concurrent_cross_room_association_has_exactly_one_winner(
    postgres_engine: Engine,
    resource_kind: str,
) -> None:
    room_a = uuid4()
    room_b = uuid4()
    resource_id = uuid4()
    with postgres_engine.begin() as connection:
        _seed_room(connection, room_a, "P2BRA00001")
        _seed_room(connection, room_b, "P2BRB00002")
        if resource_kind == "character":
            _seed_character(connection, resource_id)
        else:
            _seed_draft(connection, resource_id)

    start = Barrier(2)

    def attach(room_id: UUID) -> str:
        try:
            with postgres_engine.begin() as connection:
                start.wait(timeout=10)
                if resource_kind == "character":
                    RoomWorkspaceRepository.attach_character_in_transaction(
                        connection,
                        room_id=room_id,
                        character_id=resource_id,
                    )
                else:
                    RoomWorkspaceRepository.attach_draft_in_transaction(
                        connection,
                        room_id=room_id,
                        draft_id=resource_id,
                    )
            return "ok"
        except RoomWorkspaceAssociationConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            future.result(timeout=20)
            for future in (
                executor.submit(attach, room_a),
                executor.submit(attach, room_b),
            )
        ]

    assert sorted(outcomes) == ["conflict", "ok"]
    table = room_characters if resource_kind == "character" else room_builder_drafts
    resource_column = table.c.character_id if resource_kind == "character" else table.c.draft_id
    with postgres_engine.connect() as connection:
        rows = connection.execute(
            select(table.c.room_id).where(resource_column == resource_id)
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0] in {room_a, room_b}


def test_concurrent_legacy_claim_never_splits_unscoped_workspace_data(
    postgres_engine: Engine,
) -> None:
    room_a = uuid4()
    room_b = uuid4()
    character_ids = (uuid4(), uuid4())
    draft_ids = (uuid4(), uuid4())
    with postgres_engine.begin() as connection:
        _seed_room(connection, room_a, "P2BCL00001")
        _seed_room(connection, room_b, "P2BCL00002")
        for character_id in character_ids:
            _seed_character(connection, character_id)
        for draft_id in draft_ids:
            _seed_draft(connection, draft_id)

    start = Barrier(2)

    def claim(room_id: UUID) -> tuple[str, int, int]:
        repository = RoomWorkspaceRepository(postgres_engine)
        try:
            with postgres_engine.begin() as connection:
                start.wait(timeout=10)
                counts = repository.claim_all_unscoped_in_transaction(connection, room_id)
            return ("ok", counts.characters, counts.drafts)
        except RoomWorkspaceAssociationConflictError:
            return ("conflict", 0, 0)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            future.result(timeout=20)
            for future in (
                executor.submit(claim, room_a),
                executor.submit(claim, room_b),
            )
        ]

    with postgres_engine.connect() as connection:
        character_rooms = connection.execute(
            select(room_characters.c.room_id).order_by(room_characters.c.character_id)
        ).scalars().all()
        draft_rooms = connection.execute(
            select(room_builder_drafts.c.room_id).order_by(room_builder_drafts.c.draft_id)
        ).scalars().all()

    assert len(character_rooms) == len(character_ids)
    assert len(draft_rooms) == len(draft_ids)
    winning_rooms = set(character_rooms) | set(draft_rooms)
    assert len(winning_rooms) == 1
    assert winning_rooms <= {room_a, room_b}

    counts = RoomWorkspaceRepository(postgres_engine).legacy_counts()
    assert counts.characters == 0
    assert counts.drafts == 0
    assert any(outcome == ("ok", len(character_ids), len(draft_ids)) for outcome in outcomes)
    assert all(
        outcome == ("ok", 0, 0)
        or outcome == ("ok", len(character_ids), len(draft_ids))
        or outcome[0] == "conflict"
        for outcome in outcomes
    )
