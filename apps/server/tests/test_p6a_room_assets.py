from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
from typing import Generator
from urllib.parse import quote
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
from app.db import metadata
from app.content import load_default_content_registry
from app.domain.adventures.service import AdventureService
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.main import app
from app.persistence.adventures.repository import AdventureRepository
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
    adventure_entry_assets,
    campaign_adventure_links,
)
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.room_assets.tables import room_assets
from app.persistence.rooms.tables import campaigns, rooms


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


@dataclass(frozen=True)
class RoomAssetFixture:
    client: TestClient
    engine: Engine
    storage: FilesystemAssetStorage
    repository: RoomAssetRepository
    service: RoomAssetService
    room_a_id: UUID
    room_b_id: UUID
    token_owner_a: str
    token_dm_a: str
    token_member_a: str
    token_owner_b: str
    tmp_path: Path


def _upload(
    client: TestClient,
    token: str,
    *,
    room_id: UUID,
    kind: str,
    filename: str,
    mime: str,
    data: bytes,
    visibility: str | None = None,
):
    params: dict[str, str] = {
        "kind": kind,
        "filename": filename,
    }
    if visibility is not None:
        params["visibility"] = visibility
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": mime,
    }
    return client.post(
        f"/api/rooms/{room_id}/assets",
        params=params,
        content=data,
        headers=headers,
    )


@pytest.fixture
def asset_fixture(tmp_path: Path) -> Generator[RoomAssetFixture, None, None]:
    engine = _engine()
    storage = FilesystemAssetStorage(tmp_path)
    repository = RoomAssetRepository(engine)
    service = RoomAssetService(
        repository,
        storage,
        max_image_bytes=20 * 1024 * 1024,
        max_source_document_bytes=20 * 1024 * 1024,
    )

    room_a_id = uuid4()
    room_b_id = uuid4()
    now = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                id=room_a_id,
                code="ROOMA",
                name="Room A",
                password_salt=b"salt",
                password_hash=b"pw",
                owner_key_hash=b"owner",
                dm_key_hash=b"dm",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(rooms).values(
                id=room_b_id,
                code="ROOMB",
                name="Room B",
                password_salt=b"salt",
                password_hash=b"pw",
                owner_key_hash=b"owner",
                dm_key_hash=b"dm",
                created_at=now,
                updated_at=now,
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
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        token_clean = token.strip()
        if token_clean in token_to_context:
            return token_to_context[token_clean]
        raise APIError(401, "room_access_required", "Room access token is required")

    # Room hard delete resolves these two services from app.state; pin them to this
    # engine and restore whatever another test module left behind.
    previous_state = {
        name: app.state._state.get(name)
        for name in ("room_workspace_service", "adventure_service", "character_engine")
    }
    app.state.room_asset_service = service
    app.state.room_workspace_service = RoomCharacterWorkspaceService(
        engine, load_default_content_registry()
    )
    app.state.adventure_service = AdventureService(AdventureRepository(engine), repository)
    app.state.character_engine = engine
    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_room_access_context] = _override_access_context

    client = TestClient(app)
    try:
        yield RoomAssetFixture(
            client=client,
            engine=engine,
            storage=storage,
            repository=repository,
            service=service,
            room_a_id=room_a_id,
            room_b_id=room_b_id,
            token_owner_a=token_owner_a,
            token_dm_a=token_dm_a,
            token_member_a=token_member_a,
            token_owner_b=token_owner_b,
            tmp_path=tmp_path,
        )
    finally:
        del app.state.room_asset_service
        for name, value in previous_state.items():
            if value is None:
                app.state._state.pop(name, None)
            else:
                app.state._state[name] = value
        app.dependency_overrides.pop(get_database_engine, None)
        app.dependency_overrides.pop(get_room_access_context, None)


def test_owner_uploads_image_and_metadata_is_projected(asset_fixture: RoomAssetFixture) -> None:
    data = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    resp = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="dungeon.png",
        mime="image/png",
        data=data,
        visibility="room",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert body["room_id"] == str(asset_fixture.room_a_id)
    assert body["kind"] == "image"
    assert body["original_filename"] == "dungeon.png"
    assert body["mime_type"] == "image/png"
    assert body["size_bytes"] == len(data)
    expected_sha256 = hashlib.sha256(data).hexdigest()
    assert body["sha256"] == expected_sha256
    assert body["visibility"] == "room"
    assert "created_at" in body

    # File exists under tmp_path/<room_id>/<id>.png
    asset_id = body["id"]
    file_path = asset_fixture.tmp_path / str(asset_fixture.room_a_id) / f"{asset_id}.png"
    assert file_path.is_file()
    assert file_path.read_bytes() == data

    # JSON contains neither "storage_key" nor str(tmp_path)
    assert "storage_key" not in resp.text
    assert str(asset_fixture.tmp_path) not in resp.text


def test_dm_can_upload_member_cannot(asset_fixture: RoomAssetFixture) -> None:
    data = b"\x89PNG\r\n\x1a\ndm-image-bytes"
    # DM 201
    dm_resp = _upload(
        asset_fixture.client,
        asset_fixture.token_dm_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="dm-map.png",
        mime="image/png",
        data=data,
        visibility="room",
    )
    assert dm_resp.status_code == 201

    # MEMBER 403 and no row, no file
    member_data = b"\x89PNG\r\n\x1a\nmember-image-bytes"
    member_resp = _upload(
        asset_fixture.client,
        asset_fixture.token_member_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="member-map.png",
        mime="image/png",
        data=member_data,
        visibility="room",
    )
    assert member_resp.status_code == 403
    assert member_resp.json()["error"]["code"] == "room_asset_authority_required"

    with asset_fixture.engine.connect() as conn:
        count = conn.scalar(select(func.count()).select_from(room_assets))
        assert count == 1


def test_member_sees_room_image_but_not_dm_only_image(asset_fixture: RoomAssetFixture) -> None:
    data1 = b"\x89PNG\r\n\x1a\nroom-image"
    data2 = b"\x89PNG\r\n\x1a\ndm-only-image"

    resp1 = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="room.png",
        mime="image/png",
        data=data1,
        visibility="room",
    )
    assert resp1.status_code == 201
    id1 = resp1.json()["id"]

    resp2 = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="dm.png",
        mime="image/png",
        data=data2,
        visibility="dm_only",
    )
    assert resp2.status_code == 201
    id2 = resp2.json()["id"]

    # MEMBER GET list returns only the room one
    list_resp = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_a_id}/assets",
        headers={"Authorization": f"Bearer {asset_fixture.token_member_a}"},
    )
    assert list_resp.status_code == 200
    listed_ids = [item["id"] for item in list_resp.json()]
    assert id1 in listed_ids
    assert id2 not in listed_ids

    # GET /{dm_only_id} -> 404
    get_dm = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{id2}",
        headers={"Authorization": f"Bearer {asset_fixture.token_member_a}"},
    )
    assert get_dm.status_code == 404

    # GET /{dm_only_id}/content -> 404
    get_dm_content = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{id2}/content",
        headers={"Authorization": f"Bearer {asset_fixture.token_member_a}"},
    )
    assert get_dm_content.status_code == 404

    # DM GET both -> 200 and content bytes equal the upload
    dm_get1 = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{id1}",
        headers={"Authorization": f"Bearer {asset_fixture.token_dm_a}"},
    )
    assert dm_get1.status_code == 200
    dm_c1 = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{id1}/content",
        headers={"Authorization": f"Bearer {asset_fixture.token_dm_a}"},
    )
    assert dm_c1.status_code == 200
    assert dm_c1.content == data1

    dm_get2 = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{id2}",
        headers={"Authorization": f"Bearer {asset_fixture.token_dm_a}"},
    )
    assert dm_get2.status_code == 200
    dm_c2 = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{id2}/content",
        headers={"Authorization": f"Bearer {asset_fixture.token_dm_a}"},
    )
    assert dm_c2.status_code == 200
    assert dm_c2.content == data2


def test_source_document_is_forced_dm_only(asset_fixture: RoomAssetFixture) -> None:
    data = b"# DM Secret Notes\nDo not share."
    # owner upload kind=source_document with visibility=room -> 400 asset_visibility_not_allowed, zero rows, zero files
    bad_resp = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="source_document",
        filename="notes.md",
        mime="text/markdown",
        data=data,
        visibility="room",
    )
    assert bad_resp.status_code == 400
    assert bad_resp.json()["error"]["code"] == "asset_visibility_not_allowed"

    with asset_fixture.engine.connect() as conn:
        count = conn.scalar(select(func.count()).select_from(room_assets))
        assert count == 0
    assert not [f for f in asset_fixture.tmp_path.rglob("*") if f.is_file()]

    # with visibility=dm_only -> 201
    ok_resp = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="source_document",
        filename="notes.md",
        mime="text/markdown",
        data=data,
        visibility="dm_only",
    )
    assert ok_resp.status_code == 201
    doc_id = ok_resp.json()["id"]

    # MEMBER cannot list/get/content it (404)
    member_list = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_a_id}/assets",
        headers={"Authorization": f"Bearer {asset_fixture.token_member_a}"},
    )
    assert member_list.status_code == 200
    assert doc_id not in [item["id"] for item in member_list.json()]

    assert (
        asset_fixture.client.get(
            f"/api/rooms/{asset_fixture.room_a_id}/assets/{doc_id}",
            headers={"Authorization": f"Bearer {asset_fixture.token_member_a}"},
        ).status_code
        == 404
    )
    assert (
        asset_fixture.client.get(
            f"/api/rooms/{asset_fixture.room_a_id}/assets/{doc_id}/content",
            headers={"Authorization": f"Bearer {asset_fixture.token_member_a}"},
        ).status_code
        == 404
    )

    # DM can
    assert (
        asset_fixture.client.get(
            f"/api/rooms/{asset_fixture.room_a_id}/assets/{doc_id}",
            headers={"Authorization": f"Bearer {asset_fixture.token_dm_a}"},
        ).status_code
        == 200
    )
    dm_content = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{doc_id}/content",
        headers={"Authorization": f"Bearer {asset_fixture.token_dm_a}"},
    )
    assert dm_content.status_code == 200
    assert dm_content.content == data


def test_unsupported_media_type_leaves_no_orphan(asset_fixture: RoomAssetFixture) -> None:
    # image with Content-Type image/gif -> 400
    resp1 = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="anim.gif",
        mime="image/gif",
        data=b"GIF89a...",
        visibility="room",
    )
    assert resp1.status_code == 400
    assert resp1.json()["error"]["code"] == "asset_media_type_not_supported"

    # source_document with Content-Type text/html -> 400
    resp2 = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="source_document",
        filename="page.html",
        mime="text/html",
        data=b"<html></html>",
        visibility="dm_only",
    )
    assert resp2.status_code == 400
    assert resp2.json()["error"]["code"] == "asset_media_type_not_supported"

    # rows == 0 and tmp_path has no files
    with asset_fixture.engine.connect() as conn:
        count = conn.scalar(select(func.count()).select_from(room_assets))
        assert count == 0
    assert not [f for f in asset_fixture.tmp_path.rglob("*") if f.is_file()]


def test_oversize_upload_leaves_no_orphan(asset_fixture: RoomAssetFixture) -> None:
    # construct the service with max_image_bytes=1024 for this test
    custom_service = RoomAssetService(
        asset_fixture.repository,
        asset_fixture.storage,
        max_image_bytes=1024,
        max_source_document_bytes=1024,
    )
    app.state.room_asset_service = custom_service

    # upload 1025 bytes -> 413
    data = b"x" * 1025
    resp = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="big.png",
        mime="image/png",
        data=data,
        visibility="room",
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "asset_too_large"

    # rows == 0; no files
    with asset_fixture.engine.connect() as conn:
        count = conn.scalar(select(func.count()).select_from(room_assets))
        assert count == 0
    assert not [f for f in asset_fixture.tmp_path.rglob("*") if f.is_file()]


def test_storage_failure_rolls_back_row(
    asset_fixture: RoomAssetFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_write(storage_key: str, data: bytes) -> None:
        raise OSError("Simulated disk error")

    monkeypatch.setattr(asset_fixture.storage, "write", _fail_write)

    # Use a client with raise_server_exceptions=False to assert on HTTP 500
    safe_client = TestClient(app, raise_server_exceptions=False)
    data = b"\x89PNG\r\n\x1a\ntest"
    resp = _upload(
        safe_client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="test.png",
        mime="image/png",
        data=data,
        visibility="room",
    )
    assert resp.status_code >= 500

    # rows == 0 AND no file
    with asset_fixture.engine.connect() as conn:
        count = conn.scalar(select(func.count()).select_from(room_assets))
        assert count == 0
    assert not [f for f in asset_fixture.tmp_path.rglob("*") if f.is_file()]


def test_cross_room_asset_is_not_found(asset_fixture: RoomAssetFixture) -> None:
    data = b"\x89PNG\r\n\x1a\nroom-a-image"
    resp = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="room-a.png",
        mime="image/png",
        data=data,
        visibility="room",
    )
    assert resp.status_code == 201
    asset_a_id = resp.json()["id"]

    # owner of Room B GET /api/rooms/{room_b}/assets/{asset_a_id} -> 404
    resp_b = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_b_id}/assets/{asset_a_id}",
        headers={"Authorization": f"Bearer {asset_fixture.token_owner_b}"},
    )
    assert resp_b.status_code == 404

    # also GET with room_a id but Room B token -> 404 (context.room_id mismatch)
    resp_mismatch = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{asset_a_id}",
        headers={"Authorization": f"Bearer {asset_fixture.token_owner_b}"},
    )
    assert resp_mismatch.status_code == 404


def test_delete_removes_row_and_file_and_refuses_when_referenced(
    asset_fixture: RoomAssetFixture,
) -> None:
    data = b"\x89PNG\r\n\x1a\ndelete-target"
    resp1 = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="del1.png",
        mime="image/png",
        data=data,
        visibility="room",
    )
    assert resp1.status_code == 201
    id1 = resp1.json()["id"]
    file1 = asset_fixture.tmp_path / str(asset_fixture.room_a_id) / f"{id1}.png"
    assert file1.is_file()

    # owner delete -> 204, row and file gone
    del_resp1 = asset_fixture.client.delete(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{id1}",
        headers={"Authorization": f"Bearer {asset_fixture.token_owner_a}"},
    )
    assert del_resp1.status_code == 204
    assert not file1.exists()
    with asset_fixture.engine.connect() as conn:
        assert conn.scalar(select(room_assets.c.id).where(room_assets.c.id == UUID(id1))) is None

    # upload again
    resp2 = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="del2.png",
        mime="image/png",
        data=data,
        visibility="room",
    )
    assert resp2.status_code == 201
    id2 = resp2.json()["id"]
    file2 = asset_fixture.tmp_path / str(asset_fixture.room_a_id) / f"{id2}.png"
    assert file2.is_file()

    # insert an adventure_definitions + adventure_entries + adventure_entry_assets row directly via SQLAlchemy
    adv_id = uuid4()
    entry_id = uuid4()
    now = datetime.now(timezone.utc)
    with asset_fixture.engine.begin() as conn:
        conn.execute(
            insert(adventure_definitions).values(
                id=adv_id,
                room_id=asset_fixture.room_a_id,
                name="Test Adventure",
                summary="A test adventure",
                ruleset="dnd5e-2014",
                status="draft",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(adventure_entries).values(
                id=entry_id,
                adventure_id=adv_id,
                kind="scene",
                title="Scene 1",
                data_json={},
                visibility="public",
                sort_order=0,
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(adventure_entry_assets).values(
                adventure_entry_id=entry_id,
                asset_id=UUID(id2),
                role="image",
                sort_order=0,
            )
        )

    # DELETE -> 409 asset_in_use, row and file still present
    del_resp2 = asset_fixture.client.delete(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{id2}",
        headers={"Authorization": f"Bearer {asset_fixture.token_owner_a}"},
    )
    assert del_resp2.status_code == 409
    assert del_resp2.json()["error"]["code"] == "asset_in_use"
    assert file2.is_file()
    with asset_fixture.engine.connect() as conn:
        assert (
            conn.scalar(select(room_assets.c.id).where(room_assets.c.id == UUID(id2))) is not None
        )

    # MEMBER DELETE -> 403
    member_del = asset_fixture.client.delete(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{id2}",
        headers={"Authorization": f"Bearer {asset_fixture.token_member_a}"},
    )
    assert member_del.status_code == 403
    assert member_del.json()["error"]["code"] == "room_asset_authority_required"


def test_content_disposition_uses_original_filename(asset_fixture: RoomAssetFixture) -> None:
    original_name = "map of 'Old' Keep.png"
    data = b"\x89PNG\r\n\x1a\nmap-bytes"
    resp = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename=original_name,
        mime="image/png",
        data=data,
        visibility="room",
    )
    assert resp.status_code == 201
    asset_id = resp.json()["id"]

    content_resp = asset_fixture.client.get(
        f"/api/rooms/{asset_fixture.room_a_id}/assets/{asset_id}/content",
        headers={"Authorization": f"Bearer {asset_fixture.token_owner_a}"},
    )
    assert content_resp.status_code == 200
    assert content_resp.headers["content-type"] == "image/png"
    content_disp = content_resp.headers.get("content-disposition", "")
    assert content_disp.startswith("inline; filename=\"map of 'Old' Keep.png\"")
    assert f"filename*=UTF-8''{quote(original_name)}" in content_disp


def test_room_hard_delete_removes_assets_adventures_and_files(
    asset_fixture: RoomAssetFixture,
) -> None:
    # owner uploads two images and one source_document
    img1_resp = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="img1.png",
        mime="image/png",
        data=b"\x89PNG\r\n\x1a\nimg1",
        visibility="room",
    )
    assert img1_resp.status_code == 201
    img1_id = img1_resp.json()["id"]

    img2_resp = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="img2.png",
        mime="image/png",
        data=b"\x89PNG\r\n\x1a\nimg2",
        visibility="room",
    )
    assert img2_resp.status_code == 201
    img2_id = img2_resp.json()["id"]

    doc_resp = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="source_document",
        filename="notes.txt",
        mime="text/plain",
        data=b"secret notes",
        visibility="dm_only",
    )
    assert doc_resp.status_code == 201

    # upload one image to Room B before the delete
    img_b_resp = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_b,
        room_id=asset_fixture.room_b_id,
        kind="image",
        filename="b.png",
        mime="image/png",
        data=b"\x89PNG\r\n\x1a\nimgB",
        visibility="room",
    )
    assert img_b_resp.status_code == 201
    img_b_id = img_b_resp.json()["id"]

    # creates an Adventure via POST /api/rooms/{room_a}/adventures, an entry, links one image (POST .../entries/{id}/assets), finalizes
    auth_a = {"Authorization": f"Bearer {asset_fixture.token_owner_a}"}
    adv_resp = asset_fixture.client.post(
        f"/api/rooms/{asset_fixture.room_a_id}/adventures",
        json={"name": "Adventure A"},
        headers=auth_a,
    )
    assert adv_resp.status_code == 201
    adv_id = adv_resp.json()["id"]

    entry_resp = asset_fixture.client.post(
        f"/api/rooms/{asset_fixture.room_a_id}/adventures/{adv_id}/entries",
        json={"kind": "scene", "title": "Scene 1"},
        headers=auth_a,
    )
    assert entry_resp.status_code == 201
    entry_id = entry_resp.json()["id"]

    link_resp = asset_fixture.client.post(
        f"/api/rooms/{asset_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets",
        json={"asset_id": img1_id, "role": "image"},
        headers=auth_a,
    )
    assert link_resp.status_code == 200

    fin_resp = asset_fixture.client.post(
        f"/api/rooms/{asset_fixture.room_a_id}/adventures/{adv_id}/finalize",
        headers=auth_a,
    )
    assert fin_resp.status_code == 200

    # seed a Campaign and link the finalized Adventure to it
    camp_id = uuid4()
    now = datetime.now(timezone.utc)
    with asset_fixture.engine.begin() as conn:
        conn.execute(
            insert(campaigns).values(
                id=camp_id,
                room_id=asset_fixture.room_a_id,
                name="Campaign Alpha",
                ruleset="dnd5e-2014",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        conn.execute(
            insert(campaign_adventure_links).values(
                campaign_id=camp_id,
                adventure_id=UUID(adv_id),
                sort_order=0,
                attached_at=now,
            )
        )

    # DELETE /api/rooms/{room_a} with the owner token → 204
    del_resp = asset_fixture.client.delete(
        f"/api/rooms/{asset_fixture.room_a_id}",
        headers=auth_a,
    )
    assert del_resp.status_code == 204

    # every Room A row across the P6-A tables is gone
    with asset_fixture.engine.connect() as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(rooms)
                .where(rooms.c.id == asset_fixture.room_a_id)
            )
            == 0
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(room_assets)
                .where(room_assets.c.room_id == asset_fixture.room_a_id)
            )
            == 0
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(adventure_definitions)
                .where(adventure_definitions.c.room_id == asset_fixture.room_a_id)
            )
            == 0
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(adventure_entries)
                .where(adventure_entries.c.adventure_id == UUID(adv_id))
            )
            == 0
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(adventure_entry_assets)
                .where(adventure_entry_assets.c.adventure_entry_id == UUID(entry_id))
            )
            == 0
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(campaign_adventure_links)
                .where(campaign_adventure_links.c.campaign_id == camp_id)
            )
            == 0
        )

    # tmp_path/<room_a> contains no files
    room_a_dir = asset_fixture.tmp_path / str(asset_fixture.room_a_id)
    if room_a_dir.exists():
        assert not [f for f in room_a_dir.rglob("*") if f.is_file()]

    # Room B is untouched
    with asset_fixture.engine.connect() as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(rooms)
                .where(rooms.c.id == asset_fixture.room_b_id)
            )
            == 1
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(room_assets)
                .where(room_assets.c.room_id == asset_fixture.room_b_id)
            )
            == 1
        )
    file_b = asset_fixture.tmp_path / str(asset_fixture.room_b_id) / f"{img_b_id}.png"
    assert file_b.is_file()


def test_room_hard_delete_file_failure_keeps_locator_and_deletes_the_rest(
    asset_fixture: RoomAssetFixture,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # owner uploads three images
    ids: list[str] = []
    for i in range(3):
        resp = _upload(
            asset_fixture.client,
            asset_fixture.token_owner_a,
            room_id=asset_fixture.room_a_id,
            kind="image",
            filename=f"img{i}.png",
            mime="image/png",
            data=b"\x89PNG\r\n\x1a\n" + f"img-data-{i}".encode(),
            visibility="room",
        )
        assert resp.status_code == 201
        ids.append(resp.json()["id"])

    # one storage_key fails to delete, the others succeed
    failing_id = ids[1]
    failing_key = f"{asset_fixture.room_a_id}/{failing_id}.png"
    orig_delete = asset_fixture.storage.delete

    def _delete_with_one_failure(storage_key: str) -> None:
        if storage_key == failing_key:
            raise OSError("Simulated disk error on delete")
        orig_delete(storage_key)

    monkeypatch.setattr(asset_fixture.storage, "delete", _delete_with_one_failure)

    auth_a = {"Authorization": f"Bearer {asset_fixture.token_owner_a}"}
    # Alembic's fileConfig (run by migration tests in the same worker) disables
    # existing loggers; re-enable ours so the capture below sees the record.
    logging.getLogger("app.domain.room_assets.service").disabled = False
    with caplog.at_level(logging.ERROR, logger="app.domain.room_assets.service"):
        del_resp = asset_fixture.client.delete(
            f"/api/rooms/{asset_fixture.room_a_id}",
            headers=auth_a,
        )
    assert del_resp.status_code == 204

    # all DB rows gone
    with asset_fixture.engine.connect() as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(rooms)
                .where(rooms.c.id == asset_fixture.room_a_id)
            )
            == 0
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(room_assets)
                .where(room_assets.c.room_id == asset_fixture.room_a_id)
            )
            == 0
        )

    # the two other files gone
    assert not (asset_fixture.tmp_path / str(asset_fixture.room_a_id) / f"{ids[0]}.png").exists()
    assert not (asset_fixture.tmp_path / str(asset_fixture.room_a_id) / f"{ids[2]}.png").exists()

    # the failing file still on disk
    failing_file = asset_fixture.tmp_path / str(asset_fixture.room_a_id) / f"{failing_id}.png"
    assert failing_file.is_file()

    # exactly one ERROR line, and it locates the orphan by room and storage_key
    error_records = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR and r.name == "app.domain.room_assets.service"
    ]
    assert len(error_records) == 1
    rec_msg = error_records[0].getMessage()
    assert str(asset_fixture.room_a_id) in rec_msg
    assert failing_key in rec_msg

    # the report a retry job would consume
    report = asset_fixture.service.purge_storage_keys(
        asset_fixture.room_a_id, [failing_key]
    )
    assert report.deleted == 0
    assert report.failed == (failing_key,)


def test_room_hard_delete_by_member_is_403_and_touches_nothing(
    asset_fixture: RoomAssetFixture,
) -> None:
    # owner uploads an image
    resp = _upload(
        asset_fixture.client,
        asset_fixture.token_owner_a,
        room_id=asset_fixture.room_a_id,
        kind="image",
        filename="test.png",
        mime="image/png",
        data=b"\x89PNG\r\n\x1a\ntest",
        visibility="room",
    )
    assert resp.status_code == 201
    asset_id = resp.json()["id"]
    file_path = asset_fixture.tmp_path / str(asset_fixture.room_a_id) / f"{asset_id}.png"
    assert file_path.is_file()

    # member token DELETE room → 403
    del_resp = asset_fixture.client.delete(
        f"/api/rooms/{asset_fixture.room_a_id}",
        headers={"Authorization": f"Bearer {asset_fixture.token_member_a}"},
    )
    assert del_resp.status_code == 403

    # asset rows and files unchanged
    with asset_fixture.engine.connect() as conn:
        assert (
            conn.scalar(
                select(func.count())
                .select_from(rooms)
                .where(rooms.c.id == asset_fixture.room_a_id)
            )
            == 1
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(room_assets)
                .where(room_assets.c.room_id == asset_fixture.room_a_id)
            )
            == 1
        )
    assert file_path.is_file()
