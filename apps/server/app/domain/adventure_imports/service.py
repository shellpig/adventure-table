from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Callable, Literal, cast
import urllib.parse
from uuid import UUID, uuid4

from sqlalchemy.engine import Connection

from app.config import Settings
from app.domain.adventure_imports.errors import (
    AdventureImportBlockingWarningsError,
    AdventureImportForbiddenError,
    AdventureImportNotFoundError,
    AdventureImportRevisionConflictError,
    AdventureImportValidationError,
    ExtractorUnavailableError,
)
from app.domain.adventure_imports.extractors import (
    extract_docx_text,
    extract_pdf_text,
)
from app.domain.adventure_imports.schemas import (
    AdventureImport,
    AdventureImportDraft,
    AdventureImportSource,
    DraftEntry,
    DraftQuestion,
    DraftWarning,
    ImportDraft,
    ReviewStatus,
    SourceChunk,
    adventure_import_draft_from_stored,
    adventure_import_from_stored,
    adventure_import_source_from_stored,
    unresolved_blocking_warnings,
    validate_draft_warnings,
)
from app.domain.adventures.payloads import dump_entry_payload
from app.domain.adventures.schemas import (
    AdventureDefinition,
    AdventureDefinitionCreate,
    AdventureEntryAssetLink,
    AdventureEntryCreate,
    AdventureForbiddenError,
    AdventureNotFoundError,
)
from app.domain.adventures.service import AdventureService, require_adventure_author
from app.domain.room_assets.schemas import (
    RoomAssetForbiddenError,
    RoomAssetNotFoundError,
)
from app.domain.room_assets.service import RoomAssetService
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

_ASSET_MIME_TO_SOURCE_KIND: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "markdown",
}


def _text_stats(normalized: str) -> dict[str, object]:
    return {"line_count": len(normalized.splitlines()), "char_count": len(normalized)}


class AdventureImportService:
    def __init__(
        self,
        repository: AdventureImportRepository,
        settings: Settings,
        room_asset_service: RoomAssetService,
        adventure_service: AdventureService,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.room_asset_service = room_asset_service
        self.adventure_service = adventure_service

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
        asset_id: UUID | None = None,
        warning: tuple[str, str] | None = None,
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
                asset_id=asset_id,
                source_kind=source_kind,
                source_url=source_url,
                metadata_json=metadata_json,
                sha256=sha256,
                created_at=datetime.now(timezone.utc),
                normalized_text=normalized,
                text_length=len(normalized),
            )
            created = self.repository.add_source_in_transaction(connection, stored)
            if warning is not None:
                warning_code, warning_message = warning
                self._append_warning_in_transaction(
                    connection,
                    import_id,
                    DraftWarning(
                        warning_id=f"source:{created.id}:{warning_code}",
                        level="warning",
                        code=warning_code,
                        message=warning_message,
                        source_id=created.id,
                    ),
                )
            elif source_kind == "url" and not normalized:
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

    def _add_text_or_content_source(
        self,
        room_id: UUID,
        import_id: UUID,
        *,
        source_kind: Literal["paste", "txt", "markdown"],
        text: str | None = None,
        content: bytes | None = None,
        filename: str | None = None,
        media_type: str | None = None,
        asset_id: UUID | None = None,
    ) -> AdventureImportSource:
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
        if asset_id is not None:
            sha256 = hashlib.sha256(
                f"asset:{asset_id}:{normalized}".encode("utf-8")
            ).hexdigest()
        else:
            sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return self._add_source(
            room_id,
            import_id,
            source_kind=source_kind,
            source_url=None,
            normalized=normalized,
            sha256=sha256,
            metadata_json={
                "filename": filename,
                "media_type": media_type,
                "byte_size": raw_bytes_len,
                **_text_stats(normalized),
            },
            asset_id=asset_id,
        )

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
        return self._add_text_or_content_source(
            room_id,
            import_id,
            source_kind=source_kind,
            text=text,
            content=content,
            filename=filename,
            media_type=media_type,
            asset_id=None,
        )

    def add_asset_source(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
        *,
        asset_id: UUID,
    ) -> AdventureImportSource:
        require_import_author(context, room_id)
        try:
            asset, handle = self.room_asset_service.open_content(
                context, room_id, asset_id
            )
        except RoomAssetNotFoundError as exc:
            raise AdventureImportNotFoundError(message=str(exc)) from exc
        except RoomAssetForbiddenError as exc:
            raise AdventureImportForbiddenError(str(exc)) from exc

        with handle:
            if asset.kind != "source_document":
                raise AdventureImportValidationError(
                    f"Asset {asset_id} kind '{asset.kind}' is not 'source_document'"
                )

            if asset.mime_type not in _ASSET_MIME_TO_SOURCE_KIND:
                raise AdventureImportValidationError(
                    f"Asset {asset_id} media type '{asset.mime_type}' is not supported for import"
                )

            source_kind = _ASSET_MIME_TO_SOURCE_KIND[asset.mime_type]
            data = handle.read(self.settings.import_source_max_bytes + 1)

        self._check_source_size(len(data))

        if source_kind in ("txt", "markdown"):
            return self._add_text_or_content_source(
                room_id,
                import_id,
                source_kind=cast(Literal["txt", "markdown"], source_kind),
                content=data,
                filename=asset.original_filename,
                media_type=asset.mime_type,
                asset_id=asset.id,
            )

        warning: tuple[str, str] | None = None
        sections: list[dict[str, object]] = []
        normalized = ""

        try:
            if source_kind == "pdf":
                result = extract_pdf_text(data)
            else:
                result = extract_docx_text(data)
            normalized = result.normalized_text
            sections = [dict(s) for s in result.sections]
            if not normalized:
                warning = (
                    "empty_extraction",
                    (
                        f"No text could be extracted from {source_kind.upper()} "
                        f"asset '{asset.original_filename}'"
                    ),
                )
        except ExtractorUnavailableError as exc:
            warning = ("extractor_unavailable", str(exc))

        sha256 = hashlib.sha256(
            f"asset:{asset.id}:{normalized}".encode("utf-8")
        ).hexdigest()

        return self._add_source(
            room_id,
            import_id,
            source_kind=source_kind,
            source_url=None,
            normalized=normalized,
            sha256=sha256,
            metadata_json={
                "filename": asset.original_filename,
                "media_type": asset.mime_type,
                "byte_size": len(data),
                **_text_stats(normalized),
                "sections": sections,
            },
            asset_id=asset.id,
            warning=warning,
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

    def _load_draft_state(
        self,
        connection: Connection,
        import_id: UUID,
        expected_revision: int,
    ) -> tuple[ImportDraft, list[DraftWarning]]:
        stored_draft = self.repository.get_draft_in_transaction(
            connection, import_id
        )
        if stored_draft is None:
            current_draft = ImportDraft()
            current_warnings: list[DraftWarning] = []
            current_revision = 0
        else:
            current_draft = ImportDraft.model_validate(stored_draft.draft_json)
            current_warnings = [
                DraftWarning.model_validate(w) for w in stored_draft.warnings_json
            ]
            current_revision = stored_draft.revision

        if current_revision != expected_revision:
            raise AdventureImportRevisionConflictError(
                import_id=import_id,
                expected_revision=expected_revision,
                current_revision=current_revision,
            )
        return current_draft, current_warnings

    def _apply_draft_mutation(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
        action: str,
        expected_revision: int,
        mutator: Callable[
            [ImportDraft, list[DraftWarning]],
            tuple[ImportDraft, list[DraftWarning]],
        ],
    ) -> AdventureImportDraft:
        require_import_author(context, room_id)
        with self.repository.engine.begin() as connection:
            self._writable_import(connection, room_id, import_id, action)
            current_draft, current_warnings = self._load_draft_state(
                connection, import_id, expected_revision
            )
            updated_draft, updated_warnings = mutator(
                current_draft, current_warnings
            )

            stored = self.repository.upsert_draft_in_transaction(
                connection,
                import_id,
                updated_draft.model_dump(mode="json"),
                [w.model_dump(mode="json") for w in updated_warnings],
                expected_revision=expected_revision,
            )
            return adventure_import_draft_from_stored(stored)

    def set_entry_review(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
        *,
        entry_id: str,
        review_status: ReviewStatus,
        expected_revision: int,
    ) -> AdventureImportDraft:
        def _mutate(
            draft: ImportDraft,
            warnings: list[DraftWarning],
        ) -> tuple[ImportDraft, list[DraftWarning]]:
            if review_status not in ("pending", "accepted", "ignored", "uncertain"):
                raise AdventureImportValidationError(
                    f"Invalid review_status: {review_status}"
                )
            for idx, entry in enumerate(draft.entries):
                if entry.entry_id == entry_id:
                    new_entries = list(draft.entries)
                    new_entries[idx] = entry.model_copy(
                        update={"review_status": review_status}
                    )
                    return draft.model_copy(update={"entries": new_entries}), warnings
            raise AdventureImportNotFoundError(
                import_id=import_id,
                message=f"Entry '{entry_id}' not found in draft of import {import_id}",
            )

        return self._apply_draft_mutation(
            context,
            room_id,
            import_id,
            "set entry review",
            expected_revision,
            _mutate,
        )

    def resolve_import_warning(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
        *,
        warning_id: str,
        resolution: str | None = None,
        expected_revision: int,
    ) -> AdventureImportDraft:
        def _mutate(
            draft: ImportDraft,
            warnings: list[DraftWarning],
        ) -> tuple[ImportDraft, list[DraftWarning]]:
            for idx, w in enumerate(warnings):
                if w.warning_id == warning_id:
                    if w.resolved:
                        raise AdventureImportValidationError(
                            f"Warning '{warning_id}' is already resolved"
                        )
                    new_warnings = list(warnings)
                    new_warnings[idx] = w.model_copy(
                        update={"resolved": True, "resolution": resolution}
                    )
                    return draft, new_warnings
            raise AdventureImportNotFoundError(
                import_id=import_id,
                message=f"Warning '{warning_id}' not found in draft of import {import_id}",
            )

        return self._apply_draft_mutation(
            context,
            room_id,
            import_id,
            "resolve import warning",
            expected_revision,
            _mutate,
        )

    def answer_import_question(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
        *,
        question_id: str,
        answer: str,
        expected_revision: int,
    ) -> AdventureImportDraft:
        def _mutate(
            draft: ImportDraft,
            warnings: list[DraftWarning],
        ) -> tuple[ImportDraft, list[DraftWarning]]:
            for idx, q in enumerate(draft.questions):
                if q.question_id == question_id:
                    new_questions = list(draft.questions)
                    new_questions[idx] = q.model_copy(update={"answer": answer})
                    return draft.model_copy(update={"questions": new_questions}), warnings
            raise AdventureImportNotFoundError(
                import_id=import_id,
                message=f"Question '{question_id}' not found in draft of import {import_id}",
            )

        return self._apply_draft_mutation(
            context,
            room_id,
            import_id,
            "answer import question",
            expected_revision,
            _mutate,
        )

    def finalize_adventure(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        import_id: UUID,
        *,
        name: str,
        summary: str | None = None,
        expected_revision: int,
    ) -> AdventureDefinition:
        require_import_author(context, room_id)
        with self.repository.engine.begin() as connection:
            stored_import = self._import_in_room(connection, room_id, import_id)
            # target_adventure_id is the idempotency key: retries return the same Adventure.
            if stored_import.target_adventure_id is not None:
                return self.adventure_service.get_definition(
                    context, room_id, stored_import.target_adventure_id
                )
            if stored_import.status == "cancelled":
                raise AdventureImportValidationError(
                    "Cannot finalize import with status 'cancelled'"
                )

            current_draft, current_warnings = self._load_draft_state(
                connection, import_id, expected_revision
            )
            blocking = unresolved_blocking_warnings(current_warnings)
            if blocking:
                raise AdventureImportBlockingWarningsError(
                    import_id=import_id,
                    unresolved_warning_ids=[w.warning_id for w in blocking],
                )

            definition = self.adventure_service.create_definition(
                context,
                room_id,
                AdventureDefinitionCreate(name=name, summary=summary),
                connection=connection,
            )

            included = [e for e in current_draft.entries if e.review_status != "ignored"]
            entries_by_id = {e.entry_id: e for e in current_draft.entries}
            children: dict[str | None, list[DraftEntry]] = {}
            for entry in included:
                parent_key = _nearest_included_parent_id(entry, entries_by_id)
                children.setdefault(parent_key, []).append(entry)

            # Parents are created before children; sort_order keeps the draft list order.
            sort_orders = {e.entry_id: index for index, e in enumerate(included)}
            created_ids: dict[str | None, UUID | None] = {None: None}
            ready: list[str | None] = [None]
            while ready:
                parent_key = ready.pop(0)
                for entry in children.get(parent_key, []):
                    created_entry = self.adventure_service.create_entry(
                        context,
                        room_id,
                        definition.id,
                        AdventureEntryCreate(
                            kind=entry.entry_kind,
                            title=entry.title,
                            body=entry.body,
                            data=dump_entry_payload(entry.payload),
                            visibility=entry.visibility,
                            parent_entry_id=created_ids[parent_key],
                            sort_order=sort_orders[entry.entry_id],
                        ),
                        connection=connection,
                    )
                    created_ids[entry.entry_id] = created_entry.id
                    ready.append(entry.entry_id)
                    # source_ref stays draft-only audit data; only asset_ids become links.
                    for asset_id in entry.asset_ids:
                        self.adventure_service.link_entry_asset(
                            context,
                            room_id,
                            definition.id,
                            created_entry.id,
                            AdventureEntryAssetLink(asset_id=asset_id, role="attachment"),
                            connection=connection,
                        )
            if len(created_ids) - 1 < len(included):
                raise AdventureImportValidationError("Draft entry parents form a cycle")

            finalized_definition = self.adventure_service.finalize(
                context, room_id, definition.id, connection=connection
            )
            # Revision compare-and-set: a concurrent finalize fails here and rolls back whole.
            self.repository.update_import_status_in_transaction(
                connection,
                import_id,
                "finalized",
                expected_revision=stored_import.revision,
                target_adventure_id=definition.id,
            )
            return finalized_definition


def _nearest_included_parent_id(
    entry: DraftEntry,
    entries_by_id: dict[str, DraftEntry],
) -> str | None:
    parent_id = entry.parent_entry_id
    seen: set[str] = set()
    while parent_id is not None and parent_id not in seen:
        parent = entries_by_id[parent_id]
        if parent.review_status != "ignored":
            return parent_id
        seen.add(parent_id)
        parent_id = parent.parent_entry_id
    return None


__all__ = [
    "AdventureImportService",
    "normalize_source_text",
    "require_import_author",
]
