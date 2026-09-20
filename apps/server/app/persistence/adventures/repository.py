from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Engine

from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
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


class AdventureRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def insert_definition(self, stored: StoredAdventureDefinition) -> None:
        with self.engine.begin() as connection:
            connection.execute(insert(adventure_definitions).values(**stored.__dict__))

    def get_definition(self, room_id: UUID, adventure_id: UUID) -> StoredAdventureDefinition | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(adventure_definitions).where(
                    adventure_definitions.c.room_id == room_id,
                    adventure_definitions.c.id == adventure_id,
                )
            ).mappings().one_or_none()
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
    ) -> StoredAdventureDefinition | None:
        with self.engine.begin() as connection:
            connection.execute(
                update(adventure_definitions)
                .where(adventure_definitions.c.id == adventure_id)
                .values(status=status, updated_at=updated_at)
            )
            row = connection.execute(
                select(adventure_definitions).where(adventure_definitions.c.id == adventure_id)
            ).mappings().one_or_none()
            return StoredAdventureDefinition(**dict(row)) if row is not None else None

    def insert_entry(self, stored: StoredAdventureEntry) -> None:
        with self.engine.begin() as connection:
            connection.execute(insert(adventure_entries).values(**stored.__dict__))

    def get_entry(self, adventure_id: UUID, entry_id: UUID) -> StoredAdventureEntry | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(adventure_entries).where(
                    adventure_entries.c.adventure_id == adventure_id,
                    adventure_entries.c.id == entry_id,
                )
            ).mappings().one_or_none()
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

    def next_sort_order(self, adventure_id: UUID) -> int:
        with self.engine.connect() as connection:
            val = connection.scalar(
                select(func.coalesce(func.max(adventure_entries.c.sort_order) + 1, 0)).where(
                    adventure_entries.c.adventure_id == adventure_id
                )
            )
            return int(val if val is not None else 0)

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


__all__ = [
    "UNSET",
    "AdventureRepository",
    "StoredAdventureDefinition",
    "StoredAdventureEntry",
]
