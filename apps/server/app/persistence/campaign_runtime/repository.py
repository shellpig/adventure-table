from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, Engine, RowMapping

from app.persistence.campaign_runtime.tables import (
    campaign_world_entries,
    campaign_world_entry_characters,
)


class CampaignRuntimePersistenceError(Exception):
    """Base exception for campaign runtime persistence errors."""


class RuntimeWorldEntryNotFoundError(CampaignRuntimePersistenceError, LookupError):
    """Raised when an entry is not found in the target campaign."""

    def __init__(self, campaign_id: UUID, entry_id: UUID) -> None:
        self.campaign_id = campaign_id
        self.entry_id = entry_id
        super().__init__(
            f"Runtime world entry {entry_id} not found in campaign {campaign_id}"
        )


class RuntimeWorldEntryConflictError(CampaignRuntimePersistenceError, RuntimeError):
    """Raised when expected revision does not match current revision or entry is archived."""

    def __init__(
        self,
        campaign_id: UUID,
        entry_id: UUID,
        expected_revision: int,
        current_revision: int,
        message: str | None = None,
    ) -> None:
        self.campaign_id = campaign_id
        self.entry_id = entry_id
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        detail = (
            message
            or f"expected revision {expected_revision} but found {current_revision}"
        )
        super().__init__(
            f"Runtime world entry {entry_id} revision conflict in campaign {campaign_id}: {detail}"
        )


class RuntimeWorldEntryArchivedError(RuntimeWorldEntryConflictError):
    """Raised when attempting to update or re-archive an already-archived entry."""

    def __init__(
        self,
        campaign_id: UUID,
        entry_id: UUID,
        expected_revision: int,
        current_revision: int,
    ) -> None:
        super().__init__(
            campaign_id=campaign_id,
            entry_id=entry_id,
            expected_revision=expected_revision,
            current_revision=current_revision,
            message="entry is already archived",
        )


@dataclass(frozen=True)
class StoredRuntimeWorldEntry:
    id: UUID
    campaign_id: UUID
    kind: str
    title: str | None
    body: str | None
    state_json: dict[str, object]
    dm_notes: str | None
    visibility: str
    needs_review: bool
    source_adventure_entry_id: UUID | None
    provenance_json: dict[str, object] | None
    revision: int
    created_by_actor_kind: str
    created_by_actor_id: UUID | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class StoredRuntimeWorldEntryAggregate:
    entry: StoredRuntimeWorldEntry
    character_recipient_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class StoredRuntimeWorldEntryUpdate:
    expected_revision: int
    title: str | None
    body: str | None
    state_json: dict[str, object]
    dm_notes: str | None
    visibility: str
    needs_review: bool
    source_adventure_entry_id: UUID | None
    provenance_json: dict[str, object] | None
    updated_at: datetime
    character_recipient_ids: tuple[UUID, ...] = ()


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _row_to_stored(row: RowMapping) -> StoredRuntimeWorldEntry:
    created_at = _as_utc(row["created_at"])
    updated_at = _as_utc(row["updated_at"])
    archived_at = _as_utc(row["archived_at"])
    assert created_at is not None
    assert updated_at is not None
    return StoredRuntimeWorldEntry(
        id=row["id"],
        campaign_id=row["campaign_id"],
        kind=row["kind"],
        title=row["title"],
        body=row["body"],
        state_json=row["state_json"],
        dm_notes=row["dm_notes"],
        visibility=row["visibility"],
        needs_review=row["needs_review"],
        source_adventure_entry_id=row["source_adventure_entry_id"],
        provenance_json=row["provenance_json"],
        revision=row["revision"],
        created_by_actor_kind=row["created_by_actor_kind"],
        created_by_actor_id=row["created_by_actor_id"],
        created_at=created_at,
        updated_at=updated_at,
        archived_at=archived_at,
    )


def _batch_load_recipients(
    connection: Connection,
    entry_ids: Sequence[UUID],
) -> dict[UUID, tuple[UUID, ...]]:
    if not entry_ids:
        return {}
    query = (
        select(
            campaign_world_entry_characters.c.world_entry_id,
            campaign_world_entry_characters.c.character_id,
        )
        .where(campaign_world_entry_characters.c.world_entry_id.in_(entry_ids))
        .order_by(
            campaign_world_entry_characters.c.created_at,
            campaign_world_entry_characters.c.character_id,
        )
    )
    rows = connection.execute(query).all()
    recipients_by_entry: dict[UUID, list[UUID]] = {eid: [] for eid in entry_ids}
    for world_entry_id, character_id in rows:
        recipients_by_entry[world_entry_id].append(character_id)
    return {eid: tuple(cids) for eid, cids in recipients_by_entry.items()}


class CampaignRuntimeRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def create_entry_in_transaction(
        connection: Connection,
        entry: StoredRuntimeWorldEntry,
        character_recipient_ids: Sequence[UUID] = (),
    ) -> StoredRuntimeWorldEntryAggregate:
        connection.execute(
            insert(campaign_world_entries).values(
                id=entry.id,
                campaign_id=entry.campaign_id,
                kind=entry.kind,
                title=entry.title,
                body=entry.body,
                state_json=entry.state_json,
                dm_notes=entry.dm_notes,
                visibility=entry.visibility,
                needs_review=entry.needs_review,
                source_adventure_entry_id=entry.source_adventure_entry_id,
                provenance_json=entry.provenance_json,
                revision=entry.revision,
                created_by_actor_kind=entry.created_by_actor_kind,
                created_by_actor_id=entry.created_by_actor_id,
                created_at=entry.created_at,
                updated_at=entry.updated_at,
                archived_at=entry.archived_at,
            )
        )
        recipients = tuple(character_recipient_ids)
        if recipients:
            connection.execute(
                insert(campaign_world_entry_characters),
                [
                    {
                        "world_entry_id": entry.id,
                        "character_id": cid,
                        "created_at": entry.created_at,
                    }
                    for cid in recipients
                ],
            )
        recipient_map = _batch_load_recipients(connection, [entry.id])
        return StoredRuntimeWorldEntryAggregate(
            entry=entry,
            character_recipient_ids=recipient_map.get(entry.id, ()),
        )

    def create_entry(
        self,
        entry: StoredRuntimeWorldEntry,
        character_recipient_ids: Sequence[UUID] = (),
    ) -> StoredRuntimeWorldEntryAggregate:
        with self.engine.begin() as connection:
            return self.create_entry_in_transaction(
                connection,
                entry,
                character_recipient_ids=character_recipient_ids,
            )

    @staticmethod
    def get_entry_in_transaction(
        connection: Connection,
        campaign_id: UUID,
        entry_id: UUID,
        *,
        include_archived: bool = False,
    ) -> StoredRuntimeWorldEntryAggregate | None:
        conditions = [
            campaign_world_entries.c.campaign_id == campaign_id,
            campaign_world_entries.c.id == entry_id,
        ]
        if not include_archived:
            conditions.append(campaign_world_entries.c.archived_at.is_(None))

        row = connection.execute(
            select(campaign_world_entries).where(*conditions)
        ).mappings().one_or_none()
        if row is None:
            return None

        recipient_map = _batch_load_recipients(connection, [entry_id])
        return StoredRuntimeWorldEntryAggregate(
            entry=_row_to_stored(row),
            character_recipient_ids=recipient_map.get(entry_id, ()),
        )

    def get_entry(
        self,
        campaign_id: UUID,
        entry_id: UUID,
        *,
        include_archived: bool = False,
    ) -> StoredRuntimeWorldEntryAggregate | None:
        with self.engine.connect() as connection:
            return self.get_entry_in_transaction(
                connection,
                campaign_id,
                entry_id,
                include_archived=include_archived,
            )

    @staticmethod
    def list_entries_in_transaction(
        connection: Connection,
        campaign_id: UUID,
        *,
        include_archived: bool = False,
    ) -> tuple[StoredRuntimeWorldEntryAggregate, ...]:
        conditions = [campaign_world_entries.c.campaign_id == campaign_id]
        if not include_archived:
            conditions.append(campaign_world_entries.c.archived_at.is_(None))

        query = (
            select(campaign_world_entries)
            .where(*conditions)
            .order_by(campaign_world_entries.c.created_at, campaign_world_entries.c.id)
        )
        rows = connection.execute(query).mappings().all()
        if not rows:
            return ()

        entry_ids = [row["id"] for row in rows]
        recipient_map = _batch_load_recipients(connection, entry_ids)
        return tuple(
            StoredRuntimeWorldEntryAggregate(
                entry=_row_to_stored(row),
                character_recipient_ids=recipient_map.get(row["id"], ()),
            )
            for row in rows
        )

    def list_entries(
        self,
        campaign_id: UUID,
        *,
        include_archived: bool = False,
    ) -> tuple[StoredRuntimeWorldEntryAggregate, ...]:
        with self.engine.connect() as connection:
            return self.list_entries_in_transaction(
                connection,
                campaign_id,
                include_archived=include_archived,
            )

    @staticmethod
    def update_entry_in_transaction(
        connection: Connection,
        campaign_id: UUID,
        entry_id: UUID,
        update_candidate: StoredRuntimeWorldEntryUpdate,
    ) -> StoredRuntimeWorldEntryAggregate:
        stmt = (
            update(campaign_world_entries)
            .where(
                campaign_world_entries.c.id == entry_id,
                campaign_world_entries.c.campaign_id == campaign_id,
                campaign_world_entries.c.revision == update_candidate.expected_revision,
                campaign_world_entries.c.archived_at.is_(None),
            )
            .values(
                title=update_candidate.title,
                body=update_candidate.body,
                state_json=update_candidate.state_json,
                dm_notes=update_candidate.dm_notes,
                visibility=update_candidate.visibility,
                needs_review=update_candidate.needs_review,
                source_adventure_entry_id=update_candidate.source_adventure_entry_id,
                provenance_json=update_candidate.provenance_json,
                revision=campaign_world_entries.c.revision + 1,
                updated_at=update_candidate.updated_at,
            )
        )
        result = connection.execute(stmt)
        if result.rowcount == 0:
            existing = connection.execute(
                select(
                    campaign_world_entries.c.id,
                    campaign_world_entries.c.revision,
                    campaign_world_entries.c.archived_at,
                ).where(
                    campaign_world_entries.c.id == entry_id,
                    campaign_world_entries.c.campaign_id == campaign_id,
                )
            ).mappings().one_or_none()

            if existing is None:
                raise RuntimeWorldEntryNotFoundError(campaign_id, entry_id)
            if existing["archived_at"] is not None:
                raise RuntimeWorldEntryArchivedError(
                    campaign_id=campaign_id,
                    entry_id=entry_id,
                    expected_revision=update_candidate.expected_revision,
                    current_revision=existing["revision"],
                )
            raise RuntimeWorldEntryConflictError(
                campaign_id=campaign_id,
                entry_id=entry_id,
                expected_revision=update_candidate.expected_revision,
                current_revision=existing["revision"],
            )

        # Recipient replacement occurs only after successful row update in same transaction
        connection.execute(
            delete(campaign_world_entry_characters).where(
                campaign_world_entry_characters.c.world_entry_id == entry_id
            )
        )
        recipients = update_candidate.character_recipient_ids
        if recipients:
            connection.execute(
                insert(campaign_world_entry_characters),
                [
                    {
                        "world_entry_id": entry_id,
                        "character_id": cid,
                        "created_at": update_candidate.updated_at,
                    }
                    for cid in recipients
                ],
            )

        row = connection.execute(
            select(campaign_world_entries).where(
                campaign_world_entries.c.id == entry_id,
                campaign_world_entries.c.campaign_id == campaign_id,
            )
        ).mappings().one()

        recipient_map = _batch_load_recipients(connection, [entry_id])
        return StoredRuntimeWorldEntryAggregate(
            entry=_row_to_stored(row),
            character_recipient_ids=recipient_map.get(entry_id, ()),
        )

    def update_entry(
        self,
        campaign_id: UUID,
        entry_id: UUID,
        update_candidate: StoredRuntimeWorldEntryUpdate,
    ) -> StoredRuntimeWorldEntryAggregate:
        with self.engine.begin() as connection:
            return self.update_entry_in_transaction(
                connection,
                campaign_id,
                entry_id,
                update_candidate,
            )

    @staticmethod
    def archive_entry_in_transaction(
        connection: Connection,
        campaign_id: UUID,
        entry_id: UUID,
        *,
        expected_revision: int,
        archived_at: datetime,
    ) -> StoredRuntimeWorldEntryAggregate:
        stmt = (
            update(campaign_world_entries)
            .where(
                campaign_world_entries.c.id == entry_id,
                campaign_world_entries.c.campaign_id == campaign_id,
                campaign_world_entries.c.revision == expected_revision,
                campaign_world_entries.c.archived_at.is_(None),
            )
            .values(
                archived_at=archived_at,
                revision=campaign_world_entries.c.revision + 1,
                updated_at=archived_at,
            )
        )
        result = connection.execute(stmt)
        if result.rowcount == 0:
            existing = connection.execute(
                select(
                    campaign_world_entries.c.id,
                    campaign_world_entries.c.revision,
                    campaign_world_entries.c.archived_at,
                ).where(
                    campaign_world_entries.c.id == entry_id,
                    campaign_world_entries.c.campaign_id == campaign_id,
                )
            ).mappings().one_or_none()

            if existing is None:
                raise RuntimeWorldEntryNotFoundError(campaign_id, entry_id)
            if existing["archived_at"] is not None:
                raise RuntimeWorldEntryArchivedError(
                    campaign_id=campaign_id,
                    entry_id=entry_id,
                    expected_revision=expected_revision,
                    current_revision=existing["revision"],
                )
            raise RuntimeWorldEntryConflictError(
                campaign_id=campaign_id,
                entry_id=entry_id,
                expected_revision=expected_revision,
                current_revision=existing["revision"],
            )

        row = connection.execute(
            select(campaign_world_entries).where(
                campaign_world_entries.c.id == entry_id,
                campaign_world_entries.c.campaign_id == campaign_id,
            )
        ).mappings().one()

        recipient_map = _batch_load_recipients(connection, [entry_id])
        return StoredRuntimeWorldEntryAggregate(
            entry=_row_to_stored(row),
            character_recipient_ids=recipient_map.get(entry_id, ()),
        )

    def archive_entry(
        self,
        campaign_id: UUID,
        entry_id: UUID,
        *,
        expected_revision: int,
        archived_at: datetime,
    ) -> StoredRuntimeWorldEntryAggregate:
        with self.engine.begin() as connection:
            return self.archive_entry_in_transaction(
                connection,
                campaign_id,
                entry_id,
                expected_revision=expected_revision,
                archived_at=archived_at,
            )
