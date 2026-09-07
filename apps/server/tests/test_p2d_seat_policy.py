from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.api.errors import APIError
from app.api.rooms.seats import (
    _require_dm_seat_management,
    _require_non_dm_seat_management,
    router,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.seats import (
    ControllerKind,
    PresenceStatus,
    SeatCampaignMismatchError,
    SeatCharacterSelectionError,
    SeatControllerError,
    SeatControllerPatch,
    SeatCreate,
    SeatRole,
    SeatService,
)
from app.persistence.rooms.seats import StoredSeat, StoredSeatAccessSession


def _context(authority: RoomAccessAuthority, *, session_id=None) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=uuid4(),
        access_session_id=session_id or uuid4(),
        authority=authority,
    )


def test_p2d_router_exposes_seat_and_lobby_but_no_session_surface() -> None:
    paths = {route.path for route in router.routes}
    assert "/api/rooms/{room_id}/campaigns/{campaign_id}/seats" in paths
    assert "/api/rooms/{room_id}/campaigns/{campaign_id}/lobby" in paths
    assert any(path.endswith("/seats/{seat_id}/controller") for path in paths)
    assert any(path.endswith("/seats/{seat_id}/character") for path in paths)
    assert not any("/sessions" in path for path in paths)


def test_dm_seat_assignment_is_owner_only_but_other_seat_management_allows_dm() -> None:
    with pytest.raises(APIError) as exc:
        _require_dm_seat_management(_context(RoomAccessAuthority.DM))
    assert exc.value.code == "room_owner_required"
    _require_dm_seat_management(_context(RoomAccessAuthority.OWNER))

    _require_non_dm_seat_management(_context(RoomAccessAuthority.DM))
    _require_non_dm_seat_management(_context(RoomAccessAuthority.OWNER))
    with pytest.raises(APIError) as exc:
        _require_non_dm_seat_management(_context(RoomAccessAuthority.MEMBER))
    assert exc.value.code == "seat_management_authority_required"


class _FakeSeatRepository:
    def __init__(self) -> None:
        self.room_id = uuid4()
        self.campaign_id = uuid4()
        self.status = "active"
        self.seats: dict = {}
        self.access: dict = {}
        self.roster: dict = {}
        self.archived_characters: set = set()

    def campaign_room_id(self, campaign_id):
        return self.room_id if campaign_id == self.campaign_id else None

    def campaign_status(self, campaign_id):
        return self.status if campaign_id == self.campaign_id else None

    def active_campaign_id(self, room_id):
        return self.campaign_id if room_id == self.room_id else None

    def get(self, seat_id):
        return self.seats.get(seat_id)

    def list_for_campaign(self, campaign_id, include_archived=False):
        seats = [seat for seat in self.seats.values() if seat.campaign_id == campaign_id]
        if not include_archived:
            seats = [seat for seat in seats if seat.archived_at is None]
        return tuple(seats)

    def create(self, *, campaign_id, role, label):
        now = datetime.now(timezone.utc)
        seat = StoredSeat(
            id=uuid4(),
            campaign_id=campaign_id,
            role=role,
            label=label,
            controller_kind="none",
            controller_access_session_id=None,
            selected_character_id=None,
            archived_at=None,
            created_at=now,
            updated_at=now,
        )
        self.seats[seat.id] = seat
        return seat

    def get_access_session(self, session_id):
        return self.access.get(session_id)

    def list_access_sessions(self, room_id):
        return tuple(
            access
            for access in self.access.values()
            if access.room_id == room_id and access.revoked_at is None
        )

    def set_controller(self, *, seat_id, controller_kind, controller_access_session_id):
        seat = self.seats.get(seat_id)
        if seat is None:
            return None
        updated = StoredSeat(
            **{
                **seat.__dict__,
                "controller_kind": controller_kind,
                "controller_access_session_id": controller_access_session_id,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.seats[seat_id] = updated
        return updated

    def roster_status(self, *, campaign_id, character_id):
        return self.roster.get((campaign_id, character_id))

    def character_is_archived(self, character_id):
        return character_id in self.archived_characters

    def character_selected_elsewhere(self, *, campaign_id, character_id, excluding_seat_id):
        return any(
            seat.campaign_id == campaign_id
            and seat.id != excluding_seat_id
            and seat.archived_at is None
            and seat.selected_character_id == character_id
            for seat in self.seats.values()
        )

    def set_selected_character(self, *, seat_id, character_id):
        seat = self.seats.get(seat_id)
        if seat is None:
            return None
        updated = StoredSeat(
            **{
                **seat.__dict__,
                "selected_character_id": character_id,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.seats[seat_id] = updated
        return updated

    def archive(self, seat_id):
        seat = self.seats.get(seat_id)
        if seat is None:
            return None
        now = datetime.now(timezone.utc)
        updated = StoredSeat(
            **{
                **seat.__dict__,
                "archived_at": now,
                "controller_kind": "none",
                "controller_access_session_id": None,
                "selected_character_id": None,
                "updated_at": now,
            }
        )
        self.seats[seat_id] = updated
        return updated

    def delete_unreferenced(self, seat_id):
        return self.seats.pop(seat_id, None) is not None


def _access(repo: _FakeSeatRepository, authority="member", *, seen_seconds_ago=0, room_id=None):
    session_id = uuid4()
    now = datetime.now(timezone.utc)
    access = StoredSeatAccessSession(
        id=session_id,
        room_id=room_id or repo.room_id,
        authority=authority,
        display_name=f"{authority}-controller",
        last_seen_at=now - timedelta(seconds=seen_seconds_ago),
        revoked_at=None,
    )
    repo.access[session_id] = access
    return access


def test_one_human_controller_can_bind_multiple_player_seats() -> None:
    repo = _FakeSeatRepository()
    service = SeatService(repo)
    access = _access(repo)
    seat_a = service.create_seat(repo.room_id, repo.campaign_id, SeatCreate(role=SeatRole.PLAYER))
    seat_b = service.create_seat(repo.room_id, repo.campaign_id, SeatCreate(role=SeatRole.PLAYER))

    for seat in (seat_a, seat_b):
        bound = service.set_controller(
            repo.room_id,
            repo.campaign_id,
            seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=access.id,
            ),
        )
        assert bound.controller_access_session_id == access.id


def test_ai_controller_is_domain_shape_only_and_cannot_be_bound_in_p2() -> None:
    repo = _FakeSeatRepository()
    service = SeatService(repo)
    seat = service.create_seat(repo.room_id, repo.campaign_id, SeatCreate(role=SeatRole.PLAYER))
    with pytest.raises(SeatControllerError):
        service.set_controller(
            repo.room_id,
            repo.campaign_id,
            seat.id,
            SeatControllerPatch(controller_kind=ControllerKind.AI),
        )


def test_dm_controller_must_have_dm_or_owner_room_authority() -> None:
    repo = _FakeSeatRepository()
    service = SeatService(repo)
    member = _access(repo, "member")
    dm_seat = service.create_seat(repo.room_id, repo.campaign_id, SeatCreate(role=SeatRole.DM))
    with pytest.raises(SeatControllerError):
        service.set_controller(
            repo.room_id,
            repo.campaign_id,
            dm_seat.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=member.id,
            ),
        )


def test_controller_must_be_an_active_access_session_from_same_room() -> None:
    repo = _FakeSeatRepository()
    service = SeatService(repo)
    other_room = _access(repo, room_id=uuid4())
    player = service.create_seat(repo.room_id, repo.campaign_id, SeatCreate(role=SeatRole.PLAYER))
    with pytest.raises(SeatControllerError):
        service.set_controller(
            repo.room_id,
            repo.campaign_id,
            player.id,
            SeatControllerPatch(
                controller_kind=ControllerKind.HUMAN,
                controller_access_session_id=other_room.id,
            ),
        )


def test_player_character_selection_enforces_roster_status_archive_and_uniqueness() -> None:
    repo = _FakeSeatRepository()
    service = SeatService(repo)
    first = service.create_seat(repo.room_id, repo.campaign_id, SeatCreate(role=SeatRole.PLAYER))
    second = service.create_seat(repo.room_id, repo.campaign_id, SeatCreate(role=SeatRole.PLAYER))
    active_character = uuid4()
    inactive_character = uuid4()
    retired_character = uuid4()
    archived_character = uuid4()
    repo.roster[(repo.campaign_id, active_character)] = "active"
    repo.roster[(repo.campaign_id, inactive_character)] = "inactive"
    repo.roster[(repo.campaign_id, retired_character)] = "retired"
    repo.roster[(repo.campaign_id, archived_character)] = "active"
    repo.archived_characters.add(archived_character)

    assert service.select_character(repo.room_id, repo.campaign_id, first.id, active_character).selected_character_id == active_character
    assert service.select_character(repo.room_id, repo.campaign_id, second.id, inactive_character).selected_character_id == inactive_character

    with pytest.raises(SeatCharacterSelectionError):
        service.select_character(repo.room_id, repo.campaign_id, second.id, retired_character)
    with pytest.raises(SeatCharacterSelectionError):
        service.select_character(repo.room_id, repo.campaign_id, second.id, archived_character)
    with pytest.raises(SeatCharacterSelectionError):
        service.select_character(repo.room_id, repo.campaign_id, second.id, active_character)


def test_lobby_reconciles_selection_when_roster_or_character_becomes_ineligible() -> None:
    repo = _FakeSeatRepository()
    service = SeatService(repo)
    seat = service.create_seat(repo.room_id, repo.campaign_id, SeatCreate(role=SeatRole.PLAYER))
    character_id = uuid4()
    repo.roster[(repo.campaign_id, character_id)] = "active"
    service.select_character(repo.room_id, repo.campaign_id, seat.id, character_id)

    repo.roster[(repo.campaign_id, character_id)] = "retired"
    snapshot = service.lobby(repo.room_id, repo.campaign_id)
    assert snapshot.seats[0].selected_character_id is None

    repo.roster[(repo.campaign_id, character_id)] = "active"
    service.select_character(repo.room_id, repo.campaign_id, seat.id, character_id)
    repo.archived_characters.add(character_id)
    snapshot = service.lobby(repo.room_id, repo.campaign_id)
    assert snapshot.seats[0].selected_character_id is None


def test_cross_campaign_seat_lookup_is_rejected() -> None:
    repo = _FakeSeatRepository()
    service = SeatService(repo)
    seat = service.create_seat(repo.room_id, repo.campaign_id, SeatCreate(role=SeatRole.PLAYER))
    with pytest.raises(SeatCampaignMismatchError):
        service.get_scoped_seat(repo.room_id, uuid4(), seat.id)


def test_lobby_presence_uses_p2a_ninety_second_timeout() -> None:
    repo = _FakeSeatRepository()
    service = SeatService(repo)
    connected = _access(repo, seen_seconds_ago=89)
    offline = _access(repo, seen_seconds_ago=91)
    snapshot = service.lobby(repo.room_id, repo.campaign_id)
    by_id = {controller.access_session_id: controller for controller in snapshot.controllers}
    assert by_id[connected.id].presence is PresenceStatus.CONNECTED
    assert by_id[offline.id].presence is PresenceStatus.OFFLINE
