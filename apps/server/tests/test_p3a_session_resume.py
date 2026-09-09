from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.seats import (
    ControllerKind,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.domain.rooms.service import RoomService
from app.domain.rooms.session_resume import SessionResumeService
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import (
    TableEventAppend,
    TableEventService,
    TableEventVisibility,
)
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.session_resume import SessionResumeRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
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


def _setup_active_session(engine):
    registry = load_default_content_registry()
    room_repository = RoomRepository(engine)
    rooms = RoomService(room_repository)
    owner = rooms.create_room(
        CreateRoomRequest(name="P3 Resume Room", password="secret", display_name="Owner")
    )
    dm = rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            elevated_key=owner.dm_key,
            display_name="DM",
        ),
        remote_addr="127.0.0.2",
    )

    characters = CharacterRepository(engine, registry)
    workspace = RoomWorkspaceRepository(engine)
    build = build_p0_fighter_wizard_fixture()
    created = []
    for name in ("Mira", "Serena"):
        character = characters.create_character(
            name=name,
            build=build,
            state=build_p0_fighter_wizard_state(build),
        )
        workspace.attach_character(room_id=owner.room.id, character_id=character.id)
        created.append(character)

    campaigns = CampaignService(CampaignRepository(engine))
    campaign = campaigns.create_campaign(
        owner.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(owner.room.id, campaign.id)
    for character in created:
        campaigns.add_character(
            owner.room.id,
            campaign.id,
            RosterAdd(character_id=character.id),
        )

    seats = SeatService(SeatRepository(engine))
    dm_seat = seats.create_seat(owner.room.id, campaign.id, SeatCreate(role=SeatRole.DM))
    seats.set_controller(
        owner.room.id,
        campaign.id,
        dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )
    for index, character in enumerate(created, start=1):
        player = seats.create_seat(
            owner.room.id,
            campaign.id,
            SeatCreate(role=SeatRole.PLAYER, label=f"Player {index}"),
        )
        seats.set_controller(
            owner.room.id,
            campaign.id,
            player.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=owner.access_session_id,
            ),
        )
        seats.select_character(owner.room.id, campaign.id, player.id, character.id)

    session_service = SessionService(SessionRepository(engine))
    dm_context = rooms.authenticate(owner.room.id, dm.access_token)
    started = session_service.start_session(owner.room.id, campaign.id, dm_context)
    return (
        rooms,
        owner,
        dm,
        created,
        room_repository,
        campaigns,
        seats,
        session_service,
        campaign,
        started,
        dm_context,
        characters,
    )


def test_p3_resume_batches_active_character_summary_and_includes_event_cursor() -> None:
    engine = _engine()
    try:
        (
            _rooms,
            owner,
            dm,
            created,
            room_repository,
            campaigns,
            seats,
            session_service,
            campaign,
            started,
            dm_context,
            characters,
        ) = _setup_active_session(engine)
        event_service = TableEventService(TableEventRepository(engine))
        dm_actor = event_service.resolve_human_actor(
            room_id=owner.room.id,
            campaign_id=campaign.id,
            session_id=started.id,
            context=dm_context,
        )
        event_service.append_event(
            dm_actor,
            TableEventAppend(
                kind="diagnostic.resume",
                visibility=TableEventVisibility.PUBLIC,
                payload={"ready": True},
                idempotency_key="resume-diagnostic-1",
            ),
        )

        character_summary_selects: list[str] = []

        @event.listens_for(engine, "before_cursor_execute")
        def _capture_character_summary_query(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            normalized = statement.lower()
            if normalized.lstrip().startswith("select") and "character_versions" in normalized:
                character_summary_selects.append(statement)

        resume = SessionResumeService(
            session_service=session_service,
            room_repository=room_repository,
            campaign_service=campaigns,
            seat_service=seats,
            character_repository=characters,
            summary_repository=SessionResumeRepository(engine),
            table_event_service=event_service,
        ).resume(
            owner.room.id,
            campaign.id,
            caller_access_session_id=dm.access_session_id,
        )

        assert resume.active_session is not None
        assert resume.active_session.id == started.id
        assert [summary.id for summary in resume.active_characters] == [
            participant.active_character_id
            for participant in started.participants
            if participant.active_character_id is not None
        ]
        assert {summary.name for summary in resume.active_characters} == {
            character.name for character in created
        }
        assert len(character_summary_selects) == 1

        assert resume.table_runtime is not None
        assert resume.table_runtime.last_event_seq == 1
        assert resume.table_runtime.revision == 1
        assert resume.recent_events is not None
        assert resume.recent_events.cursor == 1
        assert [item.kind for item in resume.recent_events.events] == ["diagnostic.resume"]
    finally:
        engine.dispose()


def test_room_member_outside_session_gets_no_p3_event_projection() -> None:
    engine = _engine()
    try:
        (
            rooms,
            owner,
            _dm,
            _created,
            room_repository,
            campaigns,
            seats,
            session_service,
            campaign,
            _started,
            _dm_context,
            characters,
        ) = _setup_active_session(engine)
        observer = rooms.enter_room(
            EnterRoomRequest(
                code=owner.room.code,
                password="secret",
                display_name="Observer without Seat",
            ),
            remote_addr="127.0.0.9",
        )
        resume = SessionResumeService(
            session_service=session_service,
            room_repository=room_repository,
            campaign_service=campaigns,
            seat_service=seats,
            character_repository=characters,
            summary_repository=SessionResumeRepository(engine),
            table_event_service=TableEventService(TableEventRepository(engine)),
        ).resume(
            owner.room.id,
            campaign.id,
            caller_access_session_id=observer.access_session_id,
        )

        assert resume.active_session is not None
        assert resume.table_runtime is None
        assert resume.recent_events is None
    finally:
        engine.dispose()
