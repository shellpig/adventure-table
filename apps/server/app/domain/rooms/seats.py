from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID

from pydantic import Field, field_validator

from app.domain.rooms.schemas import RoomAccessAuthority, StrictModel
from app.persistence.rooms.seats import SeatPersistenceConflictError, SeatRepository, StoredSeat


PRESENCE_TIMEOUT = timedelta(seconds=90)


class SeatRole(StrEnum):
    DM = "dm"
    PLAYER = "player"
    SPECTATOR = "spectator"


class ControllerKind(StrEnum):
    HUMAN = "human"
    AI = "ai"
    NONE = "none"


class PresenceStatus(StrEnum):
    CONNECTED = "connected"
    OFFLINE = "offline"
    NOT_APPLICABLE = "not_applicable"


class SeatCreate(StrictModel):
    role: SeatRole
    label: str | None = Field(default=None, max_length=100)

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class SeatControllerPatch(StrictModel):
    controller_kind: ControllerKind
    controller_access_session_id: UUID | None = None


class SeatCharacterPatch(StrictModel):
    selected_character_id: UUID | None = None


class CampaignSeat(StrictModel):
    id: UUID
    campaign_id: UUID
    role: SeatRole
    label: str | None = None
    controller_kind: ControllerKind
    controller_access_session_id: UUID | None = None
    controller_display_name: str | None = None
    controller_authority: RoomAccessAuthority | None = None
    presence: PresenceStatus = PresenceStatus.NOT_APPLICABLE
    selected_character_id: UUID | None = None
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class LobbyController(StrictModel):
    access_session_id: UUID
    authority: RoomAccessAuthority
    display_name: str | None = None
    presence: PresenceStatus


class LobbySnapshot(StrictModel):
    room_id: UUID
    campaign_id: UUID
    caller_access_session_id: UUID | None = None
    seats: list[CampaignSeat]
    controllers: list[LobbyController]


class SeatNotFoundError(LookupError):
    pass


class SeatCampaignMismatchError(LookupError):
    pass


class LobbyUnavailableError(RuntimeError):
    pass


class SeatControllerError(RuntimeError):
    pass


class SeatCharacterSelectionError(RuntimeError):
    pass


class SeatService:
    def __init__(self, repository: SeatRepository) -> None:
        self.repository = repository

    def _require_campaign(self, room_id: UUID, campaign_id: UUID) -> None:
        if self.repository.campaign_room_id(campaign_id) != room_id:
            raise SeatCampaignMismatchError(campaign_id)

    def get_scoped_seat(self, room_id: UUID, campaign_id: UUID, seat_id: UUID) -> StoredSeat:
        self._require_campaign(room_id, campaign_id)
        seat = self.repository.get(seat_id)
        if seat is None or seat.campaign_id != campaign_id or seat.archived_at is not None:
            raise SeatNotFoundError(seat_id)
        return seat

    @staticmethod
    def _presence(last_seen_at: datetime, revoked_at: datetime | None, now: datetime) -> PresenceStatus:
        if revoked_at is not None:
            return PresenceStatus.OFFLINE
        if last_seen_at.tzinfo is None:
            last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
        return PresenceStatus.CONNECTED if now - last_seen_at <= PRESENCE_TIMEOUT else PresenceStatus.OFFLINE

    def _present(self, seat: StoredSeat, *, now: datetime | None = None) -> CampaignSeat:
        now = now or datetime.now(timezone.utc)
        display_name = None
        authority = None
        presence = PresenceStatus.NOT_APPLICABLE
        if seat.controller_kind == ControllerKind.HUMAN.value and seat.controller_access_session_id is not None:
            access = self.repository.get_access_session(seat.controller_access_session_id)
            if access is not None:
                display_name = access.display_name
                authority = RoomAccessAuthority(access.authority)
                presence = self._presence(access.last_seen_at, access.revoked_at, now)
            else:
                presence = PresenceStatus.OFFLINE
        return CampaignSeat(
            id=seat.id,
            campaign_id=seat.campaign_id,
            role=SeatRole(seat.role),
            label=seat.label,
            controller_kind=ControllerKind(seat.controller_kind),
            controller_access_session_id=seat.controller_access_session_id,
            controller_display_name=display_name,
            controller_authority=authority,
            presence=presence,
            selected_character_id=seat.selected_character_id,
            archived_at=seat.archived_at,
            created_at=seat.created_at,
            updated_at=seat.updated_at,
        )

    def _selection_is_eligible(self, campaign_id: UUID, character_id: UUID) -> bool:
        return (
            self.repository.roster_status(campaign_id=campaign_id, character_id=character_id)
            in {"active", "inactive"}
            and self.repository.character_is_archived(character_id) is False
        )

    def _reconcile_selections(self, campaign_id: UUID) -> None:
        for seat in self.repository.list_for_campaign(campaign_id):
            if seat.selected_character_id is None:
                continue
            if self._selection_is_eligible(campaign_id, seat.selected_character_id):
                continue
            self.repository.set_selected_character(seat_id=seat.id, character_id=None)

    def list_seats(self, room_id: UUID, campaign_id: UUID) -> list[CampaignSeat]:
        self._require_campaign(room_id, campaign_id)
        self._reconcile_selections(campaign_id)
        return [self._present(seat) for seat in self.repository.list_for_campaign(campaign_id)]

    def create_seat(self, room_id: UUID, campaign_id: UUID, payload: SeatCreate) -> CampaignSeat:
        self._require_campaign(room_id, campaign_id)
        return self._present(self.repository.create(campaign_id=campaign_id, role=payload.role.value, label=payload.label))

    def set_controller(
        self,
        room_id: UUID,
        campaign_id: UUID,
        seat_id: UUID,
        payload: SeatControllerPatch,
    ) -> CampaignSeat:
        seat = self.get_scoped_seat(room_id, campaign_id, seat_id)
        if payload.controller_kind is ControllerKind.AI:
            raise SeatControllerError("AI controllers are reserved for a later phase")
        if payload.controller_kind is ControllerKind.NONE:
            if payload.controller_access_session_id is not None:
                raise SeatControllerError("none controller cannot bind an access session")
            access_session_id = None
        else:
            if payload.controller_access_session_id is None:
                raise SeatControllerError("human controller requires an access session")
            access = self.repository.get_access_session(payload.controller_access_session_id)
            if access is None or access.room_id != room_id or access.revoked_at is not None:
                raise SeatControllerError("controller access session is not active in this Room")
            if seat.role == SeatRole.DM.value and access.authority not in {
                RoomAccessAuthority.DM.value,
                RoomAccessAuthority.OWNER.value,
            }:
                raise SeatControllerError("DM Seat controller requires DM or Owner authority")
            access_session_id = access.id
        updated = self.repository.set_controller(
            seat_id=seat.id,
            controller_kind=payload.controller_kind.value,
            controller_access_session_id=access_session_id,
        )
        if updated is None:
            raise SeatNotFoundError(seat_id)
        return self._present(updated)

    def select_character(
        self,
        room_id: UUID,
        campaign_id: UUID,
        seat_id: UUID,
        character_id: UUID | None,
    ) -> CampaignSeat:
        seat = self.get_scoped_seat(room_id, campaign_id, seat_id)
        if seat.role != SeatRole.PLAYER.value:
            raise SeatCharacterSelectionError("only Player Seats can select a Character")
        if character_id is not None:
            if not self._selection_is_eligible(campaign_id, character_id):
                raise SeatCharacterSelectionError("Character is not eligible in this Campaign roster")
            if self.repository.character_selected_elsewhere(
                campaign_id=campaign_id,
                character_id=character_id,
                excluding_seat_id=seat_id,
            ):
                raise SeatCharacterSelectionError("Character is already selected by another Player Seat")
        try:
            updated = self.repository.set_selected_character(seat_id=seat_id, character_id=character_id)
        except SeatPersistenceConflictError as exc:
            raise SeatCharacterSelectionError("Character is already selected by another Player Seat") from exc
        if updated is None:
            raise SeatNotFoundError(seat_id)
        return self._present(updated)

    def archive_seat(self, room_id: UUID, campaign_id: UUID, seat_id: UUID) -> CampaignSeat:
        self.get_scoped_seat(room_id, campaign_id, seat_id)
        archived = self.repository.archive(seat_id)
        if archived is None:
            raise SeatNotFoundError(seat_id)
        return self._present(archived)

    def delete_seat(self, room_id: UUID, campaign_id: UUID, seat_id: UUID) -> None:
        self.get_scoped_seat(room_id, campaign_id, seat_id)
        if not self.repository.delete_unreferenced(seat_id):
            raise SeatNotFoundError(seat_id)

    def lobby(
        self,
        room_id: UUID,
        campaign_id: UUID,
        *,
        caller_access_session_id: UUID | None = None,
    ) -> LobbySnapshot:
        self._require_campaign(room_id, campaign_id)
        if self.repository.campaign_status(campaign_id) != "active":
            raise LobbyUnavailableError("Campaign must be active before entering Lobby")
        self._reconcile_selections(campaign_id)
        now = datetime.now(timezone.utc)
        controllers = [
            LobbyController(
                access_session_id=access.id,
                authority=RoomAccessAuthority(access.authority),
                display_name=access.display_name,
                presence=self._presence(access.last_seen_at, access.revoked_at, now),
            )
            for access in self.repository.list_access_sessions(room_id)
        ]
        return LobbySnapshot(
            room_id=room_id,
            campaign_id=campaign_id,
            caller_access_session_id=caller_access_session_id,
            seats=[self._present(seat, now=now) for seat in self.repository.list_for_campaign(campaign_id)],
            controllers=controllers,
        )


__all__ = [
    "CampaignSeat",
    "ControllerKind",
    "LobbyController",
    "LobbySnapshot",
    "LobbyUnavailableError",
    "PresenceStatus",
    "SeatCampaignMismatchError",
    "SeatCharacterPatch",
    "SeatCharacterSelectionError",
    "SeatControllerError",
    "SeatControllerPatch",
    "SeatCreate",
    "SeatNotFoundError",
    "SeatRole",
    "SeatService",
]
