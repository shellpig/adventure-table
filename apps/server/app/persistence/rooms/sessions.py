from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.persistence.characters import characters
from app.persistence.rooms.tables import (
    active_character_session_leases,
    ai_controller_grants,
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_access_sessions,
    room_characters,
    rooms,
    session_participants,
    sessions,
)


class SessionPersistenceConflictError(RuntimeError):
    pass


class SessionAlreadyActivePersistenceError(RuntimeError):
    pass


class CharacterAlreadyLeasedPersistenceError(RuntimeError):
    pass


class SessionStartPersistenceError(RuntimeError):
    pass


class SessionStartControllerMismatchPersistenceError(SessionStartPersistenceError):
    pass


@dataclass(frozen=True)
class ParticipantSeed:
    seat_id: UUID
    role_snapshot: str
    controller_kind_at_join: str
    controller_access_session_id_at_join: UUID | None
    active_character_id: UUID | None
    controller_ai_grant_id_at_join: UUID | None = None
    controller_generation_at_join: int | None = None


@dataclass(frozen=True)
class StoredSession:
    id: UUID
    campaign_id: UUID
    status: str
    dm_seat_id: UUID
    dm_controller_kind: str
    dm_controller_access_session_id: UUID | None
    dm_controller_ai_grant_id: UUID | None
    dm_controller_generation: int | None
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
    controller_ai_grant_id_at_join: UUID | None
    controller_generation_at_join: int | None
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

    @staticmethod
    def _participant(row) -> StoredSessionParticipant:
        return StoredSessionParticipant(**dict(row))

    def get(self, session_id: UUID) -> StoredSession | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(sessions).where(sessions.c.id == session_id)
            ).mappings().one_or_none()
        return self._session(row)

    def campaign_room_id(self, campaign_id: UUID) -> UUID | None:
        with self.engine.connect() as connection:
            return connection.scalar(select(campaigns.c.room_id).where(campaigns.c.id == campaign_id))

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
        return tuple(self._participant(row) for row in rows)

    def participant(self, participant_id: UUID) -> StoredSessionParticipant | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(session_participants).where(session_participants.c.id == participant_id)
            ).mappings().one_or_none()
        return self._participant(row) if row is not None else None

    def lease_for_character(self, character_id: UUID) -> StoredCharacterLease | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(active_character_session_leases).where(
                    active_character_session_leases.c.character_id == character_id
                )
            ).mappings().one_or_none()
        return StoredCharacterLease(**dict(row)) if row is not None else None

    def _insert_session_rows(
        self,
        connection,
        *,
        session_id: UUID,
        campaign_id: UUID,
        dm_seat_id: UUID,
        dm_controller_kind: str,
        dm_controller_access_session_id: UUID | None,
        participants: Iterable[ParticipantSeed],
        now: datetime,
        dm_controller_ai_grant_id: UUID | None = None,
        dm_controller_generation: int | None = None,
    ) -> None:
        connection.execute(
            insert(sessions).values(
                id=session_id,
                campaign_id=campaign_id,
                status="active",
                dm_seat_id=dm_seat_id,
                dm_controller_kind=dm_controller_kind,
                dm_controller_access_session_id=dm_controller_access_session_id,
                dm_controller_ai_grant_id=dm_controller_ai_grant_id,
                dm_controller_generation=dm_controller_generation,
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
                    controller_ai_grant_id_at_join=(
                        participant.controller_ai_grant_id_at_join
                    ),
                    controller_generation_at_join=(
                        participant.controller_generation_at_join
                    ),
                    active_character_id=participant.active_character_id,
                    joined_at=now,
                    left_at=None,
                )
            )
            if participant.active_character_id is not None:
                try:
                    connection.execute(
                        insert(active_character_session_leases).values(
                            character_id=participant.active_character_id,
                            session_id=session_id,
                            participant_id=participant_id,
                        )
                    )
                except IntegrityError as exc:
                    raise CharacterAlreadyLeasedPersistenceError(
                        str(participant.active_character_id)
                    ) from exc

    def create_with_participants(
        self,
        *,
        campaign_id: UUID,
        dm_seat_id: UUID,
        dm_controller_kind: str,
        dm_controller_access_session_id: UUID | None,
        participants: Iterable[ParticipantSeed],
        dm_controller_ai_grant_id: UUID | None = None,
        dm_controller_generation: int | None = None,
    ) -> StoredSession:
        session_id = uuid4()
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as connection:
                self._insert_session_rows(
                    connection,
                    session_id=session_id,
                    campaign_id=campaign_id,
                    dm_seat_id=dm_seat_id,
                    dm_controller_kind=dm_controller_kind,
                    dm_controller_access_session_id=dm_controller_access_session_id,
                    dm_controller_ai_grant_id=dm_controller_ai_grant_id,
                    dm_controller_generation=dm_controller_generation,
                    participants=participants,
                    now=now,
                )
        except CharacterAlreadyLeasedPersistenceError:
            raise
        except IntegrityError as exc:
            raise SessionPersistenceConflictError(str(exc)) from exc
        stored = self.get(session_id)
        if stored is None:
            raise RuntimeError("created Session could not be reloaded")
        return stored

    @staticmethod
    def _lobby_participants(
        connection: Connection,
        *,
        campaign_id: UUID,
        seat_rows,
        dm_seat_id: UUID,
    ) -> list[ParticipantSeed]:
        participants: list[ParticipantSeed] = []
        for row in seat_rows:
            if row["id"] == dm_seat_id:
                continue
            role = row["role"]
            character_id = row["selected_character_id"]
            if role == "player":
                if character_id is None:
                    continue
                eligibility = connection.execute(
                    select(campaign_roster_entries.c.status, characters.c.archived_at)
                    .select_from(
                        campaign_roster_entries
                        .join(campaigns, campaigns.c.id == campaign_roster_entries.c.campaign_id)
                        .join(
                            room_characters,
                            and_(
                                room_characters.c.character_id
                                == campaign_roster_entries.c.character_id,
                                room_characters.c.room_id == campaigns.c.room_id,
                            ),
                        )
                        .join(
                            characters,
                            characters.c.id == campaign_roster_entries.c.character_id,
                        )
                    )
                    .where(
                        campaign_roster_entries.c.campaign_id == campaign_id,
                        campaign_roster_entries.c.character_id == character_id,
                    )
                    .with_for_update()
                ).one_or_none()
                if (
                    eligibility is None
                    or eligibility.status not in {"active", "inactive"}
                    or eligibility.archived_at is not None
                ):
                    raise SessionStartPersistenceError(
                        f"Player Seat {row['id']} has an unavailable Character"
                    )
                participants.append(
                    ParticipantSeed(
                        seat_id=row["id"],
                        role_snapshot="player",
                        controller_kind_at_join=row["controller_kind"],
                        controller_access_session_id_at_join=row[
                            "controller_access_session_id"
                        ],
                        controller_ai_grant_id_at_join=row["ai_controller_grant_id"],
                        controller_generation_at_join=(
                            int(row["controller_epoch"])
                            if row["controller_kind"] == "ai"
                            else None
                        ),
                        active_character_id=character_id,
                    )
                )
            elif role == "spectator" and row["controller_kind"] == "human":
                participants.append(
                    ParticipantSeed(
                        seat_id=row["id"],
                        role_snapshot="spectator",
                        controller_kind_at_join="human",
                        controller_access_session_id_at_join=row[
                            "controller_access_session_id"
                        ],
                        active_character_id=None,
                    )
                )
        return participants

    @staticmethod
    def _lock_start_scope(
        connection: Connection,
        *,
        room_id: UUID,
        campaign_id: UUID,
    ):
        campaign = connection.execute(
            select(campaigns.c.id, campaigns.c.room_id, campaigns.c.status)
            .where(campaigns.c.id == campaign_id)
            .with_for_update()
        ).one_or_none()
        if campaign is None or campaign.room_id != room_id:
            raise SessionStartPersistenceError("Campaign is not in this Room")
        if campaign.status != "active":
            raise SessionStartPersistenceError("Campaign must be active")
        active_campaign_id = connection.scalar(
            select(rooms.c.active_campaign_id)
            .where(rooms.c.id == room_id)
            .with_for_update()
        )
        if active_campaign_id != campaign_id:
            raise SessionStartPersistenceError(
                "Campaign must be selected as the Room's active Campaign"
            )
        if connection.scalar(
            select(sessions.c.id).where(
                sessions.c.campaign_id == campaign_id,
                sessions.c.status == "active",
            )
        ) is not None:
            raise SessionAlreadyActivePersistenceError(str(campaign_id))
        return connection.execute(
            select(campaign_seats)
            .where(
                campaign_seats.c.campaign_id == campaign_id,
                campaign_seats.c.archived_at.is_(None),
            )
            .order_by(campaign_seats.c.created_at, campaign_seats.c.id)
            .with_for_update()
        ).mappings().all()

    def start_from_lobby(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        caller_access_session_id: UUID,
        caller_authority: str,
    ) -> StoredSession:
        session_id = uuid4()
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as connection:
                seat_rows = self._lock_start_scope(
                    connection,
                    room_id=room_id,
                    campaign_id=campaign_id,
                )
                access = connection.execute(
                    select(
                        room_access_sessions.c.id,
                        room_access_sessions.c.room_id,
                        room_access_sessions.c.authority,
                        room_access_sessions.c.revoked_at,
                    ).where(room_access_sessions.c.id == caller_access_session_id)
                ).one_or_none()
                if (
                    access is None
                    or access.room_id != room_id
                    or access.revoked_at is not None
                    or access.authority != caller_authority
                    or caller_authority not in {"dm", "owner"}
                ):
                    raise SessionStartControllerMismatchPersistenceError(
                        "Start requires an active DM or Owner Room access session"
                    )
                dm_seat = next(
                    (
                        row
                        for row in seat_rows
                        if row["role"] == "dm"
                        and row["controller_kind"] == "human"
                        and row["controller_access_session_id"] == caller_access_session_id
                    ),
                    None,
                )
                if dm_seat is None:
                    raise SessionStartControllerMismatchPersistenceError(
                        "Caller is not the Owner-assigned Human DM Seat controller"
                    )
                participants = [
                    ParticipantSeed(
                        seat_id=dm_seat["id"],
                        role_snapshot="dm",
                        controller_kind_at_join="human",
                        controller_access_session_id_at_join=caller_access_session_id,
                        active_character_id=None,
                    ),
                    *self._lobby_participants(
                        connection,
                        campaign_id=campaign_id,
                        seat_rows=seat_rows,
                        dm_seat_id=dm_seat["id"],
                    ),
                ]
                self._insert_session_rows(
                    connection,
                    session_id=session_id,
                    campaign_id=campaign_id,
                    dm_seat_id=dm_seat["id"],
                    dm_controller_kind="human",
                    dm_controller_access_session_id=caller_access_session_id,
                    participants=participants,
                    now=now,
                )
        except (
            CharacterAlreadyLeasedPersistenceError,
            SessionAlreadyActivePersistenceError,
            SessionStartPersistenceError,
        ):
            raise
        except IntegrityError as exc:
            raise SessionPersistenceConflictError(str(exc)) from exc
        stored = self.get(session_id)
        if stored is None:
            raise RuntimeError("started Session could not be reloaded")
        return stored

    def start_from_ai_dm_grant(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        grant_id: UUID,
        generation: int,
    ) -> StoredSession:
        session_id = uuid4()
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as connection:
                seat_rows = self._lock_start_scope(
                    connection,
                    room_id=room_id,
                    campaign_id=campaign_id,
                )
                grant = connection.execute(
                    select(ai_controller_grants)
                    .where(ai_controller_grants.c.id == grant_id)
                    .with_for_update()
                ).mappings().one_or_none()
                if (
                    grant is None
                    or grant["status"] != "active"
                    or grant["role"] != "dm"
                    or grant["room_id"] != room_id
                    or grant["campaign_id"] != campaign_id
                    or grant["session_id"] is not None
                    or grant["pre_session_expires_at"] is None
                    or grant["pre_session_expires_at"] <= now
                    or int(grant["generation"]) != int(generation)
                ):
                    raise SessionStartControllerMismatchPersistenceError(
                        "AI DM grant is expired, stale, or already bound"
                    )
                dm_seat = next(
                    (
                        row
                        for row in seat_rows
                        if row["id"] == grant["seat_id"]
                        and row["role"] == "dm"
                        and row["controller_kind"] == "ai"
                        and row["ai_controller_grant_id"] == grant_id
                        and int(row["controller_epoch"]) == int(generation)
                    ),
                    None,
                )
                if dm_seat is None:
                    raise SessionStartControllerMismatchPersistenceError(
                        "AI DM grant is not the current DM Seat binding"
                    )
                participants = [
                    ParticipantSeed(
                        seat_id=dm_seat["id"],
                        role_snapshot="dm",
                        controller_kind_at_join="ai",
                        controller_access_session_id_at_join=None,
                        controller_ai_grant_id_at_join=grant_id,
                        controller_generation_at_join=int(generation),
                        active_character_id=None,
                    ),
                    *self._lobby_participants(
                        connection,
                        campaign_id=campaign_id,
                        seat_rows=seat_rows,
                        dm_seat_id=dm_seat["id"],
                    ),
                ]
                self._insert_session_rows(
                    connection,
                    session_id=session_id,
                    campaign_id=campaign_id,
                    dm_seat_id=dm_seat["id"],
                    dm_controller_kind="ai",
                    dm_controller_access_session_id=None,
                    dm_controller_ai_grant_id=grant_id,
                    dm_controller_generation=int(generation),
                    participants=participants,
                    now=now,
                )
                bound = connection.execute(
                    update(ai_controller_grants)
                    .where(
                        ai_controller_grants.c.id == grant_id,
                        ai_controller_grants.c.status == "active",
                        ai_controller_grants.c.session_id.is_(None),
                        ai_controller_grants.c.generation == int(generation),
                    )
                    .values(
                        session_id=session_id,
                        pre_session_expires_at=None,
                        bound_at=now,
                        last_seen_at=now,
                    )
                )
                if bound.rowcount != 1:
                    raise SessionStartControllerMismatchPersistenceError(
                        "AI DM grant could not be bound exactly once"
                    )
        except (
            CharacterAlreadyLeasedPersistenceError,
            SessionAlreadyActivePersistenceError,
            SessionStartPersistenceError,
        ):
            raise
        except IntegrityError as exc:
            raise SessionPersistenceConflictError(str(exc)) from exc
        stored = self.get(session_id)
        if stored is None:
            raise RuntimeError("AI DM started Session could not be reloaded")
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
                        controller_ai_grant_id_at_join=(
                            participant.controller_ai_grant_id_at_join
                        ),
                        controller_generation_at_join=(
                            participant.controller_generation_at_join
                        ),
                        active_character_id=participant.active_character_id,
                        joined_at=now,
                        left_at=None,
                    )
                )
                if participant.active_character_id is not None:
                    try:
                        connection.execute(
                            insert(active_character_session_leases).values(
                                character_id=participant.active_character_id,
                                session_id=session_id,
                                participant_id=participant_id,
                            )
                        )
                    except IntegrityError as exc:
                        raise CharacterAlreadyLeasedPersistenceError(
                            str(participant.active_character_id)
                        ) from exc
        except CharacterAlreadyLeasedPersistenceError:
            raise
        except IntegrityError as exc:
            raise SessionPersistenceConflictError(str(exc)) from exc
        stored = self.participant(participant_id)
        if stored is None:
            raise RuntimeError("created Session participant could not be reloaded")
        return stored

    def finalize_in_transaction(
        self,
        connection: Connection,
        *,
        session_id: UUID,
        status: str,
        now: datetime | None = None,
    ) -> bool:
        if status not in {"ended", "abandoned"}:
            raise ValueError("final Session status must be ended or abandoned")
        now = now or datetime.now(timezone.utc)
        row = connection.execute(
            select(sessions.c.status)
            .where(sessions.c.id == session_id)
            .with_for_update()
        ).one_or_none()
        if row is None or row.status != "active":
            return False
        connection.execute(
            update(ai_controller_grants)
            .where(
                ai_controller_grants.c.session_id == session_id,
                ai_controller_grants.c.status == "active",
            )
            .values(
                status="revoked",
                revoked_at=now,
                temporary_instruction=None,
            )
        )
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
        return True

    def finalize(self, session_id: UUID, *, status: str) -> StoredSession | None:
        with self.engine.begin() as connection:
            if not self.finalize_in_transaction(
                connection,
                session_id=session_id,
                status=status,
            ):
                return None
        return self.get(session_id)


__all__ = [
    "CharacterAlreadyLeasedPersistenceError",
    "ParticipantSeed",
    "SessionAlreadyActivePersistenceError",
    "SessionPersistenceConflictError",
    "SessionRepository",
    "SessionStartControllerMismatchPersistenceError",
    "SessionStartPersistenceError",
    "StoredCharacterLease",
    "StoredSession",
    "StoredSessionParticipant",
]
