from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_seat_service
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.seats import CampaignSeat, ControllerKind, PresenceStatus, SeatRole
from app.main import app
from app.persistence.rooms.seats import StoredSeat


class _ApiSeatService:
    def __init__(self, room_id: UUID, campaign_id: UUID, seat: StoredSeat) -> None:
        self.room_id = room_id
        self.campaign_id = campaign_id
        self.seat = seat
        self.character_calls: list[UUID | None] = []

    def get_scoped_seat(self, room_id: UUID, campaign_id: UUID, seat_id: UUID) -> StoredSeat:
        assert room_id == self.room_id
        assert campaign_id == self.campaign_id
        assert seat_id == self.seat.id
        return self.seat

    def create_seat(self, room_id, campaign_id, payload):
        return self._present(
            role=payload.role,
            controller_kind=ControllerKind.NONE,
            controller_access_session_id=None,
        )

    def set_controller(self, room_id, campaign_id, seat_id, payload):
        return self._present(role=SeatRole(self.seat.role))

    def select_character(self, room_id, campaign_id, seat_id, character_id):
        self.character_calls.append(character_id)
        return self._present(role=SeatRole.PLAYER, selected_character_id=character_id)

    def archive_seat(self, room_id, campaign_id, seat_id):
        return self._present(role=SeatRole(self.seat.role))

    def delete_seat(self, room_id, campaign_id, seat_id):
        return None

    def _present(
        self,
        *,
        role: SeatRole,
        selected_character_id: UUID | None = None,
        controller_kind: ControllerKind | None = None,
        controller_access_session_id: UUID | None | object = ...,
    ) -> CampaignSeat:
        now = datetime.now(timezone.utc)
        if controller_kind is None:
            controller_kind = ControllerKind(self.seat.controller_kind)
        if controller_access_session_id is ...:
            controller_access_session_id = self.seat.controller_access_session_id
        return CampaignSeat(
            id=self.seat.id,
            campaign_id=self.campaign_id,
            role=role,
            label=None,
            controller_kind=controller_kind,
            controller_access_session_id=controller_access_session_id,
            controller_display_name=None,
            controller_authority=None,
            presence=PresenceStatus.NOT_APPLICABLE,
            selected_character_id=selected_character_id,
            archived_at=None,
            created_at=now,
            updated_at=now,
        )


@pytest.fixture
def seat_api_fixture():
    room_id = uuid4()
    campaign_id = uuid4()
    seat_id = uuid4()
    session_id = uuid4()
    now = datetime.now(timezone.utc)
    seat = StoredSeat(
        id=seat_id,
        campaign_id=campaign_id,
        role="player",
        label=None,
        controller_kind="human",
        controller_access_session_id=session_id,
        selected_character_id=None,
        archived_at=None,
        created_at=now,
        updated_at=now,
    )
    service = _ApiSeatService(room_id, campaign_id, seat)
    context = {
        "value": RoomAccessContext(
            room_id=room_id,
            access_session_id=session_id,
            authority=RoomAccessAuthority.MEMBER,
        )
    }

    app.dependency_overrides[get_room_access_context] = lambda: context["value"]
    app.dependency_overrides[get_seat_service] = lambda: service
    client = TestClient(app)
    try:
        yield room_id, campaign_id, seat, service, context, client
    finally:
        app.dependency_overrides.pop(get_room_access_context, None)
        app.dependency_overrides.pop(get_seat_service, None)


@pytest.mark.parametrize(
    ("authority", "role", "expected_status", "expected_code"),
    [
        (RoomAccessAuthority.MEMBER, "player", 403, "seat_management_authority_required"),
        (RoomAccessAuthority.DM, "player", 201, None),
        (RoomAccessAuthority.OWNER, "player", 201, None),
        (RoomAccessAuthority.MEMBER, "dm", 403, "room_owner_required"),
        (RoomAccessAuthority.DM, "dm", 403, "room_owner_required"),
        (RoomAccessAuthority.OWNER, "dm", 201, None),
    ],
)
def test_create_seat_http_permission_matrix(
    seat_api_fixture,
    authority: RoomAccessAuthority,
    role: str,
    expected_status: int,
    expected_code: str | None,
) -> None:
    room_id, campaign_id, _seat, _service, context, client = seat_api_fixture
    context["value"] = RoomAccessContext(
        room_id=room_id,
        access_session_id=uuid4(),
        authority=authority,
    )
    response = client.post(
        f"/api/rooms/{room_id}/campaigns/{campaign_id}/seats",
        json={"role": role},
    )
    assert response.status_code == expected_status
    if expected_code is not None:
        assert response.json()["error"]["code"] == expected_code


def test_member_cannot_operate_another_members_player_seat_via_http(seat_api_fixture) -> None:
    room_id, campaign_id, seat, _service, context, client = seat_api_fixture
    context["value"] = RoomAccessContext(
        room_id=room_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.MEMBER,
    )
    response = client.patch(
        f"/api/rooms/{room_id}/campaigns/{campaign_id}/seats/{seat.id}/character",
        json={"selected_character_id": str(uuid4())},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "seat_controller_required"


def test_dm_cannot_reassign_dm_seat_via_http(seat_api_fixture) -> None:
    room_id, campaign_id, seat, service, context, client = seat_api_fixture
    context["value"] = RoomAccessContext(
        room_id=room_id,
        access_session_id=uuid4(),
        authority=RoomAccessAuthority.DM,
    )
    service.seat = StoredSeat(**{**seat.__dict__, "role": "dm"})
    response = client.patch(
        f"/api/rooms/{room_id}/campaigns/{campaign_id}/seats/{seat.id}/controller",
        json={
            "controller_kind": "human",
            "controller_access_session_id": str(context["value"].access_session_id),
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "room_owner_required"


def test_assigned_member_can_select_character_on_own_player_seat_via_http(seat_api_fixture) -> None:
    room_id, campaign_id, seat, service, _context, client = seat_api_fixture
    character_id = uuid4()
    response = client.patch(
        f"/api/rooms/{room_id}/campaigns/{campaign_id}/seats/{seat.id}/character",
        json={"selected_character_id": str(character_id)},
    )
    assert response.status_code == 200
    assert response.json()["selected_character_id"] == str(character_id)
    assert service.character_calls == [character_id]
