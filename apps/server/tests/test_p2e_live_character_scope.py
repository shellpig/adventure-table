from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_room_workspace_service
from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import build_p0_fighter_wizard_fixture, build_p0_fighter_wizard_state
from app.domain.rooms.campaigns import CampaignCreate, CampaignService, CampaignStatus, RosterAdd
from app.domain.rooms.schemas import CreateRoomRequest, EnterRoomRequest
from app.domain.rooms.seats import ControllerKind, SeatControllerPatch, SeatCreate, SeatRole, SeatService
from app.domain.rooms.service import RoomService
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.main import app
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.seats import SeatRepository
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.sessions import SessionRepository
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


def _setup_live_table(engine):
    registry = load_default_content_registry()
    rooms = RoomService(RoomRepository(engine))
    owner = rooms.create_room(
        CreateRoomRequest(name="P2-E live scope", password="secret", display_name="Owner")
    )
    dm = rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            elevated_key=owner.dm_key,
            display_name="Current DM",
        ),
        remote_addr="127.0.0.2",
    )
    other_dm = rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            elevated_key=owner.dm_key,
            display_name="Other DM",
        ),
        remote_addr="127.0.0.3",
    )
    player_a = rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            display_name="Player A",
        ),
        remote_addr="127.0.0.4",
    )
    player_b = rooms.enter_room(
        EnterRoomRequest(
            code=owner.room.code,
            password="secret",
            display_name="Player B",
        ),
        remote_addr="127.0.0.5",
    )

    build = build_p0_fighter_wizard_fixture()
    characters = CharacterRepository(engine, registry)
    workspace_repository = RoomWorkspaceRepository(engine)
    mira = characters.create_character(
        name="Mira",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    serena = characters.create_character(
        name="Serena",
        build=build,
        state=build_p0_fighter_wizard_state(build),
    )
    for character in (mira, serena):
        workspace_repository.attach_character(
            room_id=owner.room.id,
            character_id=character.id,
        )

    campaigns = CampaignService(CampaignRepository(engine))
    campaign = campaigns.create_campaign(
        owner.room.id,
        CampaignCreate(name="Campaign", ruleset="dnd5e-2014"),
    )
    campaigns.set_status(owner.room.id, campaign.id, CampaignStatus.ACTIVE)
    campaigns.select_campaign(owner.room.id, campaign.id)
    for character in (mira, serena):
        campaigns.add_character(
            owner.room.id,
            campaign.id,
            RosterAdd(character_id=character.id),
        )

    seats = SeatService(SeatRepository(engine))
    dm_seat = seats.create_seat(
        owner.room.id,
        campaign.id,
        SeatCreate(role=SeatRole.DM),
    )
    seats.set_controller(
        owner.room.id,
        campaign.id,
        dm_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=dm.access_session_id,
        ),
    )
    player_seat = seats.create_seat(
        owner.room.id,
        campaign.id,
        SeatCreate(role=SeatRole.PLAYER),
    )
    seats.select_character(owner.room.id, campaign.id, player_seat.id, mira.id)
    seats.set_controller(
        owner.room.id,
        campaign.id,
        player_seat.id,
        SeatControllerPatch(
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=player_a.access_session_id,
        ),
    )

    sessions = SessionService(SessionRepository(engine), SessionLiveRepository(engine))
    dm_context = rooms.authenticate(owner.room.id, dm.access_token)
    started = sessions.start_session(owner.room.id, campaign.id, dm_context)
    return {
        "registry": registry,
        "rooms": rooms,
        "owner": owner,
        "dm": dm,
        "other_dm": other_dm,
        "player_a": player_a,
        "player_b": player_b,
        "campaign": campaign,
        "mira": mira,
        "serena": serena,
        "seats": seats,
        "player_seat": player_seat,
        "sessions": sessions,
        "started": started,
        "workspace": RoomCharacterWorkspaceService(engine, registry),
    }


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def test_live_character_state_http_scope_tracks_current_player_controller_and_fixed_dm() -> None:
    engine = _engine()
    try:
        data = _setup_live_table(engine)
        rooms = data["rooms"]
        owner = data["owner"]
        dm = data["dm"]
        other_dm = data["other_dm"]
        player_a = data["player_a"]
        player_b = data["player_b"]
        mira = data["mira"]
        serena = data["serena"]
        campaign = data["campaign"]
        seats = data["seats"]
        player_seat = data["player_seat"]
        context = {
            "value": rooms.authenticate(owner.room.id, owner.access_token)
        }
        app.dependency_overrides[get_room_access_context] = lambda: context["value"]
        app.dependency_overrides[get_room_workspace_service] = lambda: data["workspace"]
        client = TestClient(app)
        state_url = f"/api/rooms/{owner.room.id}/characters/{mira.id}/state"

        denied = client.patch(state_url, json={"current_hp": mira.state.current_hp})
        assert denied.status_code == 409
        assert _error_code(denied) == "character_in_active_session"

        context["value"] = rooms.authenticate(owner.room.id, other_dm.access_token)
        denied = client.patch(state_url, json={"current_hp": mira.state.current_hp})
        assert denied.status_code == 409
        assert _error_code(denied) == "character_in_active_session"

        context["value"] = rooms.authenticate(owner.room.id, player_a.access_token)
        allowed = client.patch(state_url, json={"current_hp": mira.state.current_hp})
        assert allowed.status_code == 200

        context["value"] = rooms.authenticate(owner.room.id, dm.access_token)
        allowed = client.patch(state_url, json={"current_hp": mira.state.current_hp})
        assert allowed.status_code == 200

        seats.set_controller(
            owner.room.id,
            campaign.id,
            player_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=player_b.access_session_id,
            ),
        )
        control = SessionLiveRepository(engine).control_for_character(mira.id)
        assert control is not None
        assert control.player_controller_access_session_id == player_b.access_session_id

        context["value"] = rooms.authenticate(owner.room.id, player_a.access_token)
        denied = client.patch(state_url, json={"current_hp": mira.state.current_hp})
        assert denied.status_code == 409
        assert _error_code(denied) == "character_in_active_session"

        context["value"] = rooms.authenticate(owner.room.id, player_b.access_token)
        allowed = client.patch(state_url, json={"current_hp": mira.state.current_hp})
        assert allowed.status_code == 200

        context["value"] = rooms.authenticate(owner.room.id, owner.access_token)
        unleased_url = f"/api/rooms/{owner.room.id}/characters/{serena.id}/state"
        allowed = client.patch(unleased_url, json={"current_hp": serena.state.current_hp})
        assert allowed.status_code == 200
    finally:
        app.dependency_overrides.pop(get_room_access_context, None)
        app.dependency_overrides.pop(get_room_workspace_service, None)
        engine.dispose()


def test_active_character_cannot_be_archived_until_session_releases_lease() -> None:
    engine = _engine()
    try:
        data = _setup_live_table(engine)
        rooms = data["rooms"]
        owner = data["owner"]
        dm = data["dm"]
        campaign = data["campaign"]
        mira = data["mira"]
        serena = data["serena"]
        context = {
            "value": rooms.authenticate(owner.room.id, dm.access_token)
        }
        app.dependency_overrides[get_room_access_context] = lambda: context["value"]
        app.dependency_overrides[get_room_workspace_service] = lambda: data["workspace"]
        client = TestClient(app)

        active_archive = client.post(
            f"/api/rooms/{owner.room.id}/characters/{mira.id}/archive"
        )
        assert active_archive.status_code == 409
        assert _error_code(active_archive) == "character_in_active_session"

        unleased_archive = client.post(
            f"/api/rooms/{owner.room.id}/characters/{serena.id}/archive"
        )
        assert unleased_archive.status_code == 200

        data["sessions"].end_session(
            owner.room.id,
            campaign.id,
            data["started"].id,
            rooms.authenticate(owner.room.id, dm.access_token),
        )
        released_archive = client.post(
            f"/api/rooms/{owner.room.id}/characters/{mira.id}/archive"
        )
        assert released_archive.status_code == 200
    finally:
        app.dependency_overrides.pop(get_room_access_context, None)
        app.dependency_overrides.pop(get_room_workspace_service, None)
        engine.dispose()


def test_versioned_builder_mutations_use_same_live_character_scope() -> None:
    engine = _engine()
    try:
        data = _setup_live_table(engine)
        rooms = data["rooms"]
        owner = data["owner"]
        player_a = data["player_a"]
        mira = data["mira"]
        context = {
            "value": rooms.authenticate(owner.room.id, owner.access_token)
        }
        app.dependency_overrides[get_room_access_context] = lambda: context["value"]
        app.dependency_overrides[get_room_workspace_service] = lambda: data["workspace"]
        client = TestClient(app)
        base = f"/api/rooms/{owner.room.id}/character-builder"

        denied = client.post(
            f"{base}/characters/{mira.id}/drafts",
            json={"mode": "build_edit"},
        )
        assert denied.status_code == 409
        assert _error_code(denied) == "character_in_active_session"

        disabled = client.post(
            f"{base}/drafts",
            json={
                "mode": "build_edit",
                "character_id": str(mira.id),
                "base_version_id": str(mira.current_version_id),
            },
        )
        assert disabled.status_code == 422
        assert _error_code(disabled) == "builder_mode_not_enabled"

        context["value"] = rooms.authenticate(owner.room.id, player_a.access_token)
        created = client.post(
            f"{base}/characters/{mira.id}/drafts",
            json={"mode": "build_edit"},
        )
        assert created.status_code == 201
        draft_id = created.json()["draft"]["id"]

        context["value"] = rooms.authenticate(owner.room.id, owner.access_token)
        denied = client.patch(
            f"{base}/drafts/{draft_id}",
            json={
                "expected_revision": 1,
                "draft_payload": {"basic": {"name": "Blocked rename"}},
            },
        )
        assert denied.status_code == 409
        assert _error_code(denied) == "character_in_active_session"

        denied = client.post(f"{base}/drafts/{draft_id}/confirm")
        assert denied.status_code == 409
        assert _error_code(denied) == "character_in_active_session"

        denied = client.delete(f"{base}/drafts/{draft_id}")
        assert denied.status_code == 409
        assert _error_code(denied) == "character_in_active_session"

        context["value"] = rooms.authenticate(owner.room.id, player_a.access_token)
        allowed = client.delete(f"{base}/drafts/{draft_id}")
        assert allowed.status_code == 204
    finally:
        app.dependency_overrides.pop(get_room_access_context, None)
        app.dependency_overrides.pop(get_room_workspace_service, None)
        engine.dispose()
