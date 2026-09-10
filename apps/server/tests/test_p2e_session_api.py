from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_session_resume_service, get_session_service
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.sessions import (
    CharacterAlreadyInActiveSessionError,
    DMControllerMismatchError,
    SessionActiveCharacterLockedError,
    SessionAlreadyActiveError,
    SessionLateJoinError,
    SessionLobbyUnavailableError,
    SessionNotActiveError,
    SessionNotFoundError,
    SessionSnapshot,
    SessionStatus,
)
from app.main import app


class _ApiSessionService:
    def __init__(self, room_id: UUID, campaign_id: UUID) -> None:
        self.room_id = room_id
        self.campaign_id = campaign_id
        self.start_error: Exception | None = None
        self.get_error: Exception | None = None
        self.late_join_error: Exception | None = None
        self.active_character_error: Exception | None = None
        self.end_error: Exception | None = None
        self.abandon_error: Exception | None = None

    def start_session(self, room_id, campaign_id, context):
        assert room_id == self.room_id
        assert campaign_id == self.campaign_id
        if self.start_error is not None:
            raise self.start_error
        return _snapshot(campaign_id)

    def get_session(self, room_id, campaign_id, session_id):
        assert room_id == self.room_id
        assert campaign_id == self.campaign_id
        if self.get_error is not None:
            raise self.get_error
        return _snapshot(campaign_id, session_id=session_id)

    def late_join(self, room_id, campaign_id, session_id, payload, context):
        assert room_id == self.room_id
        assert campaign_id == self.campaign_id
        if self.late_join_error is not None:
            raise self.late_join_error
        return _snapshot(campaign_id, session_id=session_id)

    def assert_active_character_locked(
        self,
        room_id,
        campaign_id,
        session_id,
        participant_id,
        payload,
    ):
        assert room_id == self.room_id
        assert campaign_id == self.campaign_id
        if self.active_character_error is not None:
            raise self.active_character_error
        raise SessionActiveCharacterLockedError("locked")

    def end_session(self, room_id, campaign_id, session_id, context):
        assert room_id == self.room_id
        assert campaign_id == self.campaign_id
        if self.end_error is not None:
            raise self.end_error
        return _snapshot(campaign_id, session_id=session_id, status=SessionStatus.ENDED)

    def abandon_session(self, room_id, campaign_id, session_id, context):
        assert room_id == self.room_id
        assert campaign_id == self.campaign_id
        if self.abandon_error is not None:
            raise self.abandon_error
        return _snapshot(campaign_id, session_id=session_id, status=SessionStatus.ABANDONED)


class _ApiSessionResumeService:
    def __init__(self, room_id: UUID, campaign_id: UUID) -> None:
        self.room_id = room_id
        self.campaign_id = campaign_id

    def resume(self, room_id, campaign_id, *, caller_access_session_id=None):
        assert room_id == self.room_id
        assert campaign_id == self.campaign_id
        self.caller_access_session_id = caller_access_session_id
        now = datetime.now(timezone.utc).isoformat()
        return {
            "room_id": room_id,
            "campaign_id": campaign_id,
            "room": {
                "id": room_id,
                "code": "ROOM01",
                "name": "Room",
                "active_campaign_id": campaign_id,
                "created_at": now,
                "updated_at": now,
            },
            "campaign": {
                "id": campaign_id,
                "room_id": room_id,
                "name": "Campaign",
                "ruleset": "dnd5e-2014",
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
            "active_session": None,
            "participants": [],
            "seats": [],
            "active_characters": [],
        }


def _snapshot(
    campaign_id: UUID,
    *,
    session_id: UUID | None = None,
    status: SessionStatus = SessionStatus.ACTIVE,
) -> SessionSnapshot:
    now = datetime.now(timezone.utc)
    return SessionSnapshot(
        id=session_id or uuid4(),
        campaign_id=campaign_id,
        status=status,
        dm_seat_id=uuid4(),
        dm_controller_kind="human",
        dm_controller_access_session_id=uuid4(),
        started_at=now,
        ended_at=now if status is not SessionStatus.ACTIVE else None,
        participants=[],
    )


@pytest.fixture
def session_api_fixture():
    room_id = uuid4()
    campaign_id = uuid4()
    context = RoomAccessContext(
        room_id=room_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.DM,
    )
    service = _ApiSessionService(room_id, campaign_id)
    resume_service = _ApiSessionResumeService(room_id, campaign_id)
    app.dependency_overrides[get_room_access_context] = lambda: context
    app.dependency_overrides[get_session_service] = lambda: service
    app.dependency_overrides[get_session_resume_service] = lambda: resume_service
    client = TestClient(app)
    try:
        yield room_id, campaign_id, service, client
    finally:
        app.dependency_overrides.pop(get_room_access_context, None)
        app.dependency_overrides.pop(get_session_service, None)
        app.dependency_overrides.pop(get_session_resume_service, None)


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (DMControllerMismatchError("not assigned"), 403, "dm_controller_mismatch"),
        (SessionAlreadyActiveError("active"), 409, "session_already_active"),
        (
            CharacterAlreadyInActiveSessionError("leased"),
            409,
            "character_already_in_active_session",
        ),
        (SessionLobbyUnavailableError("bad lobby"), 409, "lobby_unavailable"),
    ],
)
def test_start_session_http_error_contract(
    session_api_fixture,
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    room_id, campaign_id, service, client = session_api_fixture
    service.start_error = error
    response = client.post(f"/api/rooms/{room_id}/campaigns/{campaign_id}/sessions")
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_session_http_error_contract_covers_read_join_lock_and_finalize(session_api_fixture) -> None:
    room_id, campaign_id, service, client = session_api_fixture
    prefix = f"/api/rooms/{room_id}/campaigns/{campaign_id}/sessions"
    session_id = uuid4()
    participant_id = uuid4()
    seat_id = uuid4()
    character_id = uuid4()

    service.get_error = SessionNotFoundError(session_id)
    response = client.get(f"{prefix}/{session_id}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "session_not_found"
    service.get_error = None

    service.late_join_error = DMControllerMismatchError("not current DM")
    response = client.post(f"{prefix}/{session_id}/late-join", json={"seat_id": str(seat_id)})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "dm_controller_mismatch"

    service.late_join_error = SessionLateJoinError("invalid seat")
    response = client.post(f"{prefix}/{session_id}/late-join", json={"seat_id": str(seat_id)})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "seat_character_invalid"

    service.late_join_error = CharacterAlreadyInActiveSessionError("leased")
    response = client.post(f"{prefix}/{session_id}/late-join", json={"seat_id": str(seat_id)})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "character_already_in_active_session"

    service.active_character_error = SessionActiveCharacterLockedError("locked")
    response = client.patch(
        f"{prefix}/{session_id}/participants/{participant_id}/character",
        json={"active_character_id": str(character_id)},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_active_character_locked"

    service.end_error = SessionNotActiveError(session_id)
    response = client.post(f"{prefix}/{session_id}/end")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "session_not_active"

    service.abandon_error = DMControllerMismatchError("not allowed")
    response = client.post(f"{prefix}/{session_id}/abandon")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "dm_controller_mismatch"


def test_session_routes_expose_start_resume_late_join_lock_end_and_abandon(session_api_fixture) -> None:
    room_id, campaign_id, _service, client = session_api_fixture
    prefix = f"/api/rooms/{room_id}/campaigns/{campaign_id}/sessions"
    started = client.post(prefix)
    assert started.status_code == 201
    session_id = started.json()["id"]
    resumed = client.get(f"{prefix}/active")
    assert resumed.status_code == 200
    assert resumed.json()["room"]["id"] == str(room_id)
    assert resumed.json()["campaign"]["id"] == str(campaign_id)
    assert resumed.json()["participants"] == []
    assert resumed.json()["seats"] == []
    assert resumed.json()["active_characters"] == []
    assert client.get(f"{prefix}/{session_id}").status_code == 200

    late_join = client.post(
        f"{prefix}/{session_id}/late-join",
        json={"seat_id": str(uuid4())},
    )
    assert late_join.status_code == 200

    locked = client.patch(
        f"{prefix}/{session_id}/participants/{uuid4()}/character",
        json={"active_character_id": str(uuid4())},
    )
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "session_active_character_locked"

    assert client.post(f"{prefix}/{session_id}/end").json()["status"] == "ended"
    assert client.post(f"{prefix}/{session_id}/abandon").json()["status"] == "abandoned"
