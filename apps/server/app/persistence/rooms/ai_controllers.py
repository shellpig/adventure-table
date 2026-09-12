from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, Engine

from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    session_participants,
    sessions,
)


class GrantAuthorizationRevoker(Protocol):
    def __call__(
        self,
        connection: Connection,
        grant_ids: tuple[UUID, ...],
        *,
        now: datetime,
    ) -> None: ...


class AIControllerGrantPersistenceError(RuntimeError):
    pass


class AIControllerGrantUnauthorizedPersistenceError(PermissionError):
    pass


class AIControllerHandoffPersistenceError(AIControllerGrantPersistenceError):
    pass


@dataclass(frozen=True)
class StoredAIControllerGrant:
    id: UUID
    room_id: UUID
    campaign_id: UUID
    seat_id: UUID
    role: str
    session_id: UUID | None
    secret_hash: bytes
    secret_prefix: str
    generation: int
    status: str
    pre_session_expires_at: datetime | None
    handoff_return_access_session_id: UUID | None
    temporary_instruction: str | None
    created_at: datetime
    bound_at: datetime | None
    revoked_at: datetime | None
    last_seen_at: datetime | None


@dataclass(frozen=True)
class StoredAIControllerScope:
    grant: StoredAIControllerGrant
    session_id: UUID | None
    active_character_id: UUID | None
    is_current_dm: bool


class AIControllerGrantRepository:
    def __init__(
        self,
        engine: Engine,
        grant_authorization_revoker: GrantAuthorizationRevoker | None = None,
    ) -> None:
        self.engine = engine
        self.grant_authorization_revoker = grant_authorization_revoker

    @staticmethod
    def _grant(row) -> StoredAIControllerGrant | None:
        return StoredAIControllerGrant(**dict(row)) if row is not None else None

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def get(self, grant_id: UUID) -> StoredAIControllerGrant | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(ai_controller_grants).where(ai_controller_grants.c.id == grant_id)
            ).mappings().one_or_none()
        return self._grant(row)

    @staticmethod
    def _active_access(connection: Connection, access_session_id: UUID, room_id: UUID):
        row = connection.execute(
            select(
                room_access_sessions.c.id,
                room_access_sessions.c.room_id,
                room_access_sessions.c.authority,
                room_access_sessions.c.revoked_at,
            )
            .where(room_access_sessions.c.id == access_session_id)
            .with_for_update()
        ).one_or_none()
        if row is None or row.room_id != room_id or row.revoked_at is not None:
            raise AIControllerHandoffPersistenceError(
                "Human access session is not active in this Room"
            )
        return row

    @staticmethod
    def _active_grant_ids_for_seat(
        connection: Connection,
        seat_id: UUID,
    ) -> tuple[UUID, ...]:
        return tuple(
            connection.scalars(
                select(ai_controller_grants.c.id)
                .where(
                    ai_controller_grants.c.seat_id == seat_id,
                    ai_controller_grants.c.status == "active",
                )
                .with_for_update()
            ).all()
        )

    @staticmethod
    def _active_grant_ids_for_session(
        connection: Connection,
        session_id: UUID,
    ) -> tuple[UUID, ...]:
        return tuple(
            connection.scalars(
                select(ai_controller_grants.c.id)
                .where(
                    ai_controller_grants.c.session_id == session_id,
                    ai_controller_grants.c.status == "active",
                )
                .with_for_update()
            ).all()
        )

    def _revoke_grants(
        self,
        connection: Connection,
        grant_ids: tuple[UUID, ...],
        *,
        now: datetime,
    ) -> None:
        if not grant_ids:
            return
        connection.execute(
            update(ai_controller_grants)
            .where(ai_controller_grants.c.id.in_(grant_ids))
            .values(status="revoked", revoked_at=now, temporary_instruction=None)
        )
        if self.grant_authorization_revoker is not None:
            self.grant_authorization_revoker(connection, grant_ids, now=now)

    def player_handoff_in_transaction(
        self,
        connection: Connection,
        *,
        grant_id: UUID,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        seat_id: UUID,
        caller_access_session_id: UUID,
        secret_hash: bytes,
        secret_prefix: str,
        temporary_instruction: str | None,
        now: datetime | None = None,
    ) -> StoredAIControllerGrant:
        now = self._utc(now or datetime.now(timezone.utc))
        session = connection.execute(
            select(sessions.c.id, sessions.c.campaign_id, sessions.c.status)
            .where(sessions.c.id == session_id)
            .with_for_update()
        ).one_or_none()
        if session is None or session.campaign_id != campaign_id or session.status != "active":
            raise AIControllerHandoffPersistenceError("Player handoff requires an active Session")
        if connection.scalar(select(campaigns.c.room_id).where(campaigns.c.id == campaign_id)) != room_id:
            raise AIControllerHandoffPersistenceError("Campaign is not in this Room")
        self._active_access(connection, caller_access_session_id, room_id)

        seat = connection.execute(
            select(campaign_seats)
            .where(
                campaign_seats.c.id == seat_id,
                campaign_seats.c.campaign_id == campaign_id,
                campaign_seats.c.archived_at.is_(None),
            )
            .with_for_update()
        ).mappings().one_or_none()
        if (
            seat is None
            or seat["role"] != "player"
            or seat["controller_kind"] != "human"
            or seat["controller_access_session_id"] != caller_access_session_id
        ):
            raise AIControllerHandoffPersistenceError(
                "Let AI Control requires the exact current Human Player controller"
            )
        participant = connection.execute(
            select(session_participants.c.id, session_participants.c.active_character_id)
            .where(
                session_participants.c.session_id == session_id,
                session_participants.c.seat_id == seat_id,
                session_participants.c.left_at.is_(None),
                session_participants.c.role_snapshot == "player",
            )
            .with_for_update()
        ).one_or_none()
        if participant is None or participant.active_character_id is None:
            raise AIControllerHandoffPersistenceError(
                "Player Seat is not an active Character participant in this Session"
            )

        prior_grant_ids = self._active_grant_ids_for_seat(connection, seat_id)
        self._revoke_grants(connection, prior_grant_ids, now=now)
        generation = int(seat["controller_epoch"]) + 1
        connection.execute(
            insert(ai_controller_grants).values(
                id=grant_id,
                room_id=room_id,
                campaign_id=campaign_id,
                seat_id=seat_id,
                role="player",
                session_id=session_id,
                secret_hash=secret_hash,
                secret_prefix=secret_prefix,
                generation=generation,
                status="active",
                pre_session_expires_at=None,
                handoff_return_access_session_id=caller_access_session_id,
                temporary_instruction=temporary_instruction,
                created_at=now,
                bound_at=now,
                revoked_at=None,
                last_seen_at=None,
            )
        )
        connection.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == seat_id)
            .values(
                controller_kind="ai",
                controller_access_session_id=None,
                ai_controller_grant_id=grant_id,
                controller_epoch=generation,
                updated_at=now,
            )
        )
        row = connection.execute(
            select(ai_controller_grants).where(ai_controller_grants.c.id == grant_id)
        ).mappings().one()
        return self._grant(row)  # type: ignore[return-value]

    def take_back_in_transaction(
        self,
        connection: Connection,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        seat_id: UUID,
        caller_access_session_id: UUID,
        now: datetime | None = None,
    ) -> StoredAIControllerGrant:
        now = self._utc(now or datetime.now(timezone.utc))
        self._active_access(connection, caller_access_session_id, room_id)
        seat = connection.execute(
            select(campaign_seats)
            .where(
                campaign_seats.c.id == seat_id,
                campaign_seats.c.campaign_id == campaign_id,
                campaign_seats.c.archived_at.is_(None),
            )
            .with_for_update()
        ).mappings().one_or_none()
        if seat is None or seat["controller_kind"] != "ai" or seat["ai_controller_grant_id"] is None:
            raise AIControllerHandoffPersistenceError("Seat is not currently AI controlled")
        grant_row = connection.execute(
            select(ai_controller_grants)
            .where(ai_controller_grants.c.id == seat["ai_controller_grant_id"])
            .with_for_update()
        ).mappings().one_or_none()
        grant = self._grant(grant_row)
        if (
            grant is None
            or grant.status != "active"
            or grant.session_id != session_id
            or grant.seat_id != seat_id
            or grant.generation != int(seat["controller_epoch"])
            or grant.handoff_return_access_session_id != caller_access_session_id
        ):
            raise AIControllerHandoffPersistenceError(
                "Take Back requires the exact still-active handoff origin access session"
            )
        next_epoch = int(seat["controller_epoch"]) + 1
        self._revoke_grants(connection, (grant.id,), now=now)
        connection.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == seat_id)
            .values(
                controller_kind="human",
                controller_access_session_id=caller_access_session_id,
                ai_controller_grant_id=None,
                controller_epoch=next_epoch,
                updated_at=now,
            )
        )
        return grant

    def admin_reassign_in_transaction(
        self,
        connection: Connection,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        seat_id: UUID,
        admin_access_session_id: UUID,
        target_access_session_id: UUID,
        now: datetime | None = None,
    ) -> StoredAIControllerGrant:
        now = self._utc(now or datetime.now(timezone.utc))
        admin_access = self._active_access(connection, admin_access_session_id, room_id)
        if admin_access.authority not in {"owner", "dm"}:
            raise AIControllerHandoffPersistenceError(
                "Administrative reassignment requires active Owner or DM authority"
            )
        self._active_access(connection, target_access_session_id, room_id)
        seat = connection.execute(
            select(campaign_seats)
            .where(
                campaign_seats.c.id == seat_id,
                campaign_seats.c.campaign_id == campaign_id,
                campaign_seats.c.archived_at.is_(None),
            )
            .with_for_update()
        ).mappings().one_or_none()
        if (
            seat is None
            or seat["role"] != "player"
            or seat["controller_kind"] != "ai"
            or seat["ai_controller_grant_id"] is None
        ):
            raise AIControllerHandoffPersistenceError(
                "Administrative reassignment requires an AI-controlled Player Seat"
            )
        grant_row = connection.execute(
            select(ai_controller_grants)
            .where(ai_controller_grants.c.id == seat["ai_controller_grant_id"])
            .with_for_update()
        ).mappings().one_or_none()
        grant = self._grant(grant_row)
        if (
            grant is None
            or grant.status != "active"
            or grant.session_id != session_id
            or grant.seat_id != seat_id
            or grant.campaign_id != campaign_id
            or grant.generation != int(seat["controller_epoch"])
        ):
            raise AIControllerHandoffPersistenceError("Current AI grant is stale")
        next_epoch = int(seat["controller_epoch"]) + 1
        self._revoke_grants(connection, (grant.id,), now=now)
        connection.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == seat_id)
            .values(
                controller_kind="human",
                controller_access_session_id=target_access_session_id,
                ai_controller_grant_id=None,
                controller_epoch=next_epoch,
                updated_at=now,
            )
        )
        return grant

    def mint_pre_session_dm(
        self,
        *,
        grant_id: UUID,
        room_id: UUID,
        campaign_id: UUID,
        seat_id: UUID,
        secret_hash: bytes,
        secret_prefix: str,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> StoredAIControllerGrant:
        now = self._utc(now or datetime.now(timezone.utc))
        expires_at = self._utc(expires_at)
        if expires_at <= now:
            raise AIControllerHandoffPersistenceError("pre-session AI DM grant must have a future expiry")
        with self.engine.begin() as connection:
            campaign = connection.execute(
                select(campaigns.c.room_id, campaigns.c.status)
                .where(campaigns.c.id == campaign_id)
                .with_for_update()
            ).one_or_none()
            if campaign is None or campaign.room_id != room_id or campaign.status != "active":
                raise AIControllerHandoffPersistenceError("Campaign is not Start-eligible")
            active_campaign = connection.scalar(
                select(rooms.c.active_campaign_id)
                .where(rooms.c.id == room_id)
                .with_for_update()
            )
            if active_campaign != campaign_id:
                raise AIControllerHandoffPersistenceError("Campaign is not the Room active Campaign")
            if connection.scalar(
                select(sessions.c.id).where(
                    sessions.c.campaign_id == campaign_id,
                    sessions.c.status == "active",
                )
            ) is not None:
                raise AIControllerHandoffPersistenceError(
                    "AI DM grant cannot rotate while a Session is active"
                )
            seat = connection.execute(
                select(campaign_seats)
                .where(
                    campaign_seats.c.id == seat_id,
                    campaign_seats.c.campaign_id == campaign_id,
                    campaign_seats.c.role == "dm",
                    campaign_seats.c.archived_at.is_(None),
                )
                .with_for_update()
            ).mappings().one_or_none()
            if seat is None:
                raise AIControllerHandoffPersistenceError("active DM Seat was not found")
            prior_grant_ids = self._active_grant_ids_for_seat(connection, seat_id)
            self._revoke_grants(connection, prior_grant_ids, now=now)
            generation = int(seat["controller_epoch"]) + 1
            connection.execute(
                insert(ai_controller_grants).values(
                    id=grant_id,
                    room_id=room_id,
                    campaign_id=campaign_id,
                    seat_id=seat_id,
                    role="dm",
                    session_id=None,
                    secret_hash=secret_hash,
                    secret_prefix=secret_prefix,
                    generation=generation,
                    status="active",
                    pre_session_expires_at=expires_at,
                    handoff_return_access_session_id=None,
                    temporary_instruction=None,
                    created_at=now,
                    bound_at=None,
                    revoked_at=None,
                    last_seen_at=None,
                )
            )
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == seat_id)
                .values(
                    controller_kind="ai",
                    controller_access_session_id=None,
                    ai_controller_grant_id=grant_id,
                    controller_epoch=generation,
                    updated_at=now,
                )
            )
        stored = self.get(grant_id)
        if stored is None:
            raise RuntimeError("created AI DM grant could not be reloaded")
        return stored

    def resolve_current_scope(
        self,
        grant_id: UUID,
        *,
        now: datetime | None = None,
        touch: bool = False,
    ) -> StoredAIControllerScope:
        now = self._utc(now or datetime.now(timezone.utc))
        denied_reason: str | None = None
        grant: StoredAIControllerGrant | None = None
        active_character_id = None
        is_current_dm = False

        with self.engine.begin() if touch else self.engine.connect() as connection:
            row = connection.execute(
                select(ai_controller_grants).where(ai_controller_grants.c.id == grant_id)
            ).mappings().one_or_none()
            grant = self._grant(row)
            if grant is None or grant.status != "active":
                denied_reason = "AI controller grant is revoked or unknown"
            else:
                seat = connection.execute(
                    select(campaign_seats)
                    .where(
                        campaign_seats.c.id == grant.seat_id,
                        campaign_seats.c.campaign_id == grant.campaign_id,
                        campaign_seats.c.archived_at.is_(None),
                    )
                ).mappings().one_or_none()
                if (
                    seat is None
                    or seat["controller_kind"] != "ai"
                    or seat["ai_controller_grant_id"] != grant.id
                    or int(seat["controller_epoch"]) != grant.generation
                ):
                    denied_reason = "AI controller grant is stale"
                else:
                    campaign = connection.execute(
                        select(campaigns.c.room_id, campaigns.c.status).where(
                            campaigns.c.id == grant.campaign_id
                        )
                    ).one_or_none()
                    if campaign is None or campaign.room_id != grant.room_id:
                        denied_reason = "AI controller grant scope is invalid"
                    elif grant.session_id is None:
                        active_campaign_id = connection.scalar(
                            select(rooms.c.active_campaign_id).where(rooms.c.id == grant.room_id)
                        )
                        expires_at = (
                            self._utc(grant.pre_session_expires_at)
                            if grant.pre_session_expires_at is not None
                            else None
                        )
                        if (
                            grant.role != "dm"
                            or expires_at is None
                            or expires_at <= now
                            or campaign.status != "active"
                            or active_campaign_id != grant.campaign_id
                        ):
                            denied_reason = (
                                "pre-session AI DM grant is expired or no longer Start-eligible"
                            )
                    else:
                        session = connection.execute(
                            select(sessions).where(sessions.c.id == grant.session_id)
                        ).mappings().one_or_none()
                        if (
                            session is None
                            or session["campaign_id"] != grant.campaign_id
                            or session["status"] != "active"
                        ):
                            denied_reason = "AI grant Session is not active"
                        elif grant.role == "dm":
                            is_current_dm = (
                                session["dm_controller_kind"] == "ai"
                                and session["dm_controller_ai_grant_id"] == grant.id
                                and session["dm_controller_generation"] == grant.generation
                            )
                            if not is_current_dm:
                                denied_reason = "AI DM grant is not fixed current DM"
                        else:
                            participant = connection.execute(
                                select(
                                    session_participants.c.active_character_id,
                                    session_participants.c.role_snapshot,
                                ).where(
                                    session_participants.c.session_id == grant.session_id,
                                    session_participants.c.seat_id == grant.seat_id,
                                    session_participants.c.left_at.is_(None),
                                )
                            ).one_or_none()
                            if (
                                participant is None
                                or participant.role_snapshot != "player"
                                or participant.active_character_id is None
                            ):
                                denied_reason = "AI Player is not a live participant"
                            else:
                                active_character_id = participant.active_character_id

                if denied_reason is not None and touch:
                    self._revoke_grants(connection, (grant.id,), now=now)
                elif denied_reason is None and touch:
                    connection.execute(
                        update(ai_controller_grants)
                        .where(ai_controller_grants.c.id == grant.id)
                        .values(last_seen_at=now)
                    )

        if denied_reason is not None or grant is None:
            raise AIControllerGrantUnauthorizedPersistenceError(
                denied_reason or "AI controller grant is revoked or unknown"
            )
        return StoredAIControllerScope(
            grant=grant,
            session_id=grant.session_id,
            active_character_id=active_character_id,
            is_current_dm=is_current_dm,
        )

    def revoke_session_grants_in_transaction(
        self,
        connection: Connection,
        *,
        session_id: UUID,
        now: datetime | None = None,
    ) -> None:
        now = self._utc(now or datetime.now(timezone.utc))
        grant_ids = self._active_grant_ids_for_session(connection, session_id)
        self._revoke_grants(connection, grant_ids, now=now)


__all__ = [
    "AIControllerGrantPersistenceError",
    "AIControllerGrantRepository",
    "AIControllerGrantUnauthorizedPersistenceError",
    "AIControllerHandoffPersistenceError",
    "GrantAuthorizationRevoker",
    "StoredAIControllerGrant",
    "StoredAIControllerScope",
]
