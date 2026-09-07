from __future__ import annotations

from uuid import uuid4

from sqlalchemy import create_engine, event, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.service import RoomService
from app.persistence.characters import CharacterRepository, characters
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.tables import campaign_roster_entries, campaigns, rooms
from app.persistence.rooms.workspace import RoomWorkspaceRepository


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


def _count(engine, table) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(table)) or 0)


def test_roster_fk_restricts_direct_character_delete_and_room_delete_cleans_history_first() -> None:
    engine = _engine()
    registry = load_default_content_registry()
    room_service = RoomService(RoomRepository(engine))
    room_a = room_service.create_room(CreateRoomRequest(name="Delete Me", password="secret1"))
    room_b = room_service.create_room(CreateRoomRequest(name="Keep Me", password="secret2"))
    workspace = RoomWorkspaceRepository(engine)
    character_repository = CharacterRepository(engine, registry)
    build = build_p0_fighter_wizard_fixture()
    state = build_p0_fighter_wizard_state(build)
    try:
        char_a = character_repository.create_character(name="A", build=build, state=state)
        char_b = character_repository.create_character(name="B", build=build, state=state)
        workspace.attach_character(room_id=room_a.room.id, character_id=char_a.id)
        workspace.attach_character(room_id=room_b.room.id, character_id=char_b.id)
        campaign_a = uuid4()
        campaign_b = uuid4()
        with engine.begin() as connection:
            connection.execute(insert(campaigns).values(
                id=campaign_a,
                room_id=room_a.room.id,
                name="Delete Campaign",
                ruleset="dnd5e-2014",
                status="active",
            ))
            connection.execute(insert(campaigns).values(
                id=campaign_b,
                room_id=room_b.room.id,
                name="Keep Campaign",
                ruleset="dnd5e-2014",
                status="active",
            ))
            connection.execute(insert(campaign_roster_entries).values(
                campaign_id=campaign_a,
                character_id=char_a.id,
                status="active",
            ))
            connection.execute(insert(campaign_roster_entries).values(
                campaign_id=campaign_b,
                character_id=char_b.id,
                status="active",
            ))
            connection.execute(
                update(rooms)
                .where(rooms.c.id == room_a.room.id)
                .values(active_campaign_id=campaign_a)
            )
            connection.execute(
                update(rooms)
                .where(rooms.c.id == room_b.room.id)
                .values(active_campaign_id=campaign_b)
            )

        with engine.begin() as connection:
            try:
                connection.execute(characters.delete().where(characters.c.id == char_a.id))
            except IntegrityError:
                pass
            else:
                raise AssertionError("Campaign Roster history must RESTRICT direct Character delete")

        removed = workspace.hard_delete_room(room_a.room.id)
        assert removed.characters == 1
        assert _count(engine, rooms) == 1
        assert _count(engine, campaigns) == 1
        assert _count(engine, campaign_roster_entries) == 1
        assert _count(engine, characters) == 1
        with engine.connect() as connection:
            assert connection.scalar(select(rooms.c.active_campaign_id).where(rooms.c.id == room_b.room.id)) == campaign_b
            assert connection.scalar(select(campaigns.c.id)) == campaign_b
            assert connection.scalar(select(campaign_roster_entries.c.character_id)) == char_b.id
    finally:
        engine.dispose()
