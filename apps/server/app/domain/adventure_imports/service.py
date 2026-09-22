from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Literal
import urllib.parse
from uuid import UUID, uuid4

from sqlalchemy.engine import Connection

from app.config import Settings
from app.domain.adventure_imports.errors import (
    AdventureImportForbiddenError,
    AdventureImportNotFoundError,
    AdventureImportValidationError,
)
from app.domain.adventure_imports.schemas import (
    AdventureImport,
    AdventureImportDraft,
    AdventureImportSource,
    DraftWarning,
    ImportDraft,
    SourceChunk,
    adventure_import_draft_from_stored,
    adventure_import_from_stored,
    adventure_import_source_from_stored,
    validate_draft_warnings,
)
from app.domain.adventures.schemas import (
    AdventureForbiddenError,
    AdventureNotFoundError,
)
from app.domain.adventures.service import require_adventure_author
from app.domain.rooms.schemas import RoomAccessContext
from app.persistence.adventure_imports.repository import (
    AdventureImportRepository,
    StoredAdventureImport,
    StoredAdventureImportSource,
)


def require_import_author(context: RoomAccessContext, room_id: UUID) -> None:
    try:
        require_adventure_author(context, room_id)
    except AdventureNotFoundError as exc:
        raise AdventureImportNotFoundError(message=str(exc)) from exc
    except AdventureForbiddenError as exc:
        raise AdventureImportForbiddenError(str(exc)) from exc


def normalize_source_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = [line.rstrip() for line in text.split("\n")]

    start = 0
    while start < len(raw_lines) and not raw_lines[start]:
        start += 1

    end = len(raw_lines)
    while end > start and not raw_lines[end - 1]:
        end -= 1

    if start >= end:
        return ""

    lines = raw_lines[start:end]

    collapsed: list[str] = []
    consecutive_blank = 0
    for line in lines:
        if not line:
            consecutive_blank += 1
            if consecutive_blank <= 2:
                collapsed.append(line)
        else:
            consecutive_blank = 0
            collapsed.append(line)

    return "\n".join(collapsed) + "\n"


_TERMINAL_STATUSES = ("finalized", "cancelled")


def _text_stats(normalized: str) -> dict[str, object]:
    return {"line_count": len(normalized.splitlines()), "char_count": len(normalized)}


class AdventureImportService:
    def __init__(
        self,
        repository: AdventureImportRepository,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.settings = settings

    def _import_in_room(
        self, connection: Connection, room_id: UUID, import_id: UUID
    ) -> StoredAdventureImport:
        stored = self.repository.get_import_in_transaction(connection, import_id)
        if stored is None or stored.room_id != room_id:
            raise AdventureImportNotFoundError(import_id)
        return stored

    def _writable_import(
        self, connection: Connection, room_id: UUID, import_id: UUID, action: str
    ) -> StoredAdventureImport:
        stored = self._import_in_room(connection, room_id, import_id)
        if stored.status in _TERMINAL_STATUSES:
            raise AdventureImportValidationError(
                f"Cannot {action} on import with status '{stored.status}'"
            )
        return stored

    def _check_source_size(self, raw_bytes_len: int) -> None:
        if raw_bytes_len > self.settings.import_source_max_bytes:
            raise AdventureImportValidationError(
                f"Source size {raw_bytes_len} bytes exceeds limit of "
                f"{self.settings.import_source_max_bytes} bytes"
            )

    def _add_source(
        self,
        room_id: UUID,
        import_id: UUID,
        *,
        source_kind: str,
        source_url: str | None,
        normalized: str,
        sha256: str,
        metadata_json: dict[str, object],
    ) -> AdventureImportSource:
        """Insert a source unless the import already holds one with the same sha256."""
        with self.repository.engine.begin() as connection:
            self._writable_import(connection, room_id, import_id, "add source")
            existing = self.repository.find_source_by_sha256_in_transaction(
                connection, import_id, sha256
            )
            if existing is not None:
                return adventure_import_source_from_stored(existing)
            stored = StoredAdventureImportSource(
                id=uuid4(),
                import_id=import_id,
                asset_id=None,
                source_kind=source_kind,
                source_url=source_url,
                metadata_json=metadata_json,
                sha256=sha256,
                created_at=datetime.now(timezone.utc),
                normalized_text=normalized,
                text_length=len(normalized),
            )
            created = self.repository.add_source_in_transaction(connection, stored)
            if source_kind == "url" and not normalized:
                self._append_warning_in_transaction(
                    connection,
                    import_id,
                    DraftWarning(
                        warning_id=f"source:{created.id}:no_content",
                        level="warning",
                        code="url_source_without_content",
                        message=f"URL source '{source_url}' was added without content",
                        source_id=created.id,
                    ),
                )
            return adventure_import_source_from_stored(created)

    def _append_warning_in_transaction(
        self, connection: Connection, import_id: UUID, warning: DraftWarning
    ) -> None:
        stored_draft = self.repository.get_draft_in_transaction(connection, import_id)
        if stored_draft is None:
            draft_json: dict[str, object] = ImportDraft().model_dump(mode="json")
            warnings_json: list[dict[str, object]] = []
            expected_revision = 0
        else:
            draft_json = stored_draft.draft_json
            warnings_json = list(stored_draft.warnings_json)
            expected_revision = stored_draft.revision
        warnings_json.append(warning.model_dump(mode="json"))
        self.repository.upsert_draft_in_transaction(
            connection, import_id, draft_json, warnings_json, expected_revision
        )

    def create_import(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        name: str,
    ) -> AdventureImport:
        require_import_author(context, room_id)
        name_clean = name.strip()
        if not name_clean or len(name_clean) > 200:
            raise AdventureImportValidationError(
                "Import name must be non-blank and at most 200 characters"
            )

        now = datetime.now(timezone.utc)
        stored = StoredAdventureImport(
            id=uuid4(),
            room_id=room_id,
            name=name_clean,
            status="source",
            target_adventure_id=None,
            revision=0,
            created_at=now,
            updated_at=now,
        )
        created = self.repository.create_import(stored)
        return adventure_import_from_stored(created)

    def list_imports(
        self,
        context: RoomAccessContext,
        room_id: UUID,
    ) -> tuple[AdventureImport, ...]:
        require_import_author(context, room_id)
        stored_imports = self.repository.list_imports(room_id)
        return tuple(adventure_import_from_stored(s) for s in stored_imports)

    def get_import(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
    ) -> AdventureImport:
        require_import_author(context, room_id)
        with self.repository.engine.connect() as connection:
            return adventure_import_from_stored(
                self._import_in_room(connection, room_id, import_id)
            )

    def cancel_import(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
        expected_revision: int,
    ) -> AdventureImport:
        require_import_author(context, room_id)
        with self.repository.engine.begin() as connection:
            self._writable_import(connection, room_id, import_id, "cancel")
            updated = self.repository.update_import_status_in_transaction(
                connection,
                import_id,
                "cancelled",
                expected_revision,
            )
            return adventure_import_from_stored(updated)

    def add_text_source(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
        *,
        source_kind: Literal["paste", "txt", "markdown"],
        text: str | None = None,
        content: bytes | None = None,
        filename: str | None = None,
        media_type: str | None = None,
    ) -> AdventureImportSource:
        require_import_author(context, room_id)
        if (text is None) == (content is None):
            raise AdventureImportValidationError(
                "Exactly one of 'text' or 'content' must be provided"
            )

        if content is not None:
            raw_bytes_len = len(content)
            try:
                decoded_text = content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise AdventureImportValidationError(
                    f"Content could not be decoded as UTF-8: {exc}"
                ) from exc
        else:
            assert text is not None
            raw_bytes_len = len(text.encode("utf-8"))
            decoded_text = text
        self._check_source_size(raw_bytes_len)

        normalized = normalize_source_text(decoded_text)
        return self._add_source(
            room_id,
            import_id,
            source_kind=source_kind,
            source_url=None,
            normalized=normalized,
            sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            metadata_json={
                "filename": filename,
                "media_type": media_type,
                "byte_size": raw_bytes_len,
                **_text_stats(normalized),
            },
        )

    def add_url_source(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
        *,
        url: str,
        text: str | None = None,
        excerpt: str | None = None,
        title: str | None = None,
    ) -> AdventureImportSource:
        """Record a URL the DM or an external AI read; the backend never fetches it.

        Without content the row keys on the URL itself (sha256 of ``url:<url>``) so
        several content-less URLs can coexist and re-adding one stays idempotent.
        """
        require_import_author(context, room_id)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise AdventureImportValidationError(f"Invalid URL: {url}")

        if text is not None:
            raw_bytes_len = len(text.encode("utf-8"))
            self._check_source_size(raw_bytes_len)
            normalized = normalize_source_text(text)
            sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        else:
            raw_bytes_len = 0
            normalized = ""
            sha256 = hashlib.sha256(f"url:{url}".encode("utf-8")).hexdigest()

        return self._add_source(
            room_id,
            import_id,
            source_kind="url",
            source_url=url,
            normalized=normalized,
            sha256=sha256,
            metadata_json={
                "url": url,
                "title": title,
                "excerpt": excerpt,
                "byte_size": raw_bytes_len,
                **_text_stats(normalized),
                "content_provided": text is not None,
            },
        )

    def list_sources(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
    ) -> tuple[AdventureImportSource, ...]:
        require_import_author(context, room_id)
        with self.repository.engine.connect() as connection:
            self._import_in_room(connection, room_id, import_id)
            stored_sources = self.repository.list_sources_in_transaction(connection, import_id)
        return tuple(adventure_import_source_from_stored(s) for s in stored_sources)

    def read_source_chunk(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
        source_id: UUID,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> SourceChunk:
        require_import_author(context, room_id)
        with self.repository.engine.connect() as connection:
            self._import_in_room(connection, room_id, import_id)
            source = self.repository.get_source_in_transaction(connection, source_id)
        if source is None or source.import_id != import_id:
            raise AdventureImportNotFoundError(
                message=f"Source {source_id} not found in import {import_id}"
            )
        assert source.normalized_text is not None

        max_chars = self.settings.import_chunk_max_chars
        if limit is None:
            effective_limit = max_chars
        else:
            if limit <= 0 or limit > max_chars:
                raise AdventureImportValidationError(
                    f"limit {limit} must be between 1 and {max_chars}"
                )
            effective_limit = limit

        total_length = len(source.normalized_text)
        if offset < 0 or offset > total_length:
            raise AdventureImportValidationError(
                f"offset {offset} out of bounds (0..{total_length})"
            )

        chunk_text = source.normalized_text[offset : offset + effective_limit]
        end = offset + len(chunk_text)
        return SourceChunk(
            source_id=source_id,
            offset=offset,
            text=chunk_text,
            total_length=total_length,
            next_offset=None if end >= total_length else end,
        )

    def get_draft(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
    ) -> AdventureImportDraft:
        require_import_author(context, room_id)
        with self.repository.engine.connect() as connection:
            import_record = self._import_in_room(connection, room_id, import_id)
            stored_draft = self.repository.get_draft_in_transaction(connection, import_id)
        if stored_draft is None:
            return AdventureImportDraft(
                import_id=import_id,
                draft=ImportDraft(),
                warnings=[],
                revision=0,
                updated_at=import_record.updated_at,
            )
        return adventure_import_draft_from_stored(stored_draft)

    def update_draft(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
        *,
        draft: ImportDraft,
        warnings: list[DraftWarning],
        expected_revision: int,
    ) -> AdventureImportDraft:
        require_import_author(context, room_id)
        try:
            validate_draft_warnings(warnings)
        except ValueError as exc:
            raise AdventureImportValidationError(str(exc)) from exc

        with self.repository.engine.begin() as connection:
            import_record = self._writable_import(
                connection, room_id, import_id, "update draft"
            )
            valid_source_ids = {
                s.id
                for s in self.repository.list_sources_in_transaction(connection, import_id)
            }
            referenced = [
                (f"Entry '{e.entry_id}'", e.source_ref.source_id)
                for e in draft.entries
                if e.source_ref is not None
            ] + [
                (f"Warning '{w.warning_id}'", w.source_id)
                for w in warnings
                if w.source_id is not None
            ]
            for label, source_id in referenced:
                if source_id not in valid_source_ids:
                    raise AdventureImportValidationError(
                        f"{label} references unknown source '{source_id}'"
                    )

            stored_draft = self.repository.upsert_draft_in_transaction(
                connection,
                import_id,
                draft.model_dump(mode="json"),
                [w.model_dump(mode="json") for w in warnings],
                expected_revision=expected_revision,
            )

            if import_record.status == "source":
                self.repository.update_import_status_in_transaction(
                    connection,
                    import_id,
                    "drafting",
                    expected_revision=import_record.revision,
                )

            return adventure_import_draft_from_stored(stored_draft)


__all__ = [
    "AdventureImportService",
    "normalize_source_text",
    "require_import_author",
]
