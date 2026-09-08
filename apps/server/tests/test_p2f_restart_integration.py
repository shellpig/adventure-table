from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.character_builder.schemas import BuilderBasicInput, BuilderDraftCreateInput
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.schemas import CreateRoomRequest
from app.domain.rooms.seats import ControllerKind, SeatControllerPatch, SeatCreate, SeatRole, SeatService
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionService, SessionStatus
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.workspace import RoomWorkspaceRepository


def _engine(database_path: Path):
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path.resolve().as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _create_session_lobby(
    *,
    room_id,
    campaign_id,
    access_session_id,
    character_id,
    seats: SeatService,
):
    dm_seat = seats.create_seat(
        room_id,
        campaign_id,
        SeatCreate(role=SeatRole.DM),
    )
    seats.set_controller(
        room_id,
        campaign_id,
        dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=access_session_id,
        ),
    )
    player_seat = seats.create_seat(
        room_id,
        campaign_id,
        SeatCreate(role=SeatRole.PLAYER, label="Mira"),
    )
    seats.select_character(room_id, campaign_id, player_seat.id, character_id)
    return dm_seat, player_seat


def test_p2f_restart_preserves_full_room_campaign_session_workspace_graph(tmp_path: Path) -> None:
    database_path = tmp_path / "p2f-restart.sqlite3"

    engine1 = _engine(database_path)
    metadata.create_all(engine1)
    registry1 = load_default_content_registry()
    room_repository1 = RoomRepository(engine1)
    rooms1 = RoomService(room_repository1)
    room_a = rooms1.create_room(
        CreateRoomRequest(name="Restart Room A", password="secret-a", display_name="Owner A")
    )
    room_b = rooms1.create_room(
        CreateRoomRequest(name="Restart Room B", password="secret-b", display_name="Owner B")
    )

    build = build_p0_fighter_wizard_fixture()
    characters1 = CharacterRepository(engine1, registry1)
    mira = characters1.create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    archived_character = characters1.create_character(
        name="Archived Rowan",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    workspace1 = RoomWorkspaceRepository(engine1)
    workspace1.attach_character(room_id=room_a.room.id, character_id=mira.id)
    workspace1.attach_character(room_id=room_b.room.id, character_id=archived_character.id)
    characters1.set_archived(archived_character.id, True)

    drafts1 = BuilderDraftRepository(engine1)
    open_draft = drafts1.create_draft(
        BuilderDraftCreateInput(
            draft_payload={"basic": {"name": "Restart Open Draft"}},
        )
    )
    workspace1.attach_draft(room_id=room_b.room.id, draft_id=open_draft.id)

    campaigns1 = CampaignService(CampaignRepository(engine1))
    history_campaign = campaigns1.create_campaign(
        room_a.room.id,
        CampaignCreate(name="Ended History", ruleset="dnd5e-2014"),
    )
    live_campaign = campaigns1.create_campaign(
        room_a.room.id,
        CampaignCreate(name="Live Campaign", ruleset="dnd5e-2014"),
    )
    room_b_campaign = campaigns1.create_campaign(
        room_b.room.id,
        CampaignCreate(name="Room B Draft", ruleset="dnd5e-2014"),
    )
    for campaign in (history_campaign, live_campaign):
        campaigns1.set_status(room_a.room.id, campaign.id, CampaignStatus.ACTIVE)
        campaigns1.add_character(
            room_a.room.id,
            campaign.id,
            RosterAdd(character_id=mira.id),
        )

    seats1 = SeatService(SeatRepository(engine1))
    sessions1 = SessionService(SessionRepository(engine1))
    owner_a_context1 = rooms1.authenticate(room_a.room.id, room_a.access_token)

    campaigns1.select_campaign(room_a.room.id, history_campaign.id)
    _history_dm_seat, history_player_seat = _create_session_lobby(
        room_id=room_a.room.id,
        campaign_id=history_campaign.id,
        access_session_id=room_a.access_session_id,
        character_id=mira.id,
        seats=seats1,
    )
    ended_session = sessions1.start_session(
        room_a.room.id,
        history_campaign.id,
        owner_a_context1,
    )
    ended_session = sessions1.end_session(
        room_a.room.id,
        history_campaign.id,
        ended_session.id,
        owner_a_context1,
    )
    assert ended_session.status is SessionStatus.ENDED
    archived_history_seat = seats1.archive_seat(
        room_a.room.id,
        history_campaign.id,
        history_player_seat.id,
    )
    assert archived_history_seat.archived_at is not None

    campaigns1.select_campaign(room_a.room.id, live_campaign.id)
    _live_dm_seat, live_player_seat = _create_session_lobby(
        room_id=room_a.room.id,
        campaign_id=live_campaign.id,
        access_session_id=room_a.access_session_id,
        character_id=mira.id,
        seats=seats1,
    )
    active_session = sessions1.start_session(
        room_a.room.id,
        live_campaign.id,
        owner_a_context1,
    )
    assert active_session.status is SessionStatus.ACTIVE
    assert SessionRepository(engine1).lease_for_character(mira.id) is not None
    assert room_b_campaign.status is CampaignStatus.DRAFT
    engine1.dispose()

    # Restart with new Engine/service/repository instances only.  This is the
    # P2-F closeout dataset: two Rooms, three Campaigns, one Character shared by
    # two Rosters, ended + active Session history, an open Draft, an archived
    # Character, and an archived Seat still referenced by historical Session data.
    engine2 = _engine(database_path)
    registry2 = load_default_content_registry()
    room_repository2 = RoomRepository(engine2)
    rooms2 = RoomService(room_repository2)
    owner_a_context2 = rooms2.authenticate(room_a.room.id, room_a.access_token)
    assert rooms2.authenticate(room_b.room.id, room_b.access_token).access_session_id == room_b.access_session_id
    assert room_repository2.get_room(room_a.room.id).active_campaign_id == live_campaign.id

    campaigns2 = CampaignService(CampaignRepository(engine2))
    assert {campaign.id for campaign in campaigns2.list_campaigns(room_a.room.id)} == {
        history_campaign.id,
        live_campaign.id,
    }
    assert {campaign.id for campaign in campaigns2.list_campaigns(room_b.room.id)} == {
        room_b_campaign.id,
    }
    assert campaigns2.list_roster(room_a.room.id, history_campaign.id)[0].character_id == mira.id
    assert campaigns2.list_roster(room_a.room.id, live_campaign.id)[0].character_id == mira.id

    session_repository2 = SessionRepository(engine2)
    sessions2 = SessionService(session_repository2)
    persisted_ended = session_repository2.get(ended_session.id)
    assert persisted_ended is not None
    assert persisted_ended.status == SessionStatus.ENDED.value
    assert sessions2.resume(room_a.room.id, history_campaign.id).active_session is None

    resumed = sessions2.resume(room_a.room.id, live_campaign.id).active_session
    assert resumed is not None
    assert resumed.id == active_session.id
    assert resumed.status is SessionStatus.ACTIVE
    lease = session_repository2.lease_for_character(mira.id)
    assert lease is not None
    assert lease.session_id == active_session.id
    assert any(
        participant.seat_id == live_player_seat.id and participant.active_character_id == mira.id
        for participant in resumed.participants
    )

    persisted_history_seat = SeatRepository(engine2).get(history_player_seat.id)
    assert persisted_history_seat is not None
    assert persisted_history_seat.archived_at is not None
    assert any(
        participant.seat_id == history_player_seat.id
        for participant in session_repository2.list_participants(ended_session.id)
    )

    workspace2 = RoomWorkspaceRepository(engine2)
    assert workspace2.list_character_ids(room_b.room.id, archived=True) == (archived_character.id,)
    assert workspace2.list_draft_ids(room_b.room.id) == (open_draft.id,)

    drafts2 = BuilderDraftRepository(engine2)
    reloaded_draft = drafts2.load_draft(open_draft.id)
    updated_payload = reloaded_draft.draft_payload.model_copy(
        update={"basic": BuilderBasicInput(name="Restart Draft Updated")}
    )
    updated_draft = drafts2.update_draft_payload(
        open_draft.id,
        expected_revision=reloaded_draft.revision,
        draft_payload=updated_payload,
    )
    assert updated_draft.revision == reloaded_draft.revision + 1
    assert updated_draft.draft_payload.basic is not None
    assert updated_draft.draft_payload.basic.name == "Restart Draft Updated"

    characters2 = CharacterRepository(engine2, registry2)
    characters2.set_archived(archived_character.id, False)
    assert workspace2.list_character_ids(room_b.room.id) == (archived_character.id,)

    ended_after_restart = sessions2.end_session(
        room_a.room.id,
        live_campaign.id,
        active_session.id,
        owner_a_context2,
    )
    assert ended_after_restart.status is SessionStatus.ENDED
    assert session_repository2.lease_for_character(mira.id) is None
    engine2.dispose()
