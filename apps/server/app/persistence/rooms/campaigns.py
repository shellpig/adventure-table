from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.persistence.characters import characters
from app.persistence.rooms.tables import (
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_characters,
    rooms,
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

    def create(
        self,
        *,
        room_id: UUID,
        name: str,
        ruleset: str,
        status: str,
    ) -> StoredCampaign:
        campaign_id = uuid4()
        with self.engine.begin() as connection:
            connection.execute(
                insert(campaigns).values(
                    id=campaign_id,
                    room_id=room_id,
                    name=name,
                    ruleset=ruleset,
                    status=status,
                )
            )
        campaign = self.get(campaign_id)
        if campaign is None:
            raise RuntimeError("created Campaign could not be reloaded")
        return campaign

    def get(self, campaign_id: UUID) -> StoredCampaign | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(campaigns).where(campaigns.c.id == campaign_id)
            ).mappings().one_or_none()
        return self._campaign(row)

    def list_for_room(self, room_id: UUID) -> tuple[StoredCampaign, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(campaigns)
                .where(campaigns.c.room_id == room_id)
                .order_by(campaigns.c.created_at, campaigns.c.id)
            ).mappings().all()
        return tuple(StoredCampaign(**dict(row)) for row in rows)

    def set_status(self, campaign_id: UUID, status: str) -> StoredCampaign | None:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(campaigns)
                .where(campaigns.c.id == campaign_id)
                .values(status=status, updated_at=datetime.now(timezone.utc))
            )
        if result.rowcount != 1:
            return None
        return self.get(campaign_id)

    def select_active_campaign(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID | None,
    ) -> bool:
        with self.engine.begin() as connection:
            if campaign_id is not None:
                selected = connection.scalar(
                    select(campaigns.c.id).where(
                        campaigns.c.id == campaign_id,
                        campaigns.c.room_id == room_id,
                    )
                )
                if selected is None:
                    return False
            result = connection.execute(
                update(rooms)
                .where(rooms.c.id == room_id)
                .values(
                    active_campaign_id=campaign_id,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        return result.rowcount == 1

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
                eligible = connection.scalar(
                    select(characters.c.id)
                    .select_from(
                        room_characters.join(
                            campaigns,
                            campaigns.c.room_id == room_characters.c.room_id,
                        )
                    )
                    .where(
                        campaigns.c.id == campaign_id,
                        campaigns.c.room_id == room_id,
                        room_characters.c.character_id == character_id,
                        characters.c.id == room_characters.c.character_id,
                    )
                )
                if eligible is None:
                    raise ValueError("character_not_in_room")
                connection.execute(
                    insert(campaign_roster_entries).values(
                        campaign_id=campaign_id,
                        character_id=character_id,
                        status=status,
                        added_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError:
            existing = self.get_roster_entry(campaign_id, character_id)
            if existing is not None:
                return existing
            raise
        return self.get_roster_entry(campaign_id, character_id)

    def list_roster(self, campaign_id: UUID) -> tuple[StoredRosterEntry, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(campaign_roster_entries)
                .where(campaign_roster_entries.c.campaign_id == campaign_id)
                .order_by(
                    campaign_roster_entries.c.added_at,
                    campaign_roster_entries.c.character_id,
                )
            ).mappings().all()
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
            if result.rowcount == 1 and status in {"retired", "dead"}:
                self._clear_seat_selection(
                    connection,
                    campaign_id=campaign_id,
                    character_id=character_id,
                    updated_at=now,
                )
        if result.rowcount != 1:
            return None
        return self.get_roster_entry(campaign_id, character_id)

    def get_roster_entry(
        self,
        campaign_id: UUID,
        character_id: UUID,
    ) -> StoredRosterEntry | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(campaign_roster_entries).where(
                    campaign_roster_entries.c.campaign_id == campaign_id,
                    campaign_roster_entries.c.character_id == character_id,
                )
            ).mappings().one_or_none()
        return self._roster(row)

    def remove_roster_entry(self, *, campaign_id: UUID, character_id: UUID) -> bool:
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

    def delete(self, campaign_id: UUID) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(delete(campaigns).where(campaigns.c.id == campaign_id))
        return result.rowcount == 1


__all__ = ["CampaignRepository", "StoredCampaign", "StoredRosterEntry"]
