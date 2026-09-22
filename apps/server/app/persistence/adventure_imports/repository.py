from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine, RowMapping

from app.domain.adventure_imports.errors import (
    AdventureImportNotFoundError,
    AdventureImportRevisionConflictError,
)
from app.persistence.adventure_imports.tables import (
    adventure_import_drafts,
    adventure_import_sources,
    adventure_imports,
)

UNSET = object()


@dataclass(frozen=True)
class StoredAdventureImport:
    id: UUID
    room_id: UUID
    name: str
    status: str
    target_adventure_id: UUID | None
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredAdventureImportSource:
    id: UUID
    import_id: UUID
    asset_id: UUID | None
    source_kind: str
    source_url: str | None
    metadata_json: dict[str, object]
    sha256: str
    created_at: datetime
    normalized_text: str | None = None
    text_length: int = 0


@dataclass(frozen=True)
class StoredAdventureImportDraft:
    import_id: UUID
    draft_json: dict[str, object]
    warnings_json: list[dict[str, object]]
    revision: int
    updated_at: datetime


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _row_to_stored_import(row: RowMapping) -> StoredAdventureImport:
    created_at = _as_utc(row["created_at"])
    updated_at = _as_utc(row["updated_at"])
    assert created_at is not None
    assert updated_at is not None
    return StoredAdventureImport(
        id=row["id"],
        room_id=row["room_id"],
        name=row["name"],
        status=row["status"],
        target_adventure_id=row["target_adventure_id"],
        revision=row["revision"],
        created_at=created_at,
        updated_at=updated_at,
    )


def _row_to_stored_source(
    row: RowMapping,
    *,
    include_text: bool,
) -> StoredAdventureImportSource:
    created_at = _as_utc(row["created_at"])
    assert created_at is not None
    if include_text:
        text = str(row["normalized_text"])
        length = len(text)
    else:
        text = None
        length = int(row["text_length"])
    return StoredAdventureImportSource(
        id=row["id"],
        import_id=row["import_id"],
        asset_id=row["asset_id"],
        source_kind=row["source_kind"],
        source_url=row["source_url"],
        metadata_json=row["metadata_json"],
        sha256=row["sha256"],
        created_at=created_at,
        normalized_text=text,
        text_length=length,
    )


def _row_to_stored_draft(row: RowMapping) -> StoredAdventureImportDraft:
    updated_at = _as_utc(row["updated_at"])
    assert updated_at is not None
    return StoredAdventureImportDraft(
        import_id=row["import_id"],
        draft_json=row["draft_json"],
        warnings_json=row["warnings_json"],
        revision=row["revision"],
        updated_at=updated_at,
    )


class AdventureImportRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def create_import_in_transaction(
        connection: Connection,
        stored: StoredAdventureImport,
    ) -> StoredAdventureImport:
        connection.execute(
            insert(adventure_imports).values(
                id=stored.id,
                room_id=stored.room_id,
                name=stored.name,
                status=stored.status,
                target_adventure_id=stored.target_adventure_id,
                revision=stored.revision,
                created_at=stored.created_at,
                updated_at=stored.updated_at,
            )
        )
        row = connection.execute(
            select(adventure_imports).where(adventure_imports.c.id == stored.id)
        ).mappings().one()
        return _row_to_stored_import(row)

    def create_import(self, stored: StoredAdventureImport) -> StoredAdventureImport:
        with self.engine.begin() as connection:
            return self.create_import_in_transaction(connection, stored)

    @staticmethod
    def get_import_in_transaction(
        connection: Connection,
        import_id: UUID,
    ) -> StoredAdventureImport | None:
        row = connection.execute(
            select(adventure_imports).where(adventure_imports.c.id == import_id)
        ).mappings().one_or_none()
        return _row_to_stored_import(row) if row is not None else None

    def get_import(self, import_id: UUID) -> StoredAdventureImport | None:
        with self.engine.connect() as connection:
            return self.get_import_in_transaction(connection, import_id)

    @staticmethod
    def list_imports_in_transaction(
        connection: Connection,
        room_id: UUID,
    ) -> tuple[StoredAdventureImport, ...]:
        rows = connection.execute(
            select(adventure_imports)
            .where(adventure_imports.c.room_id == room_id)
            .order_by(adventure_imports.c.created_at, adventure_imports.c.id)
        ).mappings().all()
        return tuple(_row_to_stored_import(row) for row in rows)

    def list_imports(self, room_id: UUID) -> tuple[StoredAdventureImport, ...]:
        with self.engine.connect() as connection:
            return self.list_imports_in_transaction(connection, room_id)

    @staticmethod
    def update_import_status_in_transaction(
        connection: Connection,
        import_id: UUID,
        status: str,
        expected_revision: int,
        *,
        target_adventure_id: UUID | None | object = UNSET,
        updated_at: datetime | None = None,
    ) -> StoredAdventureImport:
        now = updated_at or datetime.now(timezone.utc)
        values: dict[str, object] = {
            "status": status,
            "revision": adventure_imports.c.revision + 1,
            "updated_at": now,
        }
        if target_adventure_id is not UNSET:
            values["target_adventure_id"] = target_adventure_id

        stmt = (
            update(adventure_imports)
            .where(
                adventure_imports.c.id == import_id,
                adventure_imports.c.revision == expected_revision,
            )
            .values(**values)
        )
        result = connection.execute(stmt)
        if result.rowcount == 0:
            existing = connection.execute(
                select(adventure_imports.c.revision).where(
                    adventure_imports.c.id == import_id
                )
            ).mappings().one_or_none()
            if existing is None:
                raise AdventureImportNotFoundError(import_id)
            raise AdventureImportRevisionConflictError(
                import_id=import_id,
                expected_revision=expected_revision,
                current_revision=existing["revision"],
            )

        row = connection.execute(
            select(adventure_imports).where(adventure_imports.c.id == import_id)
        ).mappings().one()
        return _row_to_stored_import(row)

    def update_import_status(
        self,
        import_id: UUID,
        status: str,
        expected_revision: int,
        *,
        target_adventure_id: UUID | None | object = UNSET,
        updated_at: datetime | None = None,
    ) -> StoredAdventureImport:
        with self.engine.begin() as connection:
            return self.update_import_status_in_transaction(
                connection,
                import_id,
                status,
                expected_revision,
                target_adventure_id=target_adventure_id,
                updated_at=updated_at,
            )

    @staticmethod
    def add_source_in_transaction(
        connection: Connection,
        source: StoredAdventureImportSource,
    ) -> StoredAdventureImportSource:
        if source.normalized_text is None:
            raise ValueError("normalized_text is required when adding a source")
        connection.execute(
            insert(adventure_import_sources).values(
                id=source.id,
                import_id=source.import_id,
                asset_id=source.asset_id,
                source_kind=source.source_kind,
                source_url=source.source_url,
                normalized_text=source.normalized_text,
                metadata_json=source.metadata_json,
                sha256=source.sha256,
                created_at=source.created_at,
            )
        )
        row = connection.execute(
            select(adventure_import_sources).where(
                adventure_import_sources.c.id == source.id
            )
        ).mappings().one()
        return _row_to_stored_source(row, include_text=True)

    def add_source(
        self,
        source: StoredAdventureImportSource,
    ) -> StoredAdventureImportSource:
        with self.engine.begin() as connection:
            return self.add_source_in_transaction(connection, source)

    @staticmethod
    def get_source_in_transaction(
        connection: Connection,
        source_id: UUID,
    ) -> StoredAdventureImportSource | None:
        row = connection.execute(
            select(adventure_import_sources).where(
                adventure_import_sources.c.id == source_id
            )
        ).mappings().one_or_none()
        return _row_to_stored_source(row, include_text=True) if row is not None else None

    def get_source(self, source_id: UUID) -> StoredAdventureImportSource | None:
        with self.engine.connect() as connection:
            return self.get_source_in_transaction(connection, source_id)

    @staticmethod
    def list_sources_in_transaction(
        connection: Connection,
        import_id: UUID,
    ) -> tuple[StoredAdventureImportSource, ...]:
        query = (
            select(
                adventure_import_sources.c.id,
                adventure_import_sources.c.import_id,
                adventure_import_sources.c.asset_id,
                adventure_import_sources.c.source_kind,
                adventure_import_sources.c.source_url,
                adventure_import_sources.c.metadata_json,
                adventure_import_sources.c.sha256,
                adventure_import_sources.c.created_at,
                func.length(adventure_import_sources.c.normalized_text).label("text_length"),
            )
            .where(adventure_import_sources.c.import_id == import_id)
            .order_by(adventure_import_sources.c.created_at, adventure_import_sources.c.id)
        )
        rows = connection.execute(query).mappings().all()
        return tuple(_row_to_stored_source(row, include_text=False) for row in rows)

    def list_sources(
        self,
        import_id: UUID,
    ) -> tuple[StoredAdventureImportSource, ...]:
        with self.engine.connect() as connection:
            return self.list_sources_in_transaction(connection, import_id)

    @staticmethod
    def find_source_by_sha256_in_transaction(
        connection: Connection,
        import_id: UUID,
        sha256: str,
    ) -> StoredAdventureImportSource | None:
        row = connection.execute(
            select(adventure_import_sources).where(
                adventure_import_sources.c.import_id == import_id,
                adventure_import_sources.c.sha256 == sha256,
            )
        ).mappings().one_or_none()
        return _row_to_stored_source(row, include_text=True) if row is not None else None

    def find_source_by_sha256(
        self,
        import_id: UUID,
        sha256: str,
    ) -> StoredAdventureImportSource | None:
        with self.engine.connect() as connection:
            return self.find_source_by_sha256_in_transaction(connection, import_id, sha256)

    @staticmethod
    def get_draft_in_transaction(
        connection: Connection,
        import_id: UUID,
    ) -> StoredAdventureImportDraft | None:
        row = connection.execute(
            select(adventure_import_drafts).where(
                adventure_import_drafts.c.import_id == import_id
            )
        ).mappings().one_or_none()
        return _row_to_stored_draft(row) if row is not None else None

    def get_draft(self, import_id: UUID) -> StoredAdventureImportDraft | None:
        with self.engine.connect() as connection:
            return self.get_draft_in_transaction(connection, import_id)

    @staticmethod
    def upsert_draft_in_transaction(
        connection: Connection,
        import_id: UUID,
        draft_json: dict[str, object],
        warnings_json: list[dict[str, object]],
        expected_revision: int,
        updated_at: datetime | None = None,
    ) -> StoredAdventureImportDraft:
        now = updated_at or datetime.now(timezone.utc)
        if expected_revision == 0:
            existing = connection.execute(
                select(adventure_import_drafts.c.revision).where(
                    adventure_import_drafts.c.import_id == import_id
                )
            ).mappings().one_or_none()
            if existing is not None:
                raise AdventureImportRevisionConflictError(
                    import_id=import_id,
                    expected_revision=0,
                    current_revision=existing["revision"],
                )
            import_exists = connection.execute(
                select(adventure_imports.c.id).where(adventure_imports.c.id == import_id)
            ).scalar_one_or_none()
            if import_exists is None:
                raise AdventureImportNotFoundError(import_id)
            connection.execute(
                insert(adventure_import_drafts).values(
                    import_id=import_id,
                    draft_json=draft_json,
                    warnings_json=warnings_json,
                    revision=1,
                    updated_at=now,
                )
            )
            row = connection.execute(
                select(adventure_import_drafts).where(
                    adventure_import_drafts.c.import_id == import_id
                )
            ).mappings().one()
            return _row_to_stored_draft(row)

        stmt = (
            update(adventure_import_drafts)
            .where(
                adventure_import_drafts.c.import_id == import_id,
                adventure_import_drafts.c.revision == expected_revision,
            )
            .values(
                draft_json=draft_json,
                warnings_json=warnings_json,
                revision=adventure_import_drafts.c.revision + 1,
                updated_at=now,
            )
        )
        result = connection.execute(stmt)
        if result.rowcount == 0:
            existing = connection.execute(
                select(adventure_import_drafts.c.revision).where(
                    adventure_import_drafts.c.import_id == import_id
                )
            ).mappings().one_or_none()
            if existing is None:
                raise AdventureImportRevisionConflictError(
                    import_id=import_id,
                    expected_revision=expected_revision,
                    current_revision=0,
                    message=f"expected revision {expected_revision} but draft does not exist (virtual revision 0)",
                )
            raise AdventureImportRevisionConflictError(
                import_id=import_id,
                expected_revision=expected_revision,
                current_revision=existing["revision"],
            )

        row = connection.execute(
            select(adventure_import_drafts).where(
                adventure_import_drafts.c.import_id == import_id
            )
        ).mappings().one()
        return _row_to_stored_draft(row)

    def upsert_draft(
        self,
        import_id: UUID,
        draft_json: dict[str, object],
        warnings_json: list[dict[str, object]],
        expected_revision: int,
        updated_at: datetime | None = None,
    ) -> StoredAdventureImportDraft:
        with self.engine.begin() as connection:
            return self.upsert_draft_in_transaction(
                connection,
                import_id,
                draft_json,
                warnings_json,
                expected_revision,
                updated_at=updated_at,
            )


__all__ = [
    "AdventureImportRepository",
    "StoredAdventureImport",
    "StoredAdventureImportDraft",
    "StoredAdventureImportSource",
]
