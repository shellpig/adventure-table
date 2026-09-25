from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import socket
from typing import Generator
import urllib.request
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_database_engine
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import (
    get_adventure_import_service,
    get_room_asset_service,
)
from app.config import settings
from app.db import metadata
from app.domain.adventure_imports.service import AdventureImportService
from app.domain.adventures.service import AdventureService
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.main import app
from app.persistence.adventure_imports.repository import AdventureImportRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.adventures.repository import AdventureRepository
from app.persistence.adventure_imports.tables import (
    adventure_import_drafts,
    adventure_import_sources,
    adventure_imports,
)
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    adventure_entry_assets,
)
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.room_assets.tables import room_assets
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


def _make_pdf(text: str) -> bytes:
    stream_data = f"BT /F1 12 Tf 100 700 Td ({text}) Tj ET".encode("ascii")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream_data)} >>\nstream\n".encode("ascii") + stream_data + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = [b"%PDF-1.4\n"]
    offsets = [0]
    for i, obj in enumerate(objs, 1):
        offsets.append(sum(len(x) for x in out))
        out.append(f"{i} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref_offset = sum(len(x) for x in out)
    out.append(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets[1:]:
        out.append(f"{off:010d} 00000 n \n".encode("ascii"))
    out.append(
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return b"".join(out)


@dataclass(frozen=True)
class ImportApiFixture:
    client: TestClient
    engine: Engine
    room_a_id: UUID
    room_b_id: UUID
    token_owner_a: str
    token_dm_a: str
    token_member_a: str
    token_owner_b: str
    tmp_path: Path
    room_asset_service: RoomAssetService
    import_service: AdventureImportService


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def api_fixture(tmp_path: Path) -> Generator[ImportApiFixture, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fks(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    for table in TABLES_TO_CREATE:
        table.create(engine, checkfirst=True)

    storage = FilesystemAssetStorage(tmp_path)
    asset_repo = RoomAssetRepository(engine)
    room_asset_service = RoomAssetService(
        asset_repo,
        storage,
        max_image_bytes=settings.asset_max_image_bytes,
        max_source_document_bytes=settings.asset_max_source_document_bytes,
    )
    import_repo = AdventureImportRepository(engine)
    adventure_repo = AdventureRepository(engine)
    adventure_service = AdventureService(adventure_repo, asset_repo)
    import_service = AdventureImportService(
        import_repo,
        settings,
        room_asset_service,
        adventure_service,
        TableEventService(TableEventRepository(engine)),
    )

    room_a_id = uuid4()
    room_b_id = uuid4()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                [
                    {
                        "id": room_a_id,
                        "code": "ROOMA",
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
                        "code": "ROOMB",
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

    token_owner_a = "token-owner-a"
    token_dm_a = "token-dm-a"
    token_member_a = "token-member-a"
    token_owner_b = "token-owner-b"

    token_to_context = {
        token_owner_a: RoomAccessContext(
            room_id=room_a_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner A",
        ),
        token_dm_a: RoomAccessContext(
            room_id=room_a_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.DM,
            display_name="DM A",
        ),
        token_member_a: RoomAccessContext(
            room_id=room_a_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.MEMBER,
            display_name="Member A",
        ),
        token_owner_b: RoomAccessContext(
            room_id=room_b_id,
            access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER,
            display_name="Owner B",
        ),
    }

    def _override_access_context(request: Request) -> RoomAccessContext:
        auth_header = request.headers.get("authorization", "")
        scheme, _, token = auth_header.partition(" ")
        token_clean = token.strip()
        if token_clean in token_to_context:
            return token_to_context[token_clean]
        raise APIError(401, "room_access_required", "Room access token is required")

    app.state.room_asset_service = room_asset_service
    app.state.adventure_service = adventure_service
    app.state.adventure_import_service = import_service
    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_room_access_context] = _override_access_context

    client = TestClient(app)
    try:
        yield ImportApiFixture(
            client=client,
            engine=engine,
            room_a_id=room_a_id,
            room_b_id=room_b_id,
            token_owner_a=token_owner_a,
            token_dm_a=token_dm_a,
            token_member_a=token_member_a,
            token_owner_b=token_owner_b,
            tmp_path=tmp_path,
            room_asset_service=room_asset_service,
            import_service=import_service,
        )
    finally:
        try:
            del app.state.room_asset_service
        except (AttributeError, KeyError):
            pass
        try:
            del app.state.adventure_import_service
        except (AttributeError, KeyError):
            pass
        app.dependency_overrides.pop(get_database_engine, None)
        app.dependency_overrides.pop(get_room_access_context, None)


def test_all_routes_happy_path_owner_and_dm(api_fixture: ImportApiFixture) -> None:
    client = api_fixture.client
    room_id = api_fixture.room_a_id
    owner_token = api_fixture.token_owner_a
    dm_token = api_fixture.token_dm_a

    # 1. Owner creates import
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports",
        json={"name": "Lost Mine of Phandelver"},
        headers=_auth(owner_token),
    )
    assert resp.status_code == 201
    import_data = resp.json()
    assert import_data["name"] == "Lost Mine of Phandelver"
    assert import_data["status"] == "source"
    assert import_data["revision"] == 0
    import_id = import_data["id"]

    # 2. Owner lists imports
    resp = client.get(
        f"/api/rooms/{room_id}/adventure-imports",
        headers=_auth(owner_token),
    )
    assert resp.status_code == 200
    imports_list = resp.json()
    assert len(imports_list) == 1
    assert imports_list[0]["id"] == import_id

    # 3. DM gets import
    resp = client.get(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}",
        headers=_auth(dm_token),
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == import_id

    # 4. DM adds paste source via JSON
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        json={"source_kind": "paste", "text": "Goblin Ambush: Two dead horses block the path."},
        headers=_auth(dm_token),
    )
    assert resp.status_code == 200
    paste_src = resp.json()
    assert paste_src["source_kind"] == "paste"
    assert paste_src["text_length"] > 0
    paste_src_id = paste_src["id"]

    # 5. Owner adds raw txt source via raw upload
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        params={"source_kind": "txt", "filename": "cragmaw_hideout.txt"},
        content=b"Cragmaw Hideout: The cave mouth opens into darkness.",
        headers={**_auth(owner_token), "Content-Type": "text/plain"},
    )
    assert resp.status_code == 200
    txt_src = resp.json()
    assert txt_src["source_kind"] == "txt"
    assert txt_src["asset_id"] is not None

    # 6. Owner adds raw PDF source via raw upload
    pdf_bytes = _make_pdf("Redbrand Hideout beneath Tresendar Manor.")
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        params={"source_kind": "pdf", "filename": "redbrand.pdf"},
        content=pdf_bytes,
        headers={**_auth(owner_token), "Content-Type": "application/pdf"},
    )
    assert resp.status_code == 200
    pdf_src = resp.json()
    assert pdf_src["source_kind"] == "pdf"
    assert pdf_src["asset_id"] is not None

    # 7. DM creates room asset first, then calls add_source_from_asset
    asset_resp = client.post(
        f"/api/rooms/{room_id}/assets",
        params={"kind": "source_document", "filename": "wave_echo.md", "visibility": "dm_only"},
        content=b"Wave Echo Cave: The Forge of Spells lies within.",
        headers={**_auth(dm_token), "Content-Type": "text/markdown"},
    )
    assert asset_resp.status_code == 201
    existing_asset_id = asset_resp.json()["id"]

    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources/from-asset",
        json={"asset_id": existing_asset_id},
        headers=_auth(dm_token),
    )
    assert resp.status_code == 200
    from_asset_src = resp.json()
    assert from_asset_src["source_kind"] == "markdown"
    assert from_asset_src["asset_id"] == existing_asset_id

    # 8. DM lists sources
    resp = client.get(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        headers=_auth(dm_token),
    )
    assert resp.status_code == 200
    sources = resp.json()
    assert len(sources) == 4
    source_ids = {s["id"] for s in sources}
    assert paste_src_id in source_ids
    for s in sources:
        assert "normalized_text" not in s

    # 9. DM reads source chunk
    resp = client.get(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources/{paste_src_id}/chunk",
        params={"offset": 0, "limit": 20},
        headers=_auth(dm_token),
    )
    assert resp.status_code == 200
    chunk = resp.json()
    assert chunk["source_id"] == paste_src_id
    assert chunk["offset"] == 0
    assert len(chunk["text"]) == 20
    assert chunk["next_offset"] == 20

    # 10. DM updates draft (with valid source_ref)
    resp = client.put(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/draft",
        json={
            "draft": {
                "schema_version": 1,
                "entries": [
                    {
                        "entry_id": "scene_1",
                        "entry_kind": "scene",
                        "payload": {"kind": "scene", "dm_summary": "Ambush site"},
                        "provenance": "source_document",
                        "source_ref": {"source_id": paste_src_id, "locator": "line:1"},
                    }
                ],
                "questions": [],
            },
            "warnings": [],
            "expected_revision": 0,
        },
        headers=_auth(dm_token),
    )
    assert resp.status_code == 200
    draft_data = resp.json()
    assert draft_data["revision"] == 1
    assert len(draft_data["draft"]["entries"]) == 1

    # Verify import status transitioned to drafting
    get_imp_resp = client.get(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}",
        headers=_auth(dm_token),
    )
    assert get_imp_resp.json()["status"] == "drafting"

    # 11. Owner gets draft
    resp = client.get(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/draft",
        headers=_auth(owner_token),
    )
    assert resp.status_code == 200
    assert resp.json()["revision"] == 1

    # 12. Owner cancels import
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/cancel",
        json={"expected_revision": 1},
        headers=_auth(owner_token),
    )
    assert resp.status_code == 200
    cancelled_data = resp.json()
    assert cancelled_data["status"] == "cancelled"
    assert cancelled_data["revision"] == 2


@pytest.mark.parametrize(
    ("method", "path_template", "payload", "params", "content", "headers", "is_mutation"),
    [
        ("POST", "/api/rooms/{room}/adventure-imports", {"name": "Test"}, None, None, None, True),
        ("GET", "/api/rooms/{room}/adventure-imports", None, None, None, None, False),
        ("GET", "/api/rooms/{room}/adventure-imports/{import_id}", None, None, None, None, False),
        ("POST", "/api/rooms/{room}/adventure-imports/{import_id}/cancel", {"expected_revision": 0}, None, None, None, True),
        ("POST", "/api/rooms/{room}/adventure-imports/{import_id}/sources", {"source_kind": "paste", "text": "abc"}, None, None, None, True),
        ("POST", "/api/rooms/{room}/adventure-imports/{import_id}/sources", None, {"source_kind": "txt", "filename": "f.txt"}, b"content", {"Content-Type": "text/plain"}, True),
        ("GET", "/api/rooms/{room}/adventure-imports/{import_id}/sources", None, None, None, None, False),
        ("POST", "/api/rooms/{room}/adventure-imports/{import_id}/sources/from-asset", {"asset_id": "00000000-0000-0000-0000-000000000001"}, None, None, None, True),
        ("GET", "/api/rooms/{room}/adventure-imports/{import_id}/sources/{source_id}/chunk", None, {"offset": 0}, None, None, False),
        ("GET", "/api/rooms/{room}/adventure-imports/{import_id}/draft", None, None, None, None, False),
        ("PUT", "/api/rooms/{room}/adventure-imports/{import_id}/draft", {"draft": {"entries": []}, "warnings": [], "expected_revision": 0}, None, None, None, True),
    ],
    ids=[
        "create_import",
        "list_imports",
        "get_import",
        "cancel_import",
        "add_json_source",
        "add_raw_source",
        "list_sources",
        "add_source_from_asset",
        "read_source_chunk",
        "get_draft",
        "update_draft",
    ],
)
def test_authority_matrix_rejection_and_zero_side_effects(
    api_fixture: ImportApiFixture,
    method: str,
    path_template: str,
    payload: dict | None,
    params: dict | None,
    content: bytes | None,
    headers: dict | None,
    is_mutation: bool,
) -> None:
    client = api_fixture.client
    room_a = api_fixture.room_a_id
    token_member_a = api_fixture.token_member_a
    token_owner_b = api_fixture.token_owner_b
    dummy_import_id = uuid4()
    dummy_source_id = uuid4()

    path_a = path_template.format(
        room=room_a,
        import_id=dummy_import_id,
        source_id=dummy_source_id,
    )

    def _count_rows():
        with api_fixture.engine.connect() as conn:
            return (
                conn.execute(select(func.count()).select_from(adventure_imports)).scalar(),
                conn.execute(select(func.count()).select_from(adventure_import_sources)).scalar(),
                conn.execute(select(func.count()).select_from(adventure_import_drafts)).scalar(),
                conn.execute(select(func.count()).select_from(room_assets)).scalar(),
            )

    before_counts = _count_rows()

    # 1. MEMBER in Room A -> 403 adventure_import_authority_required
    req_headers_member = {**_auth(token_member_a), **(headers or {})}
    resp_member = client.request(
        method,
        path_a,
        json=payload,
        params=params,
        content=content,
        headers=req_headers_member,
    )
    assert resp_member.status_code == 403
    assert resp_member.json()["error"]["code"] == "adventure_import_authority_required"

    if is_mutation:
        assert _count_rows() == before_counts

    # 2. Owner from Room B calling Room A's path -> 404 adventure_import_not_found
    req_headers_b = {**_auth(token_owner_b), **(headers or {})}
    resp_b = client.request(
        method,
        path_a,
        json=payload,
        params=params,
        content=content,
        headers=req_headers_b,
    )
    assert resp_b.status_code == 404
    assert resp_b.json()["error"]["code"] == "adventure_import_not_found"

    if is_mutation:
        assert _count_rows() == before_counts


def test_raw_upload_mime_empty_and_size_limits_and_revision_conflicts(
    api_fixture: ImportApiFixture,
) -> None:
    client = api_fixture.client
    room_id = api_fixture.room_a_id
    token = api_fixture.token_owner_a

    # Create an import to work with
    create_resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports",
        json={"name": "Validation Test Import"},
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    import_id = create_resp.json()["id"]

    # 1. MIME mismatch: source_kind=pdf with Content-Type: text/plain
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        params={"source_kind": "pdf", "filename": "doc.pdf"},
        content=b"not a pdf",
        headers={**_auth(token), "Content-Type": "text/plain"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "asset_media_type_not_supported"

    # 2. MIME mismatch: source_kind=txt with Content-Type: application/pdf
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        params={"source_kind": "txt", "filename": "doc.txt"},
        content=b"text",
        headers={**_auth(token), "Content-Type": "application/pdf"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "asset_media_type_not_supported"

    # 3. Unsupported source_kind
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        params={"source_kind": "image", "filename": "pic.png"},
        content=b"\x89PNG\r\n\x1a\n",
        headers={**_auth(token), "Content-Type": "image/png"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "asset_media_type_not_supported"

    # 4. Empty data -> 400 asset_empty
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        params={"source_kind": "txt", "filename": "empty.txt"},
        content=b"",
        headers={**_auth(token), "Content-Type": "text/plain"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "asset_empty"

    # 5. Exceeding max source size -> 413 asset_too_large
    oversized = b"x" * (settings.asset_max_source_document_bytes + 1)
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        params={"source_kind": "txt", "filename": "huge.txt"},
        content=oversized,
        headers={**_auth(token), "Content-Type": "text/plain"},
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "asset_too_large"

    # Verify no asset was leaked in storage or DB from failed uploads
    with api_fixture.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(room_assets)).scalar() == 0

    # 6. Stale draft revision 409
    resp = client.put(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/draft",
        json={"draft": {"entries": []}, "warnings": [], "expected_revision": 999},
        headers=_auth(token),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "adventure_import_revision_conflict"

    # Draft remains at revision 0
    draft_resp = client.get(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/draft",
        headers=_auth(token),
    )
    assert draft_resp.json()["revision"] == 0

    # 7. Stale cancel revision 409
    resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/cancel",
        json={"expected_revision": 999},
        headers=_auth(token),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "adventure_import_revision_conflict"

    # Status remains source
    imp_resp = client.get(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}",
        headers=_auth(token),
    )
    assert imp_resp.json()["status"] == "source"


def test_json_url_source_boundary_no_network_fetch(
    api_fixture: ImportApiFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = api_fixture.client
    room_id = api_fixture.room_a_id
    token = api_fixture.token_owner_a

    create_resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports",
        json={"name": "URL Boundary Import"},
        headers=_auth(token),
    )
    import_id = create_resp.json()["id"]

    orig_connect = socket.socket.connect
    orig_create_conn = socket.create_connection

    def _forbidden_connect(self, address, *args, **kwargs):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "localhost", "::1"):
            return orig_connect(self, address, *args, **kwargs)
        raise RuntimeError("Network access forbidden!")

    def _forbidden_create_conn(address, *args, **kwargs):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "localhost", "::1"):
            return orig_create_conn(address, *args, **kwargs)
        raise RuntimeError("Network access forbidden!")

    def _forbidden_urlopen(*args, **kwargs):
        raise RuntimeError("Network access forbidden!")

    # Poison socket connection and urllib primitives to ensure zero backend fetch
    monkeypatch.setattr(socket.socket, "connect", _forbidden_connect)
    monkeypatch.setattr(socket, "create_connection", _forbidden_create_conn)
    monkeypatch.setattr(urllib.request, "urlopen", _forbidden_urlopen)

    # 1. URL with text succeeds
    resp1 = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        json={
            "source_kind": "url",
            "url": "https://example.com/adventure-module",
            "text": "Extracted module content from web",
            "title": "Example Module",
        },
        headers=_auth(token),
    )
    assert resp1.status_code == 200
    src1 = resp1.json()
    assert src1["source_kind"] == "url"
    assert src1["source_url"] == "https://example.com/adventure-module"
    assert src1["text_length"] > 0

    # 2. URL without text succeeds with warning in draft
    resp2 = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        json={
            "source_kind": "url",
            "url": "https://example.com/adventure-ref-only",
        },
        headers=_auth(token),
    )
    assert resp2.status_code == 200
    src2 = resp2.json()
    assert src2["source_kind"] == "url"
    assert src2["text_length"] == 0

    # Check that draft holds the expected warning
    draft_resp = client.get(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/draft",
        headers=_auth(token),
    )
    assert draft_resp.status_code == 200
    warnings = draft_resp.json()["warnings"]
    assert any(w["code"] == "url_source_without_content" for w in warnings)


def test_cross_room_ids_never_leak_and_return_404(api_fixture: ImportApiFixture) -> None:
    client = api_fixture.client
    room_a = api_fixture.room_a_id
    room_b = api_fixture.room_b_id
    token_a = api_fixture.token_owner_a
    token_b = api_fixture.token_owner_b

    # 1. Create import in Room A
    resp_a = client.post(
        f"/api/rooms/{room_a}/adventure-imports",
        json={"name": "Room A Import"},
        headers=_auth(token_a),
    )
    import_a_id = resp_a.json()["id"]

    # 2. Owner of Room B requests import A through Room B path -> 404
    resp = client.get(
        f"/api/rooms/{room_b}/adventure-imports/{import_a_id}",
        headers=_auth(token_b),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "adventure_import_not_found"

    # 3. Create asset in Room B
    asset_resp = client.post(
        f"/api/rooms/{room_b}/assets",
        params={"kind": "source_document", "filename": "b.txt", "visibility": "dm_only"},
        content=b"Asset in Room B",
        headers={**_auth(token_b), "Content-Type": "text/plain"},
    )
    asset_b_id = asset_resp.json()["id"]

    # 4. From-asset in Room A referencing asset belonging to Room B -> 404
    resp = client.post(
        f"/api/rooms/{room_a}/adventure-imports/{import_a_id}/sources/from-asset",
        json={"asset_id": asset_b_id},
        headers=_auth(token_a),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "adventure_import_not_found"

    # 5. Create source in Room B
    resp_b = client.post(
        f"/api/rooms/{room_b}/adventure-imports",
        json={"name": "Room B Import"},
        headers=_auth(token_b),
    )
    import_b_id = resp_b.json()["id"]
    src_resp = client.post(
        f"/api/rooms/{room_b}/adventure-imports/{import_b_id}/sources",
        json={"source_kind": "paste", "text": "Secret of Room B"},
        headers=_auth(token_b),
    )
    source_b_id = src_resp.json()["id"]

    # 6. Chunk read in Room A referencing source belonging to Room B -> 404
    resp = client.get(
        f"/api/rooms/{room_a}/adventure-imports/{import_a_id}/sources/{source_b_id}/chunk",
        headers=_auth(token_a),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "adventure_import_not_found"


def test_json_source_validation_422_with_zero_side_effects(
    api_fixture: ImportApiFixture,
) -> None:
    client = api_fixture.client
    room_id = api_fixture.room_a_id
    token = api_fixture.token_owner_a

    create_resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports",
        json={"name": "JSON Validation Test Import"},
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    import_id = create_resp.json()["id"]

    def _count_rows():
        with api_fixture.engine.connect() as conn:
            return (
                conn.execute(select(func.count()).select_from(adventure_imports)).scalar(),
                conn.execute(select(func.count()).select_from(adventure_import_sources)).scalar(),
                conn.execute(select(func.count()).select_from(adventure_import_drafts)).scalar(),
                conn.execute(select(func.count()).select_from(room_assets)).scalar(),
            )

    before_counts = _count_rows()

    # Case A: Malformed JSON body
    resp_malformed = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        content=b"{not valid json",
        headers={**_auth(token), "Content-Type": "application/json"},
    )
    assert resp_malformed.status_code == 422
    assert _count_rows() == before_counts

    # Case B: Missing discriminator (no source_kind)
    resp_no_disc = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        json={"text": "some text"},
        headers=_auth(token),
    )
    assert resp_no_disc.status_code == 422
    assert _count_rows() == before_counts

    # Case C: Wrong variant fields (source_kind=paste but missing required text)
    resp_wrong_fields = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        json={"source_kind": "paste", "filename": "test.txt"},
        headers=_auth(token),
    )
    assert resp_wrong_fields.status_code == 422
    assert _count_rows() == before_counts

    # Case D: Unknown source_kind discriminator
    resp_unknown_disc = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        json={"source_kind": "image", "text": "foo"},
        headers=_auth(token),
    )
    assert resp_unknown_disc.status_code == 422
    assert _count_rows() == before_counts


def test_production_dependency_get_adventure_import_service(
    api_fixture: ImportApiFixture,
) -> None:
    # 1. Clear app.state.adventure_import_service
    try:
        del app.state.adventure_import_service
    except AttributeError:
        pass

    # Ensure app.state.room_asset_service is set to the fixture's service
    app.state.room_asset_service = api_fixture.room_asset_service

    # Build a real Request with the app
    request = Request(scope={"type": "http", "app": app})

    # Call the production dependency getter
    service1 = get_adventure_import_service(request)
    assert isinstance(service1, AdventureImportService)
    assert service1.room_asset_service is api_fixture.room_asset_service

    # Proves it is cached in app.state
    service2 = get_adventure_import_service(request)
    assert service1 is service2
    assert getattr(app.state, "adventure_import_service") is service1

    # Cleanup
    try:
        del app.state.adventure_import_service
    except (AttributeError, KeyError):
        pass


def test_raw_upload_compensating_delete_for_missing_and_cancelled_import(
    api_fixture: ImportApiFixture,
) -> None:
    client = api_fixture.client
    room_id = api_fixture.room_a_id
    token = api_fixture.token_owner_a

    # Verify initial storage state
    with api_fixture.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(room_assets)).scalar() == 0
    room_storage_dir = api_fixture.tmp_path / str(room_id)
    assert not room_storage_dir.exists() or len(list(room_storage_dir.iterdir())) == 0

    # 1. Missing import ID
    missing_import_id = uuid4()
    resp_missing = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{missing_import_id}/sources",
        params={"source_kind": "txt", "filename": "missing_import.txt"},
        content=b"content for missing import",
        headers={**_auth(token), "Content-Type": "text/plain"},
    )
    assert resp_missing.status_code == 404
    assert resp_missing.json()["error"]["code"] == "adventure_import_not_found"

    # Verify no asset row and no filesystem file
    with api_fixture.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(room_assets)).scalar() == 0
    if room_storage_dir.exists():
        assert len(list(room_storage_dir.iterdir())) == 0

    # 2. Cancelled import
    create_resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports",
        json={"name": "Cancelled Import for Upload Test"},
        headers=_auth(token),
    )
    import_id = create_resp.json()["id"]

    cancel_resp = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/cancel",
        json={"expected_revision": 0},
        headers=_auth(token),
    )
    assert cancel_resp.status_code == 200

    resp_cancelled = client.post(
        f"/api/rooms/{room_id}/adventure-imports/{import_id}/sources",
        params={"source_kind": "txt", "filename": "cancelled_import.txt"},
        content=b"content for cancelled import",
        headers={**_auth(token), "Content-Type": "text/plain"},
    )
    assert resp_cancelled.status_code == 400
    assert resp_cancelled.json()["error"]["code"] == "adventure_import_invalid"

    # Verify compensating delete removed both DB row and filesystem file
    with api_fixture.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(room_assets)).scalar() == 0
    if room_storage_dir.exists():
        assert len(list(room_storage_dir.iterdir())) == 0

