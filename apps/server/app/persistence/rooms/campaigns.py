from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.persistence.rooms.tables import (
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_characters,
    rooms,
    sessions,
)


@dataclass(frozen=True)
class StoredCampaign:
    id: UUID
    room_id: UUID
    name: str
    ruleset: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredRosterEntry:
    campaign_id: UUID
    character_id: UUID
    status: str
    added_at: datetime
    updated_at: datetime


class CampaignPersistenceConflictError(RuntimeError):
    pass


class CampaignSessionHistoryPersistenceError(RuntimeError):
    pass


class CampaignNotDraftPersistenceError(RuntimeError):
    pass


class CampaignRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _campaign(row) -> StoredCampaign | None:
        return StoredCampaign(**dict(row)) if row is not None else None

    @staticmethod
    def _roster(row) -> StoredRosterEntry | None:
        return StoredRosterEntry(**dict(row)) if row is not None else None

    @staticmethod
    def get_in_transaction(connection: Connection, campaign_id: UUID) -> StoredCampaign | None:
        row = connection.execute(
            select(campaigns).where(campaigns.c.id == campaign_id)
        ).mappings().one_or_none()
        return CampaignRepository._campaign(row)

    @staticmethod
    def character_room_id_in_transaction(
        connection: Connection,
        character_id: UUID,
    ) -> UUID | None:
        return connection.scalar(
            select(room_characters.c.room_id).where(
                room_characters.c.character_id == character_id
            )
        )

    @staticmethod
    def roster_entry_in_transaction(
        connection: Connection,
        *,
        campaign_id: UUID,
        character_id: UUID,
    ) -> StoredRosterEntry | None:
        row = connection.execute(
            select(campaign_roster_entries).where(
                campaign_roster_entries.c.campaign_id == campaign_id,
                campaign_roster_entries.c.character_id == character_id,
            )
        ).mappings().one_or_none()
        return CampaignRepository._roster(row)

    @staticmethod
    def _clear_seat_selection(
        connection: Connection,
        *,
        campaign_id: UUID,
        character_id: UUID,
        updated_at: datetime,
    ) -> None:
        connection.execute(
            update(campaign_seats)
            .where(
                campaign_seats.c.campaign_id == campaign_id,
                campaign_seats.c.selected_character_id == character_id,
            )
            .values(selected_character_id=None, updated_at=updated_at)
        )

    @staticmethod
    def clear_character_seat_selections_in_transaction(
        connection: Connection,
        *,
        room_id: UUID,
        character_id: UUID,
    ) -> None:
        connection.execute(
            update(campaign_seats)
            .where(
                campaign_seats.c.selected_character_id == character_id,
                campaign_seats.c.campaign_id.in_(
                    select(campaigns.c.id).where(campaigns.c.room_id == room_id)
                ),
            )
            .values(
                selected_character_id=None,
                updated_at=datetime.now(timezone.utc),
            )
        )

    def get(self, campaign_id: UUID) -> StoredCampaign | None:
        with self.engine.connect() as connection:
            return self.get_in_transaction(connection, campaign_id)

    def list_for_room(self, room_id: UUID) -> tuple[StoredCampaign, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(campaigns)
                .where(campaigns.c.room_id == room_id)
                .order_by(campaigns.c.created_at, campaigns.c.id)
            ).mappings()
            return tuple(StoredCampaign(**dict(row)) for row in rows)

    def create(
        self,
        *,
        room_id: UUID,
        name: str,
        ruleset: str,
        status: str = "draft",
    ) -> StoredCampaign:
        now = datetime.now(timezone.utc)
        stored = StoredCampaign(
            id=uuid4(),
            room_id=room_id,
            name=name,
            ruleset=ruleset,
            status=status,
            created_at=now,
            updated_at=now,
        )
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(campaigns).values(**stored.__dict__))
        except IntegrityError as exc:
            raise CampaignPersistenceConflictError(str(exc)) from exc
        return stored

    def set_status(self, campaign_id: UUID, status: str) -> StoredCampaign | None:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(campaigns)
                .where(campaigns.c.id == campaign_id)
                .values(status=status, updated_at=now)
            )
            if result.rowcount != 1:
                return None
            return self.get_in_transaction(connection, campaign_id)

    def clear_selection_if_campaign(self, campaign_id: UUID) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(rooms)
                .where(rooms.c.active_campaign_id == campaign_id)
                .values(
                    active_campaign_id=None,
                    updated_at=datetime.now(timezone.utc),
                )
            )

    def select_active_campaign(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID | None,
    ) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(rooms)
                .where(rooms.c.id == room_id)
                .values(
                    active_campaign_id=campaign_id,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            return result.rowcount == 1

    def delete(self, campaign_id: UUID) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(delete(campaigns).where(campaigns.c.id == campaign_id))
            return result.rowcount == 1

    def delete_draft_without_session_history(self, campaign_id: UUID) -> bool:
        """Atomically enforce the P2 hard-delete boundary.

        A Campaign may be hard-deleted only while it is still Draft and has
        never acquired Session history. PostgreSQL locks the Campaign row so a
        concurrent lifecycle transition cannot invalidate the check before the
        delete is issued.
        """
        with self.engine.begin() as connection:
            status_query = select(campaigns.c.status).where(campaigns.c.id == campaign_id)
            if connection.dialect.name == "postgresql":
                status_query = status_query.with_for_update()
            status = connection.scalar(status_query)
            if status is None:
                return False
            if status != "draft":
                raise CampaignNotDraftPersistenceError(campaign_id)
            if connection.scalar(
                select(sessions.c.id)
                .where(sessions.c.campaign_id == campaign_id)
                .limit(1)
            ) is not None:
                raise CampaignSessionHistoryPersistenceError(campaign_id)
            result = connection.execute(delete(campaigns).where(campaigns.c.id == campaign_id))
            return result.rowcount == 1

    def add_roster_entry_same_room(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        character_id: UUID,
        status: str,
    ) -> StoredRosterEntry | None:
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as connection:
                campaign = self.get_in_transaction(connection, campaign_id)
                if campaign is None or campaign.room_id != room_id:
                    return None
                if self.character_room_id_in_transaction(connection, character_id) != room_id:
                    raise ValueError("character_not_in_room")
                existing = self.roster_entry_in_transaction(
                    connection,
                    campaign_id=campaign_id,
                    character_id=character_id,
                )
                if existing is not None:
                    return existing
                connection.execute(
                    insert(campaign_roster_entries).values(
                        campaign_id=campaign_id,
                        character_id=character_id,
                        status=status,
                        added_at=now,
                        updated_at=now,
                    )
                )
                return self.roster_entry_in_transaction(
                    connection,
                    campaign_id=campaign_id,
                    character_id=character_id,
                )
        except IntegrityError as exc:
            # Two add requests can both observe no row and race on the unique
            # (campaign_id, character_id) key. The contract is idempotent, so
            # after the losing transaction rolls back, return the committed
            # winner when it exists instead of leaking a database 500.
            with self.engine.connect() as connection:
                existing = self.roster_entry_in_transaction(
                    connection,
                    campaign_id=campaign_id,
                    character_id=character_id,
                )
            if existing is not None:
                return existing
            raise CampaignPersistenceConflictError(str(exc)) from exc

    def list_roster(self, campaign_id: UUID) -> tuple[StoredRosterEntry, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(campaign_roster_entries)
                .where(campaign_roster_entries.c.campaign_id == campaign_id)
                .order_by(
                    campaign_roster_entries.c.added_at,
                    campaign_roster_entries.c.character_id,
                )
            ).mappings()
            return tuple(StoredRosterEntry(**dict(row)) for row in rows)

    def update_roster_status(
        self,
        *,
        campaign_id: UUID,
        character_id: UUID,
        status: str,
    ) -> StoredRosterEntry | None:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(campaign_roster_entries)
                .where(
                    campaign_roster_entries.c.campaign_id == campaign_id,
                    campaign_roster_entries.c.character_id == character_id,
                )
                .values(status=status, updated_at=now)
            )
            if result.rowcount != 1:
                return None
            if status in {"retired", "dead"}:
                self._clear_seat_selection(
                    connection,
                    campaign_id=campaign_id,
                    character_id=character_id,
                    updated_at=now,
                )
            return self.roster_entry_in_transaction(
                connection,
                campaign_id=campaign_id,
                character_id=character_id,
            )

    def get_roster_entry(
        self,
        campaign_id: UUID,
        character_id: UUID,
    ) -> StoredRosterEntry | None:
        with self.engine.connect() as connection:
            return self.roster_entry_in_transaction(
                connection,
                campaign_id=campaign_id,
                character_id=character_id,
            )

    def remove_roster_entry(
        self,
        *,
        campaign_id: UUID,
        character_id: UUID,
    ) -> bool:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            result = connection.execute(
                delete(campaign_roster_entries).where(
                    campaign_roster_entries.c.campaign_id == campaign_id,
                    campaign_roster_entries.c.character_id == character_id,
                )
            )
            if result.rowcount == 1:
                self._clear_seat_selection(
                    connection,
                    campaign_id=campaign_id,
                    character_id=character_id,
                    updated_at=now,
                )
            return result.rowcount == 1

    def character_is_referenced(self, character_id: UUID) -> bool:
        with self.engine.connect() as connection:
            return (
                connection.scalar(
                    select(campaign_roster_entries.c.character_id)
                    .where(campaign_roster_entries.c.character_id == character_id)
                    .limit(1)
                )
                is not None
            )


__all__ = [
    "CampaignNotDraftPersistenceError",
    "CampaignPersistenceConflictError",
    "CampaignRepository",
    "CampaignSessionHistoryPersistenceError",
    "StoredCampaign",
    "StoredRosterEntry",
]
