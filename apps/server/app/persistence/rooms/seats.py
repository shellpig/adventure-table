from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.persistence.characters import characters
from app.persistence.rooms.tables import (
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
)


class SeatPersistenceConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredSeat:
    id: UUID
    campaign_id: UUID
    role: str
    label: str | None
    controller_kind: str
    controller_access_session_id: UUID | None
    selected_character_id: UUID | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredSeatAccessSession:
    id: UUID
    room_id: UUID
    authority: str
    display_name: str | None
    last_seen_at: datetime
    revoked_at: datetime | None


class SeatRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _seat(row) -> StoredSeat | None:
        return StoredSeat(**dict(row)) if row is not None else None

    @staticmethod
    def _access(row) -> StoredSeatAccessSession | None:
        if row is None:
            return None
        values = dict(row)
        return StoredSeatAccessSession(
            id=values["id"],
            room_id=values["room_id"],
            authority=values["authority"],
            display_name=values["display_name"],
            last_seen_at=values["last_seen_at"],
            revoked_at=values["revoked_at"],
        )

    def campaign_room_id(self, campaign_id: UUID) -> UUID | None:
        with self.engine.connect() as connection:
            return connection.scalar(select(campaigns.c.room_id).where(campaigns.c.id == campaign_id))

    def campaign_status(self, campaign_id: UUID) -> str | None:
        with self.engine.connect() as connection:
            return connection.scalar(select(campaigns.c.status).where(campaigns.c.id == campaign_id))

    def active_campaign_id(self, room_id: UUID) -> UUID | None:
        with self.engine.connect() as connection:
            return connection.scalar(select(rooms.c.active_campaign_id).where(rooms.c.id == room_id))

    def get(self, seat_id: UUID) -> StoredSeat | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(campaign_seats).where(campaign_seats.c.id == seat_id)).mappings().one_or_none()
        return self._seat(row)

    def list_for_campaign(self, campaign_id: UUID, *, include_archived: bool = False) -> tuple[StoredSeat, ...]:
        query = select(campaign_seats).where(campaign_seats.c.campaign_id == campaign_id)
        if not include_archived:
            query = query.where(campaign_seats.c.archived_at.is_(None))
        query = query.order_by(campaign_seats.c.created_at, campaign_seats.c.id)
        with self.engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return tuple(StoredSeat(**dict(row)) for row in rows)

    def create(self, *, campaign_id: UUID, role: str, label: str | None) -> StoredSeat:
        seat_id = uuid4()
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(campaign_seats).values(
                        id=seat_id,
                        campaign_id=campaign_id,
                        role=role,
                        label=label,
                        controller_kind="none",
                        controller_access_session_id=None,
                        selected_character_id=None,
                        archived_at=None,
                    )
                )
        except IntegrityError as exc:
            raise SeatPersistenceConflictError(str(exc)) from exc
        seat = self.get(seat_id)
        if seat is None:
            raise RuntimeError("created Seat could not be reloaded")
        return seat

    def get_access_session(self, access_session_id: UUID) -> StoredSeatAccessSession | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(room_access_sessions).where(room_access_sessions.c.id == access_session_id)
            ).mappings().one_or_none()
        return self._access(row)

    def list_access_sessions(self, room_id: UUID) -> tuple[StoredSeatAccessSession, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(room_access_sessions)
                .where(
                    room_access_sessions.c.room_id == room_id,
                    room_access_sessions.c.revoked_at.is_(None),
                )
                .order_by(room_access_sessions.c.created_at, room_access_sessions.c.id)
            ).mappings().all()
        return tuple(self._access(row) for row in rows if row is not None)

    def set_controller(
        self,
        *,
        seat_id: UUID,
        controller_kind: str,
        controller_access_session_id: UUID | None,
    ) -> StoredSeat | None:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == seat_id, campaign_seats.c.archived_at.is_(None))
                .values(
                    controller_kind=controller_kind,
                    controller_access_session_id=controller_access_session_id,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        if result.rowcount != 1:
            return None
        return self.get(seat_id)

    def roster_status(self, *, campaign_id: UUID, character_id: UUID) -> str | None:
        with self.engine.connect() as connection:
            return connection.scalar(
                select(campaign_roster_entries.c.status).where(
                    campaign_roster_entries.c.campaign_id == campaign_id,
                    campaign_roster_entries.c.character_id == character_id,
                )
            )

    def character_is_archived(self, character_id: UUID) -> bool | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(characters.c.archived_at).where(characters.c.id == character_id)
            ).one_or_none()
        if row is None:
            return None
        return row[0] is not None

    def character_selected_elsewhere(
        self,
        *,
        campaign_id: UUID,
        character_id: UUID,
        excluding_seat_id: UUID,
    ) -> bool:
        with self.engine.connect() as connection:
            row = connection.scalar(
                select(campaign_seats.c.id).where(
                    campaign_seats.c.campaign_id == campaign_id,
                    campaign_seats.c.id != excluding_seat_id,
                    campaign_seats.c.archived_at.is_(None),
                    campaign_seats.c.selected_character_id == character_id,
                ).limit(1)
            )
        return row is not None

    def set_selected_character(
        self,
        *,
        seat_id: UUID,
        character_id: UUID | None,
    ) -> StoredSeat | None:
        try:
            with self.engine.begin() as connection:
                result = connection.execute(
                    update(campaign_seats)
                    .where(campaign_seats.c.id == seat_id, campaign_seats.c.archived_at.is_(None))
                    .values(
                        selected_character_id=character_id,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
        except IntegrityError as exc:
            raise SeatPersistenceConflictError(str(exc)) from exc
        if result.rowcount != 1:
            return None
        return self.get(seat_id)

    def archive(self, seat_id: UUID) -> StoredSeat | None:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == seat_id, campaign_seats.c.archived_at.is_(None))
                .values(
                    archived_at=now,
                    controller_kind="none",
                    controller_access_session_id=None,
                    selected_character_id=None,
                    updated_at=now,
                )
            )
        if result.rowcount != 1:
            return None
        return self.get(seat_id)

    def delete_unreferenced(self, seat_id: UUID) -> bool:
        # P2-D has no Session tables yet, so every Seat is still unreferenced by
        # Session history. P2-E extends this method with the RESTRICT/history guard.
        with self.engine.begin() as connection:
            result = connection.execute(delete(campaign_seats).where(campaign_seats.c.id == seat_id))
        return result.rowcount == 1


__all__ = [
    "SeatPersistenceConflictError",
    "SeatRepository",
    "StoredSeat",
    "StoredSeatAccessSession",
]
