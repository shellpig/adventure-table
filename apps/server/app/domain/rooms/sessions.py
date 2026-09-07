from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext, StrictModel
from app.persistence.rooms.sessions import (
    CharacterAlreadyLeasedPersistenceError,
    SessionAlreadyActivePersistenceError,
    SessionRepository,
    SessionStartPersistenceError,
    StoredSession,
    StoredSessionParticipant,
)


class SessionStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    ABANDONED = "abandoned"


class SessionParticipantSnapshot(StrictModel):
    id: UUID
    seat_id: UUID
    role: str
    controller_kind_at_join: str
    controller_access_session_id_at_join: UUID | None = None
    active_character_id: UUID | None = None


class SessionSnapshot(StrictModel):
    id: UUID
    campaign_id: UUID
    status: SessionStatus
    dm_seat_id: UUID
    dm_controller_access_session_id: UUID | None = None
    started_at: datetime
    ended_at: datetime | None = None
    participants: list[SessionParticipantSnapshot]


class SessionResume(StrictModel):
    room_id: UUID
    campaign_id: UUID
    active_session: SessionSnapshot | None = None


class SessionNotFoundError(LookupError):
    pass


class SessionAlreadyActiveError(RuntimeError):
    pass


class CharacterAlreadyInActiveSessionError(RuntimeError):
    pass


class DMControllerMismatchError(PermissionError):
    pass


class SessionNotActiveError(RuntimeError):
    pass


class SessionLobbyUnavailableError(RuntimeError):
    pass


class SessionService:
    def __init__(self, repository: SessionRepository) -> None:
        self.repository = repository

    def _require_campaign(self, room_id: UUID, campaign_id: UUID) -> None:
        if self.repository.campaign_room_id(campaign_id) != room_id:
            raise SessionNotFoundError(campaign_id)

    @staticmethod
    def _participant(stored: StoredSessionParticipant) -> SessionParticipantSnapshot:
        return SessionParticipantSnapshot(
            id=stored.id,
            seat_id=stored.seat_id,
            role=stored.role_snapshot,
            controller_kind_at_join=stored.controller_kind_at_join,
            controller_access_session_id_at_join=stored.controller_access_session_id_at_join,
            active_character_id=stored.active_character_id,
        )

    def _present(self, stored: StoredSession) -> SessionSnapshot:
        return SessionSnapshot(
            id=stored.id,
            campaign_id=stored.campaign_id,
            status=SessionStatus(stored.status),
            dm_seat_id=stored.dm_seat_id,
            dm_controller_access_session_id=stored.dm_controller_access_session_id,
            started_at=stored.started_at,
            ended_at=stored.ended_at,
            participants=[
                self._participant(item)
                for item in self.repository.list_participants(stored.id)
            ],
        )

    def start_session(
        self,
        room_id: UUID,
        campaign_id: UUID,
        context: RoomAccessContext,
    ) -> SessionSnapshot:
        self._require_campaign(room_id, campaign_id)
        try:
            stored = self.repository.start_from_lobby(
                room_id=room_id,
                campaign_id=campaign_id,
                caller_access_session_id=context.access_session_id,
                caller_authority=context.authority.value,
            )
        except SessionAlreadyActivePersistenceError as exc:
            raise SessionAlreadyActiveError(str(exc)) from exc
        except CharacterAlreadyLeasedPersistenceError as exc:
            raise CharacterAlreadyInActiveSessionError(str(exc)) from exc
        except SessionStartPersistenceError as exc:
            message = str(exc)
            if "Caller" in message or "Start requires" in message:
                raise DMControllerMismatchError(message) from exc
            raise SessionLobbyUnavailableError(message) from exc
        return self._present(stored)

    def get_session(
        self,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
    ) -> SessionSnapshot:
        self._require_campaign(room_id, campaign_id)
        stored = self.repository.get(session_id)
        if stored is None or stored.campaign_id != campaign_id:
            raise SessionNotFoundError(session_id)
        return self._present(stored)

    def resume(self, room_id: UUID, campaign_id: UUID) -> SessionResume:
        self._require_campaign(room_id, campaign_id)
        stored = self.repository.active_for_campaign(campaign_id)
        return SessionResume(
            room_id=room_id,
            campaign_id=campaign_id,
            active_session=self._present(stored) if stored is not None else None,
        )

    def _require_active(
        self,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
    ) -> StoredSession:
        self._require_campaign(room_id, campaign_id)
        stored = self.repository.get(session_id)
        if stored is None or stored.campaign_id != campaign_id:
            raise SessionNotFoundError(session_id)
        if stored.status != SessionStatus.ACTIVE.value:
            raise SessionNotActiveError(session_id)
        return stored

    @staticmethod
    def _is_current_dm(stored: StoredSession, context: RoomAccessContext) -> bool:
        return (
            stored.dm_controller_kind == "human"
            and stored.dm_controller_access_session_id == context.access_session_id
            and context.authority in {RoomAccessAuthority.DM, RoomAccessAuthority.OWNER}
        )

    def end_session(
        self,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        context: RoomAccessContext,
    ) -> SessionSnapshot:
        stored = self._require_active(room_id, campaign_id, session_id)
        if not self._is_current_dm(stored, context):
            raise DMControllerMismatchError("Only the current DM Controller may End Session")
        finalized = self.repository.finalize(session_id, status=SessionStatus.ENDED.value)
        if finalized is None:
            raise SessionNotActiveError(session_id)
        return self._present(finalized)

    def abandon_session(
        self,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        context: RoomAccessContext,
    ) -> SessionSnapshot:
        stored = self._require_active(room_id, campaign_id, session_id)
        if context.authority is not RoomAccessAuthority.OWNER and not self._is_current_dm(
            stored, context
        ):
            raise DMControllerMismatchError(
                "Only the current DM Controller or Room Owner may Abandon Session"
            )
        finalized = self.repository.finalize(session_id, status=SessionStatus.ABANDONED.value)
        if finalized is None:
            raise SessionNotActiveError(session_id)
        return self._present(finalized)


__all__ = [
    "CharacterAlreadyInActiveSessionError",
    "DMControllerMismatchError",
    "SessionAlreadyActiveError",
    "SessionLobbyUnavailableError",
    "SessionNotActiveError",
    "SessionNotFoundError",
    "SessionParticipantSnapshot",
    "SessionResume",
    "SessionService",
    "SessionSnapshot",
    "SessionStatus",
]
