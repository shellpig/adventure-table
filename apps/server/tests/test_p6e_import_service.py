from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import socket
from typing import Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.engine import Engine

from app.config import Settings
from app.domain.adventure_imports.errors import (
    AdventureImportForbiddenError,
    AdventureImportNotFoundError,
    AdventureImportRevisionConflictError,
    AdventureImportValidationError,
)
from app.domain.adventure_imports.schemas import (
    DraftEntry,
    DraftQuestion,
    DraftSourceRef,
    DraftWarning,
    ImportDraft,
)
from app.domain.adventure_imports.service import (
    AdventureImportService,
)
from app.domain.adventures.payloads import ScenePayload
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.adventure_imports.repository import AdventureImportRepository
from app.persistence.adventure_imports.tables import (
    adventure_import_drafts,
    adventure_import_sources,
    adventure_imports,
)
from app.domain.adventures.service import AdventureService
from app.domain.rooms.table_events import TableEventService
from app.persistence.adventures.repository import AdventureRepository
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    adventure_entry_assets,
)
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.room_assets.tables import room_assets
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import campaigns, rooms

TABLES_TO_CREATE = [
    rooms,
    campaigns,
    adventure_definitions,
    adventure_entries,
    adventure_entry_assets,
    room_assets,
    adventure_imports,
    adventure_import_sources,
    adventure_import_drafts,
]


@dataclass(frozen=True)
class ImportServiceFixture:
    engine: Engine
    repo: AdventureImportRepository
    service: AdventureImportService
    settings: Settings
    asset_service: RoomAssetService
    adventure_service: AdventureService
    db_path: Path
    room_a_id: UUID
    room_b_id: UUID
    owner_a: RoomAccessContext
    dm_a: RoomAccessContext
    member_a: RoomAccessContext
    owner_b: RoomAccessContext


def _create_sqlite_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _enable_fks(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    for table in TABLES_TO_CREATE:
        table.create(engine, checkfirst=True)
    return engine


@pytest.fixture
def fixture(tmp_path: Path) -> ImportServiceFixture:
    db_path = tmp_path / "test_import_service.db"
    engine = _create_sqlite_engine(db_path)
    now = datetime.now(timezone.utc)
    room_a_id = uuid4()
    room_b_id = uuid4()

    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                [
                    {
                        "id": room_a_id,
                        "code": "ROOM-A",
                        "name": "Room A",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner",
                        "dm_key_hash": b"dm",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": room_b_id,
                        "code": "ROOM-B",
                        "name": "Room B",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner",
                        "dm_key_hash": b"dm",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )

    repo = AdventureImportRepository(engine)
    settings = Settings()
    asset_storage = FilesystemAssetStorage(tmp_path / "assets")
    asset_repo = RoomAssetRepository(engine)
    asset_service = RoomAssetService(
        asset_repo,
        asset_storage,
        max_image_bytes=settings.asset_max_image_bytes,
        max_source_document_bytes=settings.asset_max_source_document_bytes,
    )
    adventure_repo = AdventureRepository(engine)
    adventure_service = AdventureService(adventure_repo, asset_repo)
    service = AdventureImportService(
        repo,
        settings,
        asset_service,
        adventure_service,
        TableEventService(TableEventRepository(engine)),
    )

    return ImportServiceFixture(
        engine=engine,
        repo=repo,
        service=service,
        settings=settings,
        asset_service=asset_service,
        adventure_service=adventure_service,
        db_path=db_path,
        room_a_id=room_a_id,
        room_b_id=room_b_id,
        owner_a=RoomAccessContext(
            room_id=room_a_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner A",
        ),
        dm_a=RoomAccessContext(
            room_id=room_a_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.DM,
            display_name="DM A",
        ),
        member_a=RoomAccessContext(
            room_id=room_a_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.MEMBER,
            display_name="Member A",
        ),
        owner_b=RoomAccessContext(
            room_id=room_b_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner B",
        ),
    )


def _count_rows(engine: Engine) -> tuple[int, int, int]:
    with engine.connect() as conn:
        c1 = conn.execute(
            select(func.count()).select_from(adventure_imports)
        ).scalar_one()
        c2 = conn.execute(
            select(func.count()).select_from(adventure_import_sources)
        ).scalar_one()
        c3 = conn.execute(
            select(func.count()).select_from(adventure_import_drafts)
        ).scalar_one()
        return (c1, c2, c3)


# --- 1. Authority Matrix ---

AUTHORITY_METHODS: list[
    tuple[
        str,
        Callable[
            [AdventureImportService, RoomAccessContext, UUID, UUID, UUID],
            object,
        ],
    ]
] = [
    (
        "create_import",
        lambda s, ctx, r_id, _imp, _src: s.create_import(ctx, r_id, "New Import"),
    ),
    (
        "list_imports",
        lambda s, ctx, r_id, _imp, _src: s.list_imports(ctx, r_id),
    ),
    (
        "get_import",
        lambda s, ctx, r_id, imp_id, _src: s.get_import(ctx, r_id, imp_id),
    ),
    (
        "cancel_import",
        lambda s, ctx, r_id, imp_id, _src: s.cancel_import(ctx, r_id, imp_id, 0),
    ),
    (
        "add_text_source",
        lambda s, ctx, r_id, imp_id, _src: s.add_text_source(
            ctx, r_id, imp_id, source_kind="paste", text="text content"
        ),
    ),
    (
        "add_url_source",
        lambda s, ctx, r_id, imp_id, _src: s.add_url_source(
            ctx, r_id, imp_id, url="https://example.com"
        ),
    ),
    (
        "list_sources",
        lambda s, ctx, r_id, imp_id, _src: s.list_sources(ctx, r_id, imp_id),
    ),
    (
        "read_source_chunk",
        lambda s, ctx, r_id, imp_id, src_id: s.read_source_chunk(
            ctx, r_id, imp_id, src_id
        ),
    ),
    (
        "get_draft",
        lambda s, ctx, r_id, imp_id, _src: s.get_draft(ctx, r_id, imp_id),
    ),
    (
        "update_draft",
        lambda s, ctx, r_id, imp_id, _src: s.update_draft(
            ctx,
            r_id,
            imp_id,
            draft=ImportDraft(),
            warnings=[],
            expected_revision=0,
        ),
    ),
    (
        "add_asset_source",
        lambda s, ctx, r_id, imp_id, _src: s.add_asset_source(
            ctx, r_id, imp_id, asset_id=uuid4()
        ),
    ),
]


@pytest.mark.parametrize("method_name,method_call", AUTHORITY_METHODS)
@pytest.mark.parametrize(
    "actor_kind,expected_exc",
    [
        ("member_a", AdventureImportForbiddenError),
        ("owner_b", AdventureImportNotFoundError),
    ],
)
def test_authority_matrix(
    fixture: ImportServiceFixture,
    method_name: str,
    method_call: Callable[
        [AdventureImportService, RoomAccessContext, UUID, UUID, UUID],
        object,
    ],
    actor_kind: str,
    expected_exc: type[Exception],
) -> None:
    imp = fixture.service.create_import(fixture.owner_a, fixture.room_a_id, "Seed Import")
    src = fixture.service.add_text_source(
        fixture.owner_a,
        fixture.room_a_id,
        imp.id,
        source_kind="paste",
        text="Sample text",
    )
    before_counts = _count_rows(fixture.engine)

    ctx = getattr(fixture, actor_kind)
    with pytest.raises(expected_exc):
        method_call(fixture.service, ctx, fixture.room_a_id, imp.id, src.id)

    after_counts = _count_rows(fixture.engine)
    assert before_counts == after_counts


# --- 2. Text kinds ---


@pytest.mark.parametrize("source_kind", ["paste", "txt", "markdown"])
@pytest.mark.parametrize(
    "input_mode,text_in,bytes_in,expected_normalized",
    [
        (
            "str_crlf",
            "  line 1  \r\n\r\n\r\n\r\nline 2  \r\n\r\n",
            None,
            "  line 1\n\n\nline 2\n",
        ),
        (
            "bytes_bom",
            None,
            b"\xef\xbb\xbf  line 1  \r\n\r\n\r\n\r\nline 2  \r\n\r\n",
            "  line 1\n\n\nline 2\n",
        ),
    ],
)
def test_text_source_kinds(
    fixture: ImportServiceFixture,
    source_kind: Literal["paste", "txt", "markdown"],
    input_mode: str,
    text_in: str | None,
    bytes_in: bytes | None,
    expected_normalized: str,
) -> None:
    imp = fixture.service.create_import(fixture.owner_a, fixture.room_a_id, "Text Import")
    expected_hash = hashlib.sha256(expected_normalized.encode("utf-8")).hexdigest()

    src = fixture.service.add_text_source(
        fixture.owner_a,
        fixture.room_a_id,
        imp.id,
        source_kind=source_kind,
        text=text_in,
        content=bytes_in,
        filename="notes.txt",
        media_type="text/plain",
    )

    assert src.source_kind == source_kind
    assert src.sha256 == expected_hash
    assert src.metadata_json["filename"] == "notes.txt"
    assert src.metadata_json["media_type"] == "text/plain"
    assert src.metadata_json["line_count"] == len(expected_normalized.splitlines())
    assert src.metadata_json["char_count"] == len(expected_normalized)

    # list_sources omits text and provides text_length
    sources = fixture.service.list_sources(fixture.owner_a, fixture.room_a_id, imp.id)
    assert len(sources) == 1
    assert sources[0].text_length == len(expected_normalized)
    assert not hasattr(sources[0], "normalized_text")

    # Idempotent re-add
    counts_before = _count_rows(fixture.engine)
    src_again = fixture.service.add_text_source(
        fixture.owner_a,
        fixture.room_a_id,
        imp.id,
        source_kind=source_kind,
        text=text_in,
        content=bytes_in,
    )
    counts_after = _count_rows(fixture.engine)
    assert src_again.id == src.id
    assert counts_before == counts_after


def test_text_source_oversize_and_undecodable(fixture: ImportServiceFixture) -> None:
    imp = fixture.service.create_import(fixture.owner_a, fixture.room_a_id, "Limit Import")
    custom_settings = Settings(import_source_max_bytes=50)
    service_small = AdventureImportService(
        fixture.repo,
        custom_settings,
        fixture.asset_service,
        fixture.adventure_service,
        TableEventService(TableEventRepository(fixture.engine)),
    )

    before_counts = _count_rows(fixture.engine)
    with pytest.raises(AdventureImportValidationError):
        service_small.add_text_source(
            fixture.owner_a,
            fixture.room_a_id,
            imp.id,
            source_kind="txt",
            content=b"x" * 51,
        )
    assert _count_rows(fixture.engine) == before_counts

    with pytest.raises(AdventureImportValidationError):
        fixture.service.add_text_source(
            fixture.owner_a,
            fixture.room_a_id,
            imp.id,
            source_kind="txt",
            content=b"\xff\xfe\x00\x00",
        )
    assert _count_rows(fixture.engine) == before_counts


# --- 3. URL sources ---


@pytest.mark.parametrize("invalid_url", ["ftp://example.com", "javascript:alert(1)", "http://", "not-a-url"])
def test_url_source_invalid_scheme(fixture: ImportServiceFixture, invalid_url: str) -> None:
    imp = fixture.service.create_import(fixture.owner_a, fixture.room_a_id, "URL Import")
    with pytest.raises(AdventureImportValidationError):
        fixture.service.add_url_source(
            fixture.owner_a,
            fixture.room_a_id,
            imp.id,
            url=invalid_url,
        )


def test_url_source_with_text_and_without_text(
    fixture: ImportServiceFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Prove no network call is ever made
    def _fail_socket(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Network attempted")

    monkeypatch.setattr(socket, "socket", _fail_socket)
    monkeypatch.setattr(socket, "create_connection", _fail_socket)

    imp = fixture.service.create_import(fixture.owner_a, fixture.room_a_id, "URL Test")

    # URL with text behaves like B
    src_with_text = fixture.service.add_url_source(
        fixture.owner_a,
        fixture.room_a_id,
        imp.id,
        url="https://example.com/adventure",
        text="Chapter 1\r\n\r\nDetails\n",
        title="Chapter 1",
        excerpt="An excerpt",
    )
    assert src_with_text.source_kind == "url"
    assert src_with_text.source_url == "https://example.com/adventure"
    assert src_with_text.metadata_json["content_provided"] is True
    assert src_with_text.metadata_json["title"] == "Chapter 1"

    # URL without text
    src_no_text = fixture.service.add_url_source(
        fixture.owner_a,
        fixture.room_a_id,
        imp.id,
        url="https://example.com/empty-page",
        title="Empty Page",
    )
    assert src_no_text.source_kind == "url"
    assert src_no_text.sha256 == hashlib.sha256(b"url:https://example.com/empty-page").hexdigest()
    assert src_no_text.metadata_json["content_provided"] is False

    # Check draft warning was appended and import status stays "source"
    imp_check = fixture.service.get_import(fixture.owner_a, fixture.room_a_id, imp.id)
    assert imp_check.status == "source"

    draft = fixture.service.get_draft(fixture.owner_a, fixture.room_a_id, imp.id)
    assert draft.revision == 1
    assert len(draft.warnings) == 1
    w = draft.warnings[0]
    assert w.warning_id == f"source:{src_no_text.id}:no_content"
    assert w.level == "warning"
    assert w.code == "url_source_without_content"
    assert w.source_id == src_no_text.id

    # Second identical URL-only add is idempotent
    counts_before = _count_rows(fixture.engine)
    src_second = fixture.service.add_url_source(
        fixture.owner_a,
        fixture.room_a_id,
        imp.id,
        url="https://example.com/empty-page",
    )
    counts_after = _count_rows(fixture.engine)
    assert src_second.id == src_no_text.id
    assert counts_before == counts_after


# --- 4. Chunk reading ---


def test_chunk_reading_boundary_and_validation(fixture: ImportServiceFixture) -> None:
    imp = fixture.service.create_import(fixture.owner_a, fixture.room_a_id, "Chunk Import")
    sample_text = "0123456789ABCDEFGHIJ"  # len 20 -> normalized: 20 chars + \n = 21 chars
    src = fixture.service.add_text_source(
        fixture.owner_a,
        fixture.room_a_id,
        imp.id,
        source_kind="txt",
        text=sample_text,
    )
    total_len = src.text_length
    assert total_len == 21

    # Chunk 1: offset 0, limit 10
    c1 = fixture.service.read_source_chunk(
        fixture.owner_a, fixture.room_a_id, imp.id, src.id, offset=0, limit=10
    )
    assert c1.offset == 0
    assert c1.text == "0123456789"
    assert c1.total_length == total_len
    assert c1.next_offset == 10

    # Chunk 2: offset 10, limit 10
    c2 = fixture.service.read_source_chunk(
        fixture.owner_a, fixture.room_a_id, imp.id, src.id, offset=10, limit=10
    )
    assert c2.offset == 10
    assert c2.text == "ABCDEFGHIJ"
    assert c2.next_offset == 20

    # Chunk 3: offset 20, limit 10 -> reaches end
    c3 = fixture.service.read_source_chunk(
        fixture.owner_a, fixture.room_a_id, imp.id, src.id, offset=20, limit=10
    )
    assert c3.offset == 20
    assert c3.text == "\n"
    assert c3.next_offset is None

    # Default limit uses settings.import_chunk_max_chars
    c_default = fixture.service.read_source_chunk(
        fixture.owner_a, fixture.room_a_id, imp.id, src.id, offset=0, limit=None
    )
    assert c_default.text == "0123456789ABCDEFGHIJ\n"
    assert c_default.next_offset is None

    # Validation errors
    with pytest.raises(AdventureImportValidationError):
        fixture.service.read_source_chunk(
            fixture.owner_a, fixture.room_a_id, imp.id, src.id, offset=-1
        )
    with pytest.raises(AdventureImportValidationError):
        fixture.service.read_source_chunk(
            fixture.owner_a, fixture.room_a_id, imp.id, src.id, offset=total_len + 1
        )
    with pytest.raises(AdventureImportValidationError):
        fixture.service.read_source_chunk(
            fixture.owner_a, fixture.room_a_id, imp.id, src.id, limit=0
        )
    with pytest.raises(AdventureImportValidationError):
        fixture.service.read_source_chunk(
            fixture.owner_a,
            fixture.room_a_id,
            imp.id,
            src.id,
            limit=fixture.settings.import_chunk_max_chars + 1,
        )


# --- 5. Draft ---


def test_draft_lifecycle_revisions_and_restart_stability(
    fixture: ImportServiceFixture,
) -> None:
    imp = fixture.service.create_import(fixture.owner_a, fixture.room_a_id, "Draft Import")
    src = fixture.service.add_text_source(
        fixture.owner_a,
        fixture.room_a_id,
        imp.id,
        source_kind="paste",
        text="Source text",
    )

    # get_draft before any write returns revision 0 and writes nothing
    draft_0 = fixture.service.get_draft(fixture.owner_a, fixture.room_a_id, imp.id)
    assert draft_0.revision == 0
    assert draft_0.warnings == []
    assert draft_0.draft.entries == []
    with fixture.engine.connect() as conn:
        draft_count = conn.execute(
            select(func.count()).select_from(adventure_import_drafts)
        ).scalar_one()
        assert draft_count == 0

    # update_draft at expected_revision 0 -> revision 1 and status "drafting"
    entry = DraftEntry(
        entry_id="scene-1",
        entry_kind="scene",
        payload=ScenePayload(read_aloud="The Tavern"),
        provenance="source_document",
        source_ref=DraftSourceRef(source_id=src.id, locator="p.1"),
    )
    warning = DraftWarning(
        warning_id="w-1",
        level="info",
        code="note",
        message="A note",
        source_id=src.id,
    )
    question = DraftQuestion(
        question_id="q-1",
        message="What is the tavern name?",
        entry_id="scene-1",
    )
    draft_payload = ImportDraft(entries=[entry], questions=[question])

    draft_1 = fixture.service.update_draft(
        fixture.owner_a,
        fixture.room_a_id,
        imp.id,
        draft=draft_payload,
        warnings=[warning],
        expected_revision=0,
    )
    assert draft_1.revision == 1
    assert len(draft_1.draft.entries) == 1
    imp_1 = fixture.service.get_import(fixture.owner_a, fixture.room_a_id, imp.id)
    assert imp_1.status == "drafting"

    # Revision increment: update at expected 1 -> revision 2
    draft_2 = fixture.service.update_draft(
        fixture.owner_a,
        fixture.room_a_id,
        imp.id,
        draft=draft_payload,
        warnings=[warning],
        expected_revision=1,
    )
    assert draft_2.revision == 2

    # Stale expected revision rejected with draft/warnings/revision/status unchanged
    with pytest.raises(AdventureImportRevisionConflictError):
        fixture.service.update_draft(
            fixture.owner_a,
            fixture.room_a_id,
            imp.id,
            draft=draft_payload,
            warnings=[warning],
            expected_revision=0,
        )
    draft_check = fixture.service.get_draft(fixture.owner_a, fixture.room_a_id, imp.id)
    assert draft_check.revision == 2

    # Dangling source_ref / warning source_id rejected
    dangling_id = uuid4()
    bad_entry = DraftEntry(
        entry_id="scene-bad",
        entry_kind="scene",
        payload=ScenePayload(read_aloud="Bad"),
        source_ref=DraftSourceRef(source_id=dangling_id),
    )
    with pytest.raises(AdventureImportValidationError):
        fixture.service.update_draft(
            fixture.owner_a,
            fixture.room_a_id,
            imp.id,
            draft=ImportDraft(entries=[bad_entry]),
            warnings=[],
            expected_revision=2,
        )

    bad_warning = DraftWarning(
        warning_id="w-bad",
        level="warning",
        code="bad",
        message="bad",
        source_id=dangling_id,
    )
    with pytest.raises(AdventureImportValidationError):
        fixture.service.update_draft(
            fixture.owner_a,
            fixture.room_a_id,
            imp.id,
            draft=draft_payload,
            warnings=[bad_warning],
            expected_revision=2,
        )

    # E.4: Restart stability — fresh repository and service on the same SQLite file
    fresh_engine = _create_sqlite_engine(fixture.db_path)
    fresh_repo = AdventureImportRepository(fresh_engine)
    fresh_asset_repo = RoomAssetRepository(fresh_engine)
    fresh_asset_service = RoomAssetService(
        fresh_asset_repo,
        FilesystemAssetStorage(fixture.db_path.parent / "assets"),
        max_image_bytes=fixture.settings.asset_max_image_bytes,
        max_source_document_bytes=fixture.settings.asset_max_source_document_bytes,
    )
    fresh_adventure_service = AdventureService(
        AdventureRepository(fresh_engine),
        fresh_asset_repo,
    )
    fresh_service = AdventureImportService(
        fresh_repo,
        fixture.settings,
        fresh_asset_service,
        fresh_adventure_service,
        TableEventService(TableEventRepository(fresh_engine)),
    )

    reopened_draft = fresh_service.get_draft(fixture.owner_a, fixture.room_a_id, imp.id)
    assert reopened_draft.revision == 2
    assert reopened_draft.draft.entries[0].entry_id == "scene-1"
    assert reopened_draft.draft.questions[0].question_id == "q-1"
    assert reopened_draft.warnings[0].warning_id == "w-1"


# --- 6. Cancel import and post-cancel rejections ---


def test_cancel_import_and_post_cancel_rejections(fixture: ImportServiceFixture) -> None:
    imp = fixture.service.create_import(fixture.owner_a, fixture.room_a_id, "Cancel Import")

    # Stale cancel on active import raises revision conflict
    with pytest.raises(AdventureImportRevisionConflictError):
        fixture.service.cancel_import(
            fixture.owner_a, fixture.room_a_id, imp.id, expected_revision=5
        )

    # Cancel import succeeds
    cancelled = fixture.service.cancel_import(
        fixture.owner_a, fixture.room_a_id, imp.id, expected_revision=0
    )
    assert cancelled.status == "cancelled"
    assert cancelled.revision == 1

    # Cancelling already-cancelled import raises validation error
    with pytest.raises(AdventureImportValidationError):
        fixture.service.cancel_import(
            fixture.owner_a, fixture.room_a_id, imp.id, expected_revision=1
        )

    # Post-cancel add_text_source rejected
    with pytest.raises(AdventureImportValidationError):
        fixture.service.add_text_source(
            fixture.owner_a,
            fixture.room_a_id,
            imp.id,
            source_kind="paste",
            text="hello",
        )

    # Post-cancel add_url_source rejected
    with pytest.raises(AdventureImportValidationError):
        fixture.service.add_url_source(
            fixture.owner_a,
            fixture.room_a_id,
            imp.id,
            url="https://example.com",
        )

    # Post-cancel update_draft rejected
    with pytest.raises(AdventureImportValidationError):
        fixture.service.update_draft(
            fixture.owner_a,
            fixture.room_a_id,
            imp.id,
            draft=ImportDraft(),
            warnings=[],
            expected_revision=0,
        )
