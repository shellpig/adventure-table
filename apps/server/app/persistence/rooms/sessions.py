from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.persistence.rooms.tables import (
    active_character_session_leases,
    session_participants,
    sessions,
)


class SessionPersistenceConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParticipantSeed:
    seat_id: UUID
    role_snapshot: str
    controller_kind_at_join: str
    controller_access_session_id_at_join: UUID | None
    active_character_id: UUID | None


@dataclass(frozen=True)
class StoredSession:
    id: UUID
    campaign_id: UUID
    status: str
    dm_seat_id: UUID
    dm_controller_kind: str
    dm_controller_access_session_id: UUID | None
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class StoredSessionParticipant:
    id: UUID
    session_id: UUID
    seat_id: UUID
    role_snapshot: str
    controller_kind_at_join: str
    controller_access_session_id_at_join: UUID | None
    active_character_id: UUID | None
    joined_at: datetime
    left_at: datetime | None


@dataclass(frozen=True)
class StoredCharacterLease:
    character_id: UUID
    session_id: UUID
    participant_id: UUID


class SessionRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _session(row) -> StoredSession | None:
        return StoredSession(**dict(row)) if row is not None else None

    def get(self, session_id: UUID) -> StoredSession | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(sessions).where(sessions.c.id == session_id)
            ).mappings().one_or_none()
        return self._session(row)

    def active_for_campaign(self, campaign_id: UUID) -> StoredSession | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(sessions).where(
                    sessions.c.campaign_id == campaign_id,
                    sessions.c.status == "active",
                )
            ).mappings().one_or_none()
        return self._session(row)

    def list_participants(self, session_id: UUID) -> tuple[StoredSessionParticipant, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(session_participants)
                .where(session_participants.c.session_id == session_id)
                .order_by(session_participants.c.joined_at, session_participants.c.id)
            ).mappings().all()
        return tuple(StoredSessionParticipant(**dict(row)) for row in rows)

    def lease_for_character(self, character_id: UUID) -> StoredCharacterLease | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(active_character_session_leases).where(
                    active_character_session_leases.c.character_id == character_id
                )
            ).mappings().one_or_none()
        return StoredCharacterLease(**dict(row)) if row is not None else None

    def create_with_participants(
        self,
        *,
        campaign_id: UUID,
        dm_seat_id: UUID,
        dm_controller_kind: str,
        dm_controller_access_session_id: UUID | None,
        participants: Iterable[ParticipantSeed],
    ) -> StoredSession:
        """Persist one Session boundary and all participant/lease rows atomically.

        P2-E domain validation and locking live above this primitive. The database
        primary key on active_character_session_leases.character_id is the final
        concurrency guard; any collision rolls the entire transaction back.
        """

        session_id = uuid4()
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(sessions).values(
                        id=session_id,
                        campaign_id=campaign_id,
                        status="active",
                        dm_seat_id=dm_seat_id,
                        dm_controller_kind=dm_controller_kind,
                        dm_controller_access_session_id=dm_controller_access_session_id,
                        started_at=now,
                        ended_at=None,
                    )
                )
                for participant in participants:
                    participant_id = uuid4()
                    connection.execute(
                        insert(session_participants).values(
                            id=participant_id,
                            session_id=session_id,
                            seat_id=participant.seat_id,
                            role_snapshot=participant.role_snapshot,
                            controller_kind_at_join=participant.controller_kind_at_join,
                            controller_access_session_id_at_join=(
                                participant.controller_access_session_id_at_join
                            ),
                            active_character_id=participant.active_character_id,
                            joined_at=now,
                            left_at=None,
                        )
                    )
                    if participant.active_character_id is not None:
                        connection.execute(
                            insert(active_character_session_leases).values(
                                character_id=participant.active_character_id,
                                session_id=session_id,
                                participant_id=participant_id,
                            )
                        )
        except IntegrityError as exc:
            raise SessionPersistenceConflictError(str(exc)) from exc
        stored = self.get(session_id)
        if stored is None:
            raise RuntimeError("created Session could not be reloaded")
        return stored

    def add_participant(
        self,
        *,
        session_id: UUID,
        participant: ParticipantSeed,
    ) -> StoredSessionParticipant:
        participant_id = uuid4()
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(session_participants).values(
                        id=participant_id,
                        session_id=session_id,
                        seat_id=participant.seat_id,
                        role_snapshot=participant.role_snapshot,
                        controller_kind_at_join=participant.controller_kind_at_join,
                        controller_access_session_id_at_join=(
                            participant.controller_access_session_id_at_join
                        ),
                        active_character_id=participant.active_character_id,
                        joined_at=now,
                        left_at=None,
                    )
                )
                if participant.active_character_id is not None:
                    connection.execute(
                        insert(active_character_session_leases).values(
                            character_id=participant.active_character_id,
                            session_id=session_id,
                            participant_id=participant_id,
                        )
                    )
        except IntegrityError as exc:
            raise SessionPersistenceConflictError(str(exc)) from exc
        with self.engine.connect() as connection:
            row = connection.execute(
                select(session_participants).where(session_participants.c.id == participant_id)
            ).mappings().one()
        return StoredSessionParticipant(**dict(row))

    def finalize(self, session_id: UUID, *, status: str) -> StoredSession | None:
        if status not in {"ended", "abandoned"}:
            raise ValueError("final Session status must be ended or abandoned")
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            row = connection.execute(
                select(sessions.c.status)
                .where(sessions.c.id == session_id)
                .with_for_update()
            ).one_or_none()
            if row is None or row.status != "active":
                return None
            connection.execute(
                update(sessions)
                .where(sessions.c.id == session_id)
                .values(status=status, ended_at=now)
            )
            connection.execute(
                delete(active_character_session_leases).where(
                    active_character_session_leases.c.session_id == session_id
                )
            )
        return self.get(session_id)


__all__ = [
    "ParticipantSeed",
    "SessionPersistenceConflictError",
    "SessionRepository",
    "StoredCharacterLease",
    "StoredSession",
    "StoredSessionParticipant",
]
