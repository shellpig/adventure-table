from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext, StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventService,
)
from app.persistence.rooms.session_live import (
    LateJoinCharacterLeasedPersistenceError,
    LateJoinControllerMismatchPersistenceError,
    LateJoinPersistenceError,
    SessionLiveRepository,
)
from app.persistence.rooms.sessions import (
    CharacterAlreadyLeasedPersistenceError,
    SessionAlreadyActivePersistenceError,
    SessionRepository,
    SessionStartControllerMismatchPersistenceError,
    SessionStartPersistenceError,
    StoredSession,
    StoredSessionParticipant,
)
from app.persistence.rooms.table_runtime import (
    TableEventActorBindingStalePersistenceError,
    TableEventRepository,
    TableEventSessionNotActivePersistenceError,
    TableEventSessionNotFoundPersistenceError,
)


class SessionStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"
    ABANDONED = "abandoned"


class SessionLateJoinRequest(StrictModel):
    seat_id: UUID


class SessionActiveCharacterPatch(StrictModel):
    active_character_id: UUID


class SessionParticipantSnapshot(StrictModel):
    id: UUID
    seat_id: UUID
    role: str
    controller_kind_at_join: str
    controller_access_session_id_at_join: UUID | None = None
    controller_ai_grant_id_at_join: UUID | None = None
    controller_generation_at_join: int | None = None
    active_character_id: UUID | None = None


class SessionSnapshot(StrictModel):
    id: UUID
    campaign_id: UUID
    status: SessionStatus
    dm_seat_id: UUID
    dm_controller_kind: str
    dm_controller_access_session_id: UUID | None = None
    dm_controller_ai_grant_id: UUID | None = None
    dm_controller_generation: int | None = None
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


class SessionLateJoinError(RuntimeError):
    pass


class SessionActiveCharacterLockedError(RuntimeError):
    pass


class SessionService:
    def __init__(
        self,
        repository: SessionRepository,
        live_repository: SessionLiveRepository | None = None,
        event_service: TableEventService | None = None,
    ) -> None:
        self.repository = repository
        self.live_repository = live_repository or SessionLiveRepository(repository.engine)
        self.event_service = event_service or TableEventService(
            TableEventRepository(repository.engine)
        )

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
            controller_ai_grant_id_at_join=stored.controller_ai_grant_id_at_join,
            controller_generation_at_join=stored.controller_generation_at_join,
            active_character_id=stored.active_character_id,
        )

    def _present(self, stored: StoredSession) -> SessionSnapshot:
        return SessionSnapshot(
            id=stored.id,
            campaign_id=stored.campaign_id,
            status=SessionStatus(stored.status),
            dm_seat_id=stored.dm_seat_id,
            dm_controller_kind=stored.dm_controller_kind,
            dm_controller_access_session_id=stored.dm_controller_access_session_id,
            dm_controller_ai_grant_id=stored.dm_controller_ai_grant_id,
            dm_controller_generation=stored.dm_controller_generation,
            started_at=stored.started_at,
            ended_at=stored.ended_at,
            participants=[
                self._participant(item)
                for item in self.repository.list_participants(stored.id)
            ],
        )

    @staticmethod
    def _map_start_error(exc: Exception) -> Exception:
        if isinstance(exc, SessionAlreadyActivePersistenceError):
            return SessionAlreadyActiveError(str(exc))
        if isinstance(exc, CharacterAlreadyLeasedPersistenceError):
            return CharacterAlreadyInActiveSessionError(str(exc))
        if isinstance(exc, SessionStartControllerMismatchPersistenceError):
            return DMControllerMismatchError(str(exc))
        if isinstance(exc, SessionStartPersistenceError):
            return SessionLobbyUnavailableError(str(exc))
        return exc

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
        except Exception as exc:
            mapped = self._map_start_error(exc)
            if mapped is exc:
                raise
            raise mapped from exc
        return self._present(stored)

    def start_session_as_ai_dm(
        self,
        room_id: UUID,
        campaign_id: UUID,
        *,
        grant_id: UUID,
        generation: int,
    ) -> SessionSnapshot:
        self._require_campaign(room_id, campaign_id)
        try:
            stored = self.repository.start_from_ai_dm_grant(
                room_id=room_id,
                campaign_id=campaign_id,
                grant_id=grant_id,
                generation=generation,
            )
        except Exception as exc:
            mapped = self._map_start_error(exc)
            if mapped is exc:
                raise
            raise mapped from exc
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

    def _resolve_human_actor(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        context: RoomAccessContext,
    ) -> TableActorContext:
        try:
            return self.event_service.resolve_human_actor(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                context=context,
            )
        except (TableEventNotFoundError, TableEventActorUnauthorizedError) as exc:
            raise DMControllerMismatchError(
                "Caller is not a current Session controller"
            ) from exc

    def _require_current_dm_actor(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        actor: TableActorContext,
    ) -> None:
        if (
            actor.room_id != room_id
            or actor.campaign_id != campaign_id
            or actor.session_id != session_id
            or not actor.is_current_dm
            or actor.role != "dm"
        ):
            raise DMControllerMismatchError("Only the current DM Controller may perform this action")
        try:
            self.event_service.require_actor_current(actor)
        except TableEventActorUnauthorizedError as exc:
            raise DMControllerMismatchError("Current DM Controller binding is stale") from exc

    def late_join(
        self,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        payload: SessionLateJoinRequest,
        context: RoomAccessContext,
    ) -> SessionSnapshot:
        actor = self._resolve_human_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
        )
        return self.late_join_actor(
            room_id,
            campaign_id,
            session_id,
            payload,
            actor,
        )

    def late_join_actor(
        self,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        payload: SessionLateJoinRequest,
        actor: TableActorContext,
    ) -> SessionSnapshot:
        self._require_active(room_id, campaign_id, session_id)
        self._require_current_dm_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            actor=actor,
        )
        try:
            self.live_repository.late_join_from_lobby(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                caller_actor_kind=actor.actor_kind.value,
                caller_access_session_id=actor.access_session_id,
                caller_ai_grant_id=actor.ai_controller_grant_id,
                caller_generation=actor.grant_generation,
                seat_id=payload.seat_id,
            )
        except LateJoinControllerMismatchPersistenceError as exc:
            raise DMControllerMismatchError(str(exc)) from exc
        except LateJoinCharacterLeasedPersistenceError as exc:
            raise CharacterAlreadyInActiveSessionError(str(exc)) from exc
        except LateJoinPersistenceError as exc:
            raise SessionLateJoinError(str(exc)) from exc
        stored = self.repository.get(session_id)
        if stored is None:
            raise SessionNotFoundError(session_id)
        return self._present(stored)

    def assert_active_character_locked(
        self,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        participant_id: UUID,
        _payload: SessionActiveCharacterPatch,
    ) -> None:
        self._require_active(room_id, campaign_id, session_id)
        if not self.live_repository.participant_is_active(
            session_id=session_id,
            participant_id=participant_id,
        ):
            raise SessionNotFoundError(participant_id)
        raise SessionActiveCharacterLockedError(
            "Active Character is immutable after Session participation begins"
        )

    def _finalize_with_event(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        status: SessionStatus,
        actor: TableActorContext | None,
        owner_access_session_id: UUID | None = None,
    ) -> SessionSnapshot:
        binding = self.event_service._stored_binding(actor) if actor is not None else None

        def projection(connection, _event_id, _seq) -> None:
            if not self.repository.finalize_in_transaction(
                connection,
                session_id=session_id,
                status=status.value,
            ):
                raise SessionNotActiveError(session_id)

        try:
            self.event_service.repository.append(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                kind=f"session.{status.value}",
                acting_seat_id=actor.seat_id if actor is not None else None,
                subject_seat_id=None,
                subject_character_id=None,
                execution_mode="self" if actor is not None else "system",
                visibility="public",
                recipient_seat_ids=(),
                payload_version=1,
                payload={
                    "status": status.value,
                    **(
                        {"owner_access_session_id": str(owner_access_session_id)}
                        if owner_access_session_id is not None
                        else {}
                    ),
                },
                idempotency_key=None,
                expected_actor_binding=binding,
                transaction_projection=projection,
            )
        except TableEventActorBindingStalePersistenceError as exc:
            raise DMControllerMismatchError("Current DM Controller binding is stale") from exc
        except TableEventSessionNotFoundPersistenceError as exc:
            raise SessionNotFoundError(session_id) from exc
        except TableEventSessionNotActivePersistenceError as exc:
            raise SessionNotActiveError(session_id) from exc
        if self.event_service.notifier is not None:
            self.event_service.notifier.notify(session_id)
        finalized = self.repository.get(session_id)
        if finalized is None:
            raise SessionNotFoundError(session_id)
        return self._present(finalized)

    def end_session(
        self,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        context: RoomAccessContext,
    ) -> SessionSnapshot:
        self._require_active(room_id, campaign_id, session_id)
        actor = self._resolve_human_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
        )
        return self.end_session_actor(room_id, campaign_id, session_id, actor)

    def end_session_actor(
        self,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        actor: TableActorContext,
    ) -> SessionSnapshot:
        self._require_active(room_id, campaign_id, session_id)
        self._require_current_dm_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            actor=actor,
        )
        return self._finalize_with_event(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            status=SessionStatus.ENDED,
            actor=actor,
        )

    def abandon_session(
        self,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        context: RoomAccessContext,
    ) -> SessionSnapshot:
        self._require_active(room_id, campaign_id, session_id)
        if context.authority is RoomAccessAuthority.OWNER:
            return self._finalize_with_event(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                status=SessionStatus.ABANDONED,
                actor=None,
                owner_access_session_id=context.access_session_id,
            )
        actor = self._resolve_human_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            context=context,
        )
        return self.abandon_session_actor(room_id, campaign_id, session_id, actor)

    def abandon_session_actor(
        self,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        actor: TableActorContext,
    ) -> SessionSnapshot:
        self._require_active(room_id, campaign_id, session_id)
        self._require_current_dm_actor(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            actor=actor,
        )
        return self._finalize_with_event(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=session_id,
            status=SessionStatus.ABANDONED,
            actor=actor,
        )


__all__ = [
    "CharacterAlreadyInActiveSessionError",
    "DMControllerMismatchError",
    "SessionActiveCharacterLockedError",
    "SessionActiveCharacterPatch",
    "SessionAlreadyActiveError",
    "SessionLateJoinError",
    "SessionLateJoinRequest",
    "SessionLobbyUnavailableError",
    "SessionNotActiveError",
    "SessionNotFoundError",
    "SessionParticipantSnapshot",
    "SessionResume",
    "SessionService",
    "SessionSnapshot",
    "SessionStatus",
]
