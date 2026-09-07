from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_seat_service
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.seats import CampaignSeat, ControllerKind, PresenceStatus, SeatRole
from app.main import app
from app.persistence.rooms.seats import StoredSeat


class _OwnerDmSeatService:
    def __init__(self, room_id: UUID, campaign_id: UUID, seat: StoredSeat) -> None:
        self.room_id = room_id
        self.campaign_id = campaign_id
        self.seat = seat
        self.controller_calls: list[UUID] = []

    def get_scoped_seat(self, room_id: UUID, campaign_id: UUID, seat_id: UUID) -> StoredSeat:
        assert room_id == self.room_id
        assert campaign_id == self.campaign_id
        assert seat_id == self.seat.id
        return self.seat

    def set_controller(self, room_id, campaign_id, seat_id, payload):
        assert payload.controller_kind is ControllerKind.HUMAN
        assert payload.controller_access_session_id is not None
        self.controller_calls.append(payload.controller_access_session_id)
        now = datetime.now(timezone.utc)
        return CampaignSeat(
            id=self.seat.id,
            campaign_id=self.campaign_id,
            role=SeatRole.DM,
            label="DM",
            controller_kind=ControllerKind.HUMAN,
            controller_access_session_id=payload.controller_access_session_id,
            controller_display_name=None,
            controller_authority=RoomAccessAuthority.DM,
            presence=PresenceStatus.CONNECTED,
            selected_character_id=None,
            archived_at=None,
            created_at=now,
            updated_at=now,
        )


def test_owner_can_reassign_dm_seat_from_dm_a_to_dm_b_via_http() -> None:
    room_id = uuid4()
    campaign_id = uuid4()
    seat_id = uuid4()
    owner_access_id = uuid4()
    now = datetime.now(timezone.utc)
    seat = StoredSeat(
        id=seat_id,
        campaign_id=campaign_id,
        role="dm",
        label="DM",
        controller_kind="none",
        controller_access_session_id=None,
        selected_character_id=None,
        archived_at=None,
        created_at=now,
        updated_at=now,
    )
    service = _OwnerDmSeatService(room_id, campaign_id, seat)
    context = RoomAccessContext(
        room_id=room_id,
        access_session_id=owner_access_id,
        authority=RoomAccessAuthority.OWNER,
    )
    app.dependency_overrides[get_room_access_context] = lambda: context
    app.dependency_overrides[get_seat_service] = lambda: service
    client = TestClient(app)
    dm_a = uuid4()
    dm_b = uuid4()
    try:
        for controller_id in (dm_a, dm_b):
            response = client.patch(
                f"/api/rooms/{room_id}/campaigns/{campaign_id}/seats/{seat_id}/controller",
                json={
                    "controller_kind": "human",
                    "controller_access_session_id": str(controller_id),
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["controller_access_session_id"] == str(controller_id)
        assert service.controller_calls == [dm_a, dm_b]
    finally:
        app.dependency_overrides.pop(get_room_access_context, None)
        app.dependency_overrides.pop(get_seat_service, None)
