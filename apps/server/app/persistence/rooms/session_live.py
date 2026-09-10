from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.persistence.characters import characters
from app.persistence.rooms.sessions import StoredSessionParticipant
from app.persistence.rooms.tables import (
    active_character_session_leases,
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_characters,
    session_participants,
    sessions,
)


class LateJoinPersistenceError(RuntimeError):
    pass


class LateJoinControllerMismatchPersistenceError(LateJoinPersistenceError):
    pass


class LateJoinCharacterLeasedPersistenceError(LateJoinPersistenceError):
    pass


@dataclass(frozen=True)
class ActiveCharacterControl:
    character_id: UUID
    session_id: UUID
    participant_id: UUID
    seat_id: UUID
    dm_controller_kind: str
    dm_controller_access_session_id: UUID | None
    dm_controller_ai_grant_id: UUID | None
    dm_controller_generation: int | None
    player_controller_kind: str
    player_controller_access_session_id: UUID | None
    player_ai_controller_grant_id: UUID | None
    player_controller_epoch: int


class SessionLiveRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _caller_is_current_dm(
        session,
        *,
        caller_actor_kind: str,
        caller_access_session_id: UUID | None,
        caller_ai_grant_id: UUID | None,
        caller_generation: int | None,
    ) -> bool:
        if caller_actor_kind == "human":
            return (
                caller_access_session_id is not None
                and caller_ai_grant_id is None
                and caller_generation is None
                and session.dm_controller_kind == "human"
                and session.dm_controller_access_session_id == caller_access_session_id
            )
        if caller_actor_kind == "ai":
            return (
                caller_access_session_id is None
                and caller_ai_grant_id is not None
                and caller_generation is not None
                and session.dm_controller_kind == "ai"
                and session.dm_controller_ai_grant_id == caller_ai_grant_id
                and session.dm_controller_generation == caller_generation
            )
        return False

    def late_join_from_lobby(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        caller_actor_kind: str,
        seat_id: UUID,
        caller_access_session_id: UUID | None = None,
        caller_ai_grant_id: UUID | None = None,
        caller_generation: int | None = None,
    ) -> StoredSessionParticipant:
        participant_id = uuid4()
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as connection:
                session = connection.execute(
                    select(
                        sessions.c.id,
                        sessions.c.campaign_id,
                        sessions.c.status,
                        sessions.c.dm_controller_kind,
                        sessions.c.dm_controller_access_session_id,
                        sessions.c.dm_controller_ai_grant_id,
                        sessions.c.dm_controller_generation,
                    )
                    .where(sessions.c.id == session_id)
                    .with_for_update()
                ).one_or_none()
                if (
                    session is None
                    or session.campaign_id != campaign_id
                    or session.status != "active"
                ):
                    raise LateJoinPersistenceError("Session is not active in this Campaign")
                campaign_room_id = connection.scalar(
                    select(campaigns.c.room_id).where(campaigns.c.id == campaign_id)
                )
                if campaign_room_id != room_id:
                    raise LateJoinPersistenceError("Session Campaign is not in this Room")
                if not self._caller_is_current_dm(
                    session,
                    caller_actor_kind=caller_actor_kind,
                    caller_access_session_id=caller_access_session_id,
                    caller_ai_grant_id=caller_ai_grant_id,
                    caller_generation=caller_generation,
                ):
                    raise LateJoinControllerMismatchPersistenceError(
                        "Only the current DM Controller may Late Join"
                    )

                seat = connection.execute(
                    select(campaign_seats)
                    .where(
                        campaign_seats.c.id == seat_id,
                        campaign_seats.c.campaign_id == campaign_id,
                        campaign_seats.c.archived_at.is_(None),
                    )
                    .with_for_update()
                ).mappings().one_or_none()
                if seat is None or seat["role"] != "player":
                    raise LateJoinPersistenceError("Late Join requires an active Player Seat")
                if seat["selected_character_id"] is None:
                    raise LateJoinPersistenceError("Late Join Player Seat has no selected Character")
                if connection.scalar(
                    select(session_participants.c.id).where(
                        session_participants.c.session_id == session_id,
                        session_participants.c.seat_id == seat_id,
                    )
                ) is not None:
                    raise LateJoinPersistenceError("Seat already participates in this Session")

                character_id = seat["selected_character_id"]
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
                        .join(characters, characters.c.id == campaign_roster_entries.c.character_id)
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
                    raise LateJoinPersistenceError(
                        "Late Join Character is not eligible in this Campaign roster"
                    )

                connection.execute(
                    insert(session_participants).values(
                        id=participant_id,
                        session_id=session_id,
                        seat_id=seat_id,
                        role_snapshot="player",
                        controller_kind_at_join=seat["controller_kind"],
                        controller_access_session_id_at_join=(
                            seat["controller_access_session_id"]
                        ),
                        controller_ai_grant_id_at_join=(
                            seat["ai_controller_grant_id"]
                            if seat["controller_kind"] == "ai"
                            else None
                        ),
                        controller_generation_at_join=(
                            int(seat["controller_epoch"])
                            if seat["controller_kind"] == "ai"
                            else None
                        ),
                        active_character_id=character_id,
                        joined_at=now,
                        left_at=None,
                    )
                )
                try:
                    connection.execute(
                        insert(active_character_session_leases).values(
                            character_id=character_id,
                            session_id=session_id,
                            participant_id=participant_id,
                        )
                    )
                except IntegrityError as exc:
                    raise LateJoinCharacterLeasedPersistenceError(str(character_id)) from exc
        except (
            LateJoinCharacterLeasedPersistenceError,
            LateJoinControllerMismatchPersistenceError,
            LateJoinPersistenceError,
        ):
            raise
        except IntegrityError as exc:
            raise LateJoinPersistenceError(str(exc)) from exc

        with self.engine.connect() as connection:
            row = connection.execute(
                select(session_participants).where(session_participants.c.id == participant_id)
            ).mappings().one()
        return StoredSessionParticipant(**dict(row))

    def control_for_character(self, character_id: UUID) -> ActiveCharacterControl | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(
                    active_character_session_leases.c.character_id,
                    active_character_session_leases.c.session_id,
                    active_character_session_leases.c.participant_id,
                    session_participants.c.seat_id,
                    sessions.c.dm_controller_kind,
                    sessions.c.dm_controller_access_session_id,
                    sessions.c.dm_controller_ai_grant_id,
                    sessions.c.dm_controller_generation,
                    campaign_seats.c.controller_kind.label("player_controller_kind"),
                    campaign_seats.c.controller_access_session_id.label(
                        "player_controller_access_session_id"
                    ),
                    campaign_seats.c.ai_controller_grant_id.label(
                        "player_ai_controller_grant_id"
                    ),
                    campaign_seats.c.controller_epoch.label("player_controller_epoch"),
                )
                .select_from(
                    active_character_session_leases
                    .join(sessions, sessions.c.id == active_character_session_leases.c.session_id)
                    .join(
                        session_participants,
                        session_participants.c.id == active_character_session_leases.c.participant_id,
                    )
                    .join(campaign_seats, campaign_seats.c.id == session_participants.c.seat_id)
                )
                .where(
                    active_character_session_leases.c.character_id == character_id,
                    sessions.c.status == "active",
                )
            ).mappings().one_or_none()
        if row is None:
            return None
        values = dict(row)
        values["player_controller_epoch"] = int(values["player_controller_epoch"])
        return ActiveCharacterControl(**values)

    def character_is_history_referenced(self, character_id: UUID) -> bool:
        with self.engine.connect() as connection:
            return connection.scalar(
                select(session_participants.c.id)
                .where(session_participants.c.active_character_id == character_id)
                .limit(1)
            ) is not None

    def participant_is_active(
        self,
        *,
        session_id: UUID,
        participant_id: UUID,
    ) -> bool:
        with self.engine.connect() as connection:
            return connection.scalar(
                select(session_participants.c.id)
                .join(sessions, sessions.c.id == session_participants.c.session_id)
                .where(
                    session_participants.c.id == participant_id,
                    session_participants.c.session_id == session_id,
                    sessions.c.status == "active",
                )
            ) is not None


__all__ = [
    "ActiveCharacterControl",
    "LateJoinCharacterLeasedPersistenceError",
    "LateJoinControllerMismatchPersistenceError",
    "LateJoinPersistenceError",
    "SessionLiveRepository",
]
