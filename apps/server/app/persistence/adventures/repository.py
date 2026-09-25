from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy import delete, exists, func, insert, select, update
from sqlalchemy.engine import Connection, Engine

from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    adventure_entry_assets,
    campaign_adventure_links,
)

UNSET = object()


@dataclass(frozen=True)
class StoredAdventureDefinition:
    id: UUID
    room_id: UUID
    name: str
    summary: str | None
    ruleset: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredAdventureEntry:
    id: UUID
    adventure_id: UUID
    parent_entry_id: UUID | None
    kind: str
    title: str | None
    body: str | None
    data_json: dict[str, object]
    visibility: str
    sort_order: int
    provenance_json: dict[str, object] | None
    source_ref_json: dict[str, object] | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredAdventureEntryAsset:
    adventure_entry_id: UUID
    asset_id: UUID
    role: str
    sort_order: int


@dataclass(frozen=True)
class StoredCampaignAdventureLink:
    campaign_id: UUID
    adventure_id: UUID
    sort_order: int
    attached_at: datetime


class AdventureRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def insert_definition(
        self,
        stored: StoredAdventureDefinition,
        *,
        connection: Connection | None = None,
    ) -> None:
        statement = insert(adventure_definitions).values(**stored.__dict__)
        if connection is not None:
            connection.execute(statement)
            return
        with self.engine.begin() as conn:
            conn.execute(statement)

    def get_definition(
        self,
        room_id: UUID,
        adventure_id: UUID,
        *,
        connection: Connection | None = None,
    ) -> StoredAdventureDefinition | None:
        query = select(adventure_definitions).where(
            adventure_definitions.c.room_id == room_id,
            adventure_definitions.c.id == adventure_id,
        )
        if connection is not None:
            row = connection.execute(query).mappings().one_or_none()
            return StoredAdventureDefinition(**dict(row)) if row is not None else None
        with self.engine.connect() as conn:
            row = conn.execute(query).mappings().one_or_none()
            return StoredAdventureDefinition(**dict(row)) if row is not None else None

    def list_definitions(self, room_id: UUID) -> tuple[StoredAdventureDefinition, ...]:
        with self.engine.connect() as connection:
            query = (
                select(adventure_definitions)
                .where(adventure_definitions.c.room_id == room_id)
                .order_by(adventure_definitions.c.created_at, adventure_definitions.c.id)
            )
            rows = connection.execute(query).mappings().all()
            return tuple(StoredAdventureDefinition(**dict(row)) for row in rows)

    def update_definition(
        self,
        adventure_id: UUID,
        *,
        name: str | None = None,
        summary: str | None | object = UNSET,
        updated_at: datetime,
    ) -> StoredAdventureDefinition | None:
        values: dict[str, object] = {"updated_at": updated_at}
        if name is not None:
            values["name"] = name
        if summary is not UNSET:
            values["summary"] = summary

        with self.engine.begin() as connection:
            connection.execute(
                update(adventure_definitions)
                .where(adventure_definitions.c.id == adventure_id)
                .values(**values)
            )
            row = connection.execute(
                select(adventure_definitions).where(adventure_definitions.c.id == adventure_id)
            ).mappings().one_or_none()
            return StoredAdventureDefinition(**dict(row)) if row is not None else None

    def set_status(
        self,
        adventure_id: UUID,
        status: str,
        updated_at: datetime,
        *,
        connection: Connection | None = None,
    ) -> StoredAdventureDefinition | None:
        statement = (
            update(adventure_definitions)
            .where(adventure_definitions.c.id == adventure_id)
            .values(status=status, updated_at=updated_at)
        )
        query = select(adventure_definitions).where(adventure_definitions.c.id == adventure_id)
        if connection is not None:
            connection.execute(statement)
            row = connection.execute(query).mappings().one_or_none()
            return StoredAdventureDefinition(**dict(row)) if row is not None else None
        with self.engine.begin() as conn:
            conn.execute(statement)
            row = conn.execute(query).mappings().one_or_none()
            return StoredAdventureDefinition(**dict(row)) if row is not None else None

    def insert_entry(
        self,
        stored: StoredAdventureEntry,
        *,
        connection: Connection | None = None,
    ) -> None:
        statement = insert(adventure_entries).values(**stored.__dict__)
        if connection is not None:
            connection.execute(statement)
            return
        with self.engine.begin() as conn:
            conn.execute(statement)

    def get_entry(
        self,
        adventure_id: UUID,
        entry_id: UUID,
        *,
        connection: Connection | None = None,
    ) -> StoredAdventureEntry | None:
        query = select(adventure_entries).where(
            adventure_entries.c.adventure_id == adventure_id,
            adventure_entries.c.id == entry_id,
        )
        if connection is not None:
            row = connection.execute(query).mappings().one_or_none()
            return StoredAdventureEntry(**dict(row)) if row is not None else None
        with self.engine.connect() as conn:
            row = conn.execute(query).mappings().one_or_none()
            return StoredAdventureEntry(**dict(row)) if row is not None else None

    def list_entries(self, adventure_id: UUID) -> tuple[StoredAdventureEntry, ...]:
        with self.engine.connect() as connection:
            query = (
                select(adventure_entries)
                .where(adventure_entries.c.adventure_id == adventure_id)
                .order_by(adventure_entries.c.sort_order, adventure_entries.c.id)
            )
            rows = connection.execute(query).mappings().all()
            return tuple(StoredAdventureEntry(**dict(row)) for row in rows)

    def update_entry(
        self,
        adventure_id: UUID,
        entry_id: UUID,
        *,
        title: str | None | object = UNSET,
        body: str | None | object = UNSET,
        data_json: dict[str, object] | None = None,
        visibility: str | None = None,
        parent_entry_id: UUID | None | object = UNSET,
        updated_at: datetime,
    ) -> StoredAdventureEntry | None:
        values: dict[str, object] = {"updated_at": updated_at}
        if title is not UNSET:
            values["title"] = title
        if body is not UNSET:
            values["body"] = body
        if data_json is not None:
            values["data_json"] = data_json
        if visibility is not None:
            values["visibility"] = visibility
        if parent_entry_id is not UNSET:
            values["parent_entry_id"] = parent_entry_id

        with self.engine.begin() as connection:
            connection.execute(
                update(adventure_entries)
                .where(
                    adventure_entries.c.adventure_id == adventure_id,
                    adventure_entries.c.id == entry_id,
                )
                .values(**values)
            )
            row = connection.execute(
                select(adventure_entries).where(
                    adventure_entries.c.adventure_id == adventure_id,
                    adventure_entries.c.id == entry_id,
                )
            ).mappings().one_or_none()
            return StoredAdventureEntry(**dict(row)) if row is not None else None

    def delete_entry(self, adventure_id: UUID, entry_id: UUID) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                delete(adventure_entries).where(
                    adventure_entries.c.adventure_id == adventure_id,
                    adventure_entries.c.id == entry_id,
                )
            )
            return bool(result.rowcount > 0)

    def next_sort_order(
        self,
        adventure_id: UUID,
        *,
        connection: Connection | None = None,
    ) -> int:
        query = select(
            func.coalesce(func.max(adventure_entries.c.sort_order) + 1, 0)
        ).where(adventure_entries.c.adventure_id == adventure_id)
        if connection is not None:
            val = connection.scalar(query)
            return int(val)
        with self.engine.connect() as conn:
            val = conn.scalar(query)
            return int(val)

    def reorder_entries(
        self,
        adventure_id: UUID,
        entry_ids: Sequence[UUID],
    ) -> bool:
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(adventure_entries.c.id).where(
                    adventure_entries.c.adventure_id == adventure_id,
                    adventure_entries.c.id.in_(entry_ids),
                )
            ).all()
            found_ids = {row[0] for row in rows}
            if len(entry_ids) == 0 or len(set(entry_ids)) != len(entry_ids) or len(found_ids) != len(entry_ids):
                return False
            for idx, entry_id in enumerate(entry_ids):
                connection.execute(
                    update(adventure_entries)
                    .where(
                        adventure_entries.c.adventure_id == adventure_id,
                        adventure_entries.c.id == entry_id,
                    )
                    .values(sort_order=idx)
                )
            return True

    def delete_definition(self, room_id: UUID, adventure_id: UUID) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                delete(adventure_definitions).where(
                    adventure_definitions.c.room_id == room_id,
                    adventure_definitions.c.id == adventure_id,
                )
            )
            return bool(result.rowcount > 0)

    def is_attached(self, adventure_id: UUID) -> bool:
        with self.engine.connect() as connection:
            return bool(
                connection.scalar(
                    select(
                        exists().where(campaign_adventure_links.c.adventure_id == adventure_id)
                    )
                )
            )

    def insert_entry_asset(
        self,
        stored: StoredAdventureEntryAsset,
        *,
        connection: Connection | None = None,
    ) -> None:
        statement = insert(adventure_entry_assets).values(**stored.__dict__)
        if connection is not None:
            connection.execute(statement)
            return
        with self.engine.begin() as conn:
            conn.execute(statement)

    def delete_entry_asset(self, entry_id: UUID, asset_id: UUID) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                delete(adventure_entry_assets).where(
                    adventure_entry_assets.c.adventure_entry_id == entry_id,
                    adventure_entry_assets.c.asset_id == asset_id,
                )
            )
            return bool(result.rowcount > 0)

    def list_entry_assets(
        self,
        adventure_id: UUID,
        *,
        connection: Connection | None = None,
    ) -> tuple[StoredAdventureEntryAsset, ...]:
        query = (
            select(adventure_entry_assets)
            .join(
                adventure_entries,
                adventure_entry_assets.c.adventure_entry_id == adventure_entries.c.id,
            )
            .where(adventure_entries.c.adventure_id == adventure_id)
            .order_by(
                adventure_entry_assets.c.adventure_entry_id,
                adventure_entry_assets.c.sort_order,
                adventure_entry_assets.c.asset_id,
            )
        )
        if connection is not None:
            rows = connection.execute(query).mappings().all()
            return tuple(StoredAdventureEntryAsset(**dict(row)) for row in rows)
        with self.engine.connect() as conn:
            rows = conn.execute(query).mappings().all()
            return tuple(StoredAdventureEntryAsset(**dict(row)) for row in rows)

    def next_entry_asset_sort_order(
        self,
        entry_id: UUID,
        *,
        connection: Connection | None = None,
    ) -> int:
        query = select(
            func.coalesce(func.max(adventure_entry_assets.c.sort_order) + 1, 0)
        ).where(adventure_entry_assets.c.adventure_entry_id == entry_id)
        if connection is not None:
            val = connection.scalar(query)
            return int(val)
        with self.engine.connect() as conn:
            val = conn.scalar(query)
            return int(val)


class CampaignAdventureLinkRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def attach(self, stored: StoredCampaignAdventureLink) -> None:
        with self.engine.begin() as connection:
            connection.execute(insert(campaign_adventure_links).values(**stored.__dict__))

    @staticmethod
    def detach_in_transaction(
        connection: Connection, campaign_id: UUID, adventure_id: UUID
    ) -> bool:
        result = connection.execute(
            delete(campaign_adventure_links).where(
                campaign_adventure_links.c.campaign_id == campaign_id,
                campaign_adventure_links.c.adventure_id == adventure_id,
            )
        )
        return bool(result.rowcount > 0)

    def detach(self, campaign_id: UUID, adventure_id: UUID) -> bool:
        with self.engine.begin() as connection:
            return self.detach_in_transaction(connection, campaign_id, adventure_id)

    def list_for_campaign(
        self, campaign_id: UUID
    ) -> tuple[StoredCampaignAdventureLink, ...]:
        with self.engine.connect() as connection:
            query = (
                select(campaign_adventure_links)
                .where(campaign_adventure_links.c.campaign_id == campaign_id)
                .order_by(
                    campaign_adventure_links.c.sort_order,
                    campaign_adventure_links.c.attached_at,
                    campaign_adventure_links.c.adventure_id,
                )
            )
            rows = connection.execute(query).mappings().all()
            return tuple(StoredCampaignAdventureLink(**dict(row)) for row in rows)

    @staticmethod
    def is_attached_in_transaction(
        connection: Connection, campaign_id: UUID, adventure_id: UUID
    ) -> bool:
        return bool(
            connection.scalar(
                select(
                    exists().where(
                        campaign_adventure_links.c.campaign_id == campaign_id,
                        campaign_adventure_links.c.adventure_id == adventure_id,
                    )
                )
            )
        )

    def is_attached(self, campaign_id: UUID, adventure_id: UUID) -> bool:
        with self.engine.connect() as connection:
            return self.is_attached_in_transaction(connection, campaign_id, adventure_id)

    @staticmethod
    def is_adventure_entry_attached_in_transaction(
        connection: Connection, campaign_id: UUID, adventure_entry_id: UUID
    ) -> bool:
        return bool(
            connection.scalar(
                select(
                    exists().where(
                        campaign_adventure_links.c.campaign_id == campaign_id,
                        campaign_adventure_links.c.adventure_id == adventure_entries.c.adventure_id,
                        adventure_entries.c.id == adventure_entry_id,
                    )
                )
            )
        )

    def is_adventure_entry_attached(
        self, campaign_id: UUID, adventure_entry_id: UUID
    ) -> bool:
        with self.engine.connect() as connection:
            return self.is_adventure_entry_attached_in_transaction(
                connection, campaign_id, adventure_entry_id
            )

    def next_sort_order(self, campaign_id: UUID) -> int:
        with self.engine.connect() as connection:
            val = connection.scalar(
                select(
                    func.coalesce(func.max(campaign_adventure_links.c.sort_order) + 1, 0)
                ).where(campaign_adventure_links.c.campaign_id == campaign_id)
            )
            return int(val)


__all__ = [
    "UNSET",
    "AdventureRepository",
    "CampaignAdventureLinkRepository",
    "StoredAdventureDefinition",
    "StoredAdventureEntry",
    "StoredAdventureEntryAsset",
    "StoredCampaignAdventureLink",
]
