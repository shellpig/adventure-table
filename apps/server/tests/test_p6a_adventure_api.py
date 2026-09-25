from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, delete, event, func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_database_engine
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.db import metadata
from app.domain.adventures.service import AdventureService
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
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
class AdventureApiFixture:
    client: TestClient
    engine: Engine
    room_a_id: UUID
    room_b_id: UUID
    token_owner_a: str
    token_dm_a: str
    token_member_a: str
    token_owner_b: str
    tmp_path: Path


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_adventure(
    client: TestClient,
    token: str,
    room_id: UUID,
    name: str,
) -> dict[str, object]:
    resp = client.post(
        f"/api/rooms/{room_id}/adventures",
        json={"name": name},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    return resp.json()


def _upload_asset(
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
def api_fixture(tmp_path: Path) -> Generator[AdventureApiFixture, None, None]:
    engine = _engine()
    storage = FilesystemAssetStorage(tmp_path)
    asset_repo = RoomAssetRepository(engine)
    room_asset_service = RoomAssetService(
        asset_repo,
        storage,
        max_image_bytes=20 * 1024 * 1024,
        max_source_document_bytes=20 * 1024 * 1024,
    )
    adv_repo = AdventureRepository(engine)
    adventure_service = AdventureService(adv_repo, asset_repo)

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
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        token_clean = token.strip()
        if token_clean in token_to_context:
            return token_to_context[token_clean]
        raise APIError(401, "room_access_required", "Room access token is required")

    app.state.room_asset_service = room_asset_service
    app.state.adventure_service = adventure_service
    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_room_access_context] = _override_access_context

    client = TestClient(app)
    try:
        yield AdventureApiFixture(
            client=client,
            engine=engine,
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
        del app.state.adventure_service
        app.dependency_overrides.pop(get_database_engine, None)
        app.dependency_overrides.pop(get_room_access_context, None)


def test_owner_full_authoring_flow_over_http(api_fixture: AdventureApiFixture) -> None:
    # POST adventure (name only) 201 status draft
    adv = _create_adventure(
        api_fixture.client,
        api_fixture.token_owner_a,
        api_fixture.room_a_id,
        "The Sunless Citadel",
    )
    assert adv["status"] == "draft"
    adv_id = adv["id"]

    # POST scene entry 201
    entry_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
        json={"kind": "scene", "title": "Courtyard", "data": {"read_aloud": "Cold wind."}},
        headers=_auth(api_fixture.token_owner_a),
    )
    assert entry_resp.status_code == 201
    entry_data = entry_resp.json()
    entry_id = entry_data["id"]
    assert entry_data["kind"] == "scene"
    assert entry_data["title"] == "Courtyard"

    # PATCH entry body 200
    patch_resp = api_fixture.client.patch(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}",
        json={"body": "Updated scene description"},
        headers=_auth(api_fixture.token_owner_a),
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["body"] == "Updated scene description"

    # GET entries lists 1 with assets == []
    list_resp = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
        headers=_auth(api_fixture.token_owner_a),
    )
    assert list_resp.status_code == 200
    entries = list_resp.json()
    assert len(entries) == 1
    assert entries[0]["assets"] == []

    # POST reorder 204
    reorder_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/reorder",
        json={"entry_ids": [entry_id]},
        headers=_auth(api_fixture.token_owner_a),
    )
    assert reorder_resp.status_code == 204

    # DELETE entry 204
    del_resp = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}",
        headers=_auth(api_fixture.token_owner_a),
    )
    assert del_resp.status_code == 204

    # GET entries empty
    list_resp2 = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
        headers=_auth(api_fixture.token_owner_a),
    )
    assert list_resp2.status_code == 200
    assert list_resp2.json() == []


def test_dm_can_write_member_gets_404_everywhere(api_fixture: AdventureApiFixture) -> None:
    # dm_a POST adventure 201 and POST entry 201
    adv = _create_adventure(
        api_fixture.client,
        api_fixture.token_dm_a,
        api_fixture.room_a_id,
        "DM Adventure",
    )
    adv_id = adv["id"]

    entry_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
        json={"kind": "section", "title": "Intro"},
        headers=_auth(api_fixture.token_dm_a),
    )
    assert entry_resp.status_code == 201
    entry_id = entry_resp.json()["id"]

    # Record row counts before member operations
    with api_fixture.engine.connect() as conn:
        def_count_before = conn.scalar(select(func.count()).select_from(adventure_definitions))
        entry_count_before = conn.scalar(select(func.count()).select_from(adventure_entries))

    member_auth = _auth(api_fixture.token_member_a)

    # member_a operations: all 404 with code adventure_not_found
    calls = [
        api_fixture.client.get(f"/api/rooms/{api_fixture.room_a_id}/adventures", headers=member_auth),
        api_fixture.client.get(f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}", headers=member_auth),
        api_fixture.client.get(f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries", headers=member_auth),
        api_fixture.client.post(
            f"/api/rooms/{api_fixture.room_a_id}/adventures",
            json={"name": "Member Adv"},
            headers=member_auth,
        ),
        api_fixture.client.post(
            f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
            json={"kind": "section", "title": "Member Entry"},
            headers=member_auth,
        ),
        api_fixture.client.patch(
            f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}",
            json={"name": "Hacked Adv"},
            headers=member_auth,
        ),
        api_fixture.client.delete(
            f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}",
            headers=member_auth,
        ),
        api_fixture.client.post(
            f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/finalize",
            headers=member_auth,
        ),
        api_fixture.client.post(
            f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/archive",
            headers=member_auth,
        ),
    ]

    for resp in calls:
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "adventure_not_found"

    # Row counts unchanged after member writes
    with api_fixture.engine.connect() as conn:
        def_count_after = conn.scalar(select(func.count()).select_from(adventure_definitions))
        entry_count_after = conn.scalar(select(func.count()).select_from(adventure_entries))
        assert def_count_after == def_count_before
        assert entry_count_after == entry_count_before


def test_cross_room_is_404(api_fixture: AdventureApiFixture) -> None:
    adv = _create_adventure(
        api_fixture.client,
        api_fixture.token_owner_a,
        api_fixture.room_a_id,
        "Room A Adv",
    )
    adv_id = adv["id"]

    # owner_b on /api/rooms/{room_b}/adventures/{adventure_in_a} GET/PATCH/finalize -> 404
    auth_b = _auth(api_fixture.token_owner_b)
    resp_get = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_b_id}/adventures/{adv_id}",
        headers=auth_b,
    )
    assert resp_get.status_code == 404

    resp_patch = api_fixture.client.patch(
        f"/api/rooms/{api_fixture.room_b_id}/adventures/{adv_id}",
        json={"name": "Stolen"},
        headers=auth_b,
    )
    assert resp_patch.status_code == 404

    resp_fin = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_b_id}/adventures/{adv_id}/finalize",
        headers=auth_b,
    )
    assert resp_fin.status_code == 404

    # owner_b with room_a in the URL -> 404 (context.room_id mismatch)
    resp_mismatch = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}",
        headers=auth_b,
    )
    assert resp_mismatch.status_code == 404


def test_finalize_then_archive_lifecycle(api_fixture: AdventureApiFixture) -> None:
    auth_a = _auth(api_fixture.token_owner_a)
    adv = _create_adventure(
        api_fixture.client,
        api_fixture.token_owner_a,
        api_fixture.room_a_id,
        "Lifecycle Adv",
    )
    adv_id = adv["id"]

    # finalize draft -> 200 status finalized
    fin_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/finalize",
        headers=auth_a,
    )
    assert fin_resp.status_code == 200
    assert fin_resp.json()["status"] == "finalized"

    # finalize again -> 409 adventure_status_conflict
    fin_again = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/finalize",
        headers=auth_a,
    )
    assert fin_again.status_code == 409
    assert fin_again.json()["error"]["code"] == "adventure_status_conflict"

    # PATCH name on finalized -> 200 (authoring correction allowed)
    patch_resp = api_fixture.client.patch(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}",
        json={"name": "Lifecycle Adv Corrected"},
        headers=auth_a,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Lifecycle Adv Corrected"

    # POST entry on finalized -> 201
    entry_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
        json={"kind": "section", "title": "Act I"},
        headers=auth_a,
    )
    assert entry_resp.status_code == 201

    # archive -> 200 status archived
    arch_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/archive",
        headers=auth_a,
    )
    assert arch_resp.status_code == 200
    assert arch_resp.json()["status"] == "archived"

    # POST entry on archived -> 409 adventure_archived
    entry_arch = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
        json={"kind": "section", "title": "Act II"},
        headers=auth_a,
    )
    assert entry_arch.status_code == 409
    assert entry_arch.json()["error"]["code"] == "adventure_archived"

    # PATCH definition on archived -> 409
    patch_arch = api_fixture.client.patch(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}",
        json={"name": "Cannot change"},
        headers=auth_a,
    )
    assert patch_arch.status_code == 409
    assert patch_arch.json()["error"]["code"] == "adventure_archived"

    # archive again -> 200 (idempotent)
    arch_again = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/archive",
        headers=auth_a,
    )
    assert arch_again.status_code == 200
    assert arch_again.json()["status"] == "archived"


def test_delete_rules(api_fixture: AdventureApiFixture) -> None:
    auth_a = _auth(api_fixture.token_owner_a)

    # DELETE draft -> 204 and GET -> 404
    adv1 = _create_adventure(
        api_fixture.client,
        api_fixture.token_owner_a,
        api_fixture.room_a_id,
        "Draft Adv to Delete",
    )
    adv1_id = adv1["id"]

    del_resp1 = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv1_id}",
        headers=auth_a,
    )
    assert del_resp1.status_code == 204

    get_resp1 = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv1_id}",
        headers=auth_a,
    )
    assert get_resp1.status_code == 404

    # create+finalize another
    adv2 = _create_adventure(
        api_fixture.client,
        api_fixture.token_owner_a,
        api_fixture.room_a_id,
        "Attached Adv",
    )
    adv2_id = UUID(str(adv2["id"]))

    fin_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv2_id}/finalize",
        headers=auth_a,
    )
    assert fin_resp.status_code == 200

    # insert an entry
    entry_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv2_id}/entries",
        json={"kind": "section", "title": "Sec 1"},
        headers=auth_a,
    )
    assert entry_resp.status_code == 201

    # insert a campaign row and a campaign_adventure_links row directly via SQLAlchemy
    camp_id = uuid4()
    now = datetime.now(timezone.utc)
    with api_fixture.engine.begin() as conn:
        conn.execute(
            insert(campaigns).values(
                id=camp_id,
                room_id=api_fixture.room_a_id,
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
                adventure_id=adv2_id,
                sort_order=0,
                attached_at=now,
            )
        )

    # DELETE -> 409 adventure_attached_use_archive and the definition + entries + link still exist
    del_att = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv2_id}",
        headers=auth_a,
    )
    assert del_att.status_code == 409
    assert del_att.json()["error"]["code"] == "adventure_attached_use_archive"

    with api_fixture.engine.connect() as conn:
        assert (
            conn.scalar(
                select(adventure_definitions.c.id).where(
                    adventure_definitions.c.id == adv2_id
                )
            )
            is not None
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(adventure_entries)
                .where(adventure_entries.c.adventure_id == adv2_id)
            )
            == 1
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(campaign_adventure_links)
                .where(campaign_adventure_links.c.adventure_id == adv2_id)
            )
            == 1
        )

    # archive it -> 200
    arch_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv2_id}/archive",
        headers=auth_a,
    )
    assert arch_resp.status_code == 200
    assert arch_resp.json()["status"] == "archived"

    # DELETE while still linked -> still 409 (archive does not make an attached Adventure deletable)
    del_arch_linked = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv2_id}",
        headers=auth_a,
    )
    assert del_arch_linked.status_code == 409
    assert del_arch_linked.json()["error"]["code"] == "adventure_attached_use_archive"

    # remove the link row -> DELETE -> 204
    with api_fixture.engine.begin() as conn:
        conn.execute(
            delete(campaign_adventure_links).where(
                campaign_adventure_links.c.adventure_id == adv2_id
            )
        )

    del_unlinked = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv2_id}",
        headers=auth_a,
    )
    assert del_unlinked.status_code == 204


def test_entry_asset_link_and_unlink(api_fixture: AdventureApiFixture) -> None:
    auth_a = _auth(api_fixture.token_owner_a)

    # upload an image asset via POST /api/rooms/{room_a}/assets (raw body)
    img_bytes = b"\x89PNG\r\n\x1a\nfake-image"
    img_resp = _upload_asset(
        api_fixture.client,
        api_fixture.token_owner_a,
        room_id=api_fixture.room_a_id,
        kind="image",
        filename="map.png",
        mime="image/png",
        data=img_bytes,
        visibility="room",
    )
    assert img_resp.status_code == 201
    image_id = img_resp.json()["id"]

    # upload a source_document (dm_only)
    doc_bytes = b"# Source doc\nNotes"
    doc_resp = _upload_asset(
        api_fixture.client,
        api_fixture.token_owner_a,
        room_id=api_fixture.room_a_id,
        kind="source_document",
        filename="notes.md",
        mime="text/markdown",
        data=doc_bytes,
        visibility="dm_only",
    )
    assert doc_resp.status_code == 201
    doc_id = doc_resp.json()["id"]

    adv = _create_adventure(
        api_fixture.client,
        api_fixture.token_owner_a,
        api_fixture.room_a_id,
        "Asset Link Adv",
    )
    adv_id = adv["id"]

    entry_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
        json={"kind": "scene", "title": "Chamber"},
        headers=auth_a,
    )
    assert entry_resp.status_code == 201
    entry_id = entry_resp.json()["id"]

    # POST entries/{id}/assets {asset_id: image, role: "image"} -> 200
    link1 = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets",
        json={"asset_id": image_id, "role": "image"},
        headers=auth_a,
    )
    assert link1.status_code == 200
    entry_view1 = link1.json()
    assert len(entry_view1["assets"]) == 1
    assert entry_view1["assets"][0]["asset"]["id"] == image_id
    assert "storage_key" not in entry_view1["assets"][0]["asset"]
    assert entry_view1["assets"][0]["sort_order"] == 0

    # role "source" with the image -> 400 adventure_entry_payload_invalid
    bad_source = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets",
        json={"asset_id": image_id, "role": "source"},
        headers=auth_a,
    )
    assert bad_source.status_code == 400
    assert bad_source.json()["error"]["code"] == "adventure_entry_payload_invalid"

    # role "source" with the source_document -> 200 (now 2 assets, sort_order 0 and 1)
    link2 = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets",
        json={"asset_id": doc_id, "role": "source"},
        headers=auth_a,
    )
    assert link2.status_code == 200
    entry_view2 = link2.json()
    assert len(entry_view2["assets"]) == 2
    assert entry_view2["assets"][0]["sort_order"] == 0
    assert entry_view2["assets"][1]["sort_order"] == 1
    assert entry_view2["assets"][1]["asset"]["id"] == doc_id

    # duplicate link -> 400
    dup_link = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets",
        json={"asset_id": image_id, "role": "image"},
        headers=auth_a,
    )
    assert dup_link.status_code == 400
    assert dup_link.json()["error"]["code"] == "adventure_entry_payload_invalid"

    # DELETE entries/{id}/assets/{image_id} -> 200 with 1 asset left
    unlink1 = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets/{image_id}",
        headers=auth_a,
    )
    assert unlink1.status_code == 200
    entry_view3 = unlink1.json()
    assert len(entry_view3["assets"]) == 1
    assert entry_view3["assets"][0]["asset"]["id"] == doc_id

    # DELETE again -> 404 adventure_entry_asset_not_found
    unlink2 = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets/{image_id}",
        headers=auth_a,
    )
    assert unlink2.status_code == 404
    assert unlink2.json()["error"]["code"] == "adventure_entry_asset_not_found"


def test_entry_asset_link_rejects_cross_room_and_unknown_assets(
    api_fixture: AdventureApiFixture,
) -> None:
    auth_a = _auth(api_fixture.token_owner_a)

    # owner_b uploads an image in room B
    img_bytes = b"\x89PNG\r\n\x1a\nroom-b-image"
    resp_b = _upload_asset(
        api_fixture.client,
        api_fixture.token_owner_b,
        room_id=api_fixture.room_b_id,
        kind="image",
        filename="room_b.png",
        mime="image/png",
        data=img_bytes,
        visibility="room",
    )
    assert resp_b.status_code == 201
    asset_b_id = resp_b.json()["id"]

    adv = _create_adventure(
        api_fixture.client,
        api_fixture.token_owner_a,
        api_fixture.room_a_id,
        "Room A Adv",
    )
    adv_id = adv["id"]

    entry_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
        json={"kind": "scene", "title": "Room A Scene"},
        headers=auth_a,
    )
    assert entry_resp.status_code == 201
    entry_id = entry_resp.json()["id"]

    # owner_a links it to a room-A entry -> 404 adventure_entry_asset_not_found
    cross_link = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets",
        json={"asset_id": asset_b_id, "role": "image"},
        headers=auth_a,
    )
    assert cross_link.status_code == 404
    assert cross_link.json()["error"]["code"] == "adventure_entry_asset_not_found"

    # random uuid -> 404
    random_id = str(uuid4())
    unknown_link = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets",
        json={"asset_id": random_id, "role": "image"},
        headers=auth_a,
    )
    assert unknown_link.status_code == 404
    assert unknown_link.json()["error"]["code"] == "adventure_entry_asset_not_found"

    # nothing written to adventure_entry_assets
    with api_fixture.engine.connect() as conn:
        count = conn.scalar(select(func.count()).select_from(adventure_entry_assets))
        assert count == 0


def test_room_asset_delete_refused_while_linked(api_fixture: AdventureApiFixture) -> None:
    auth_a = _auth(api_fixture.token_owner_a)

    # upload image
    img_bytes = b"\x89PNG\r\n\x1a\nkeep-image"
    img_resp = _upload_asset(
        api_fixture.client,
        api_fixture.token_owner_a,
        room_id=api_fixture.room_a_id,
        kind="image",
        filename="keep.png",
        mime="image/png",
        data=img_bytes,
        visibility="room",
    )
    assert img_resp.status_code == 201
    image_id = img_resp.json()["id"]

    adv = _create_adventure(
        api_fixture.client,
        api_fixture.token_owner_a,
        api_fixture.room_a_id,
        "Keep Adv",
    )
    adv_id = adv["id"]

    entry_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
        json={"kind": "scene", "title": "Keep Entrance"},
        headers=auth_a,
    )
    assert entry_resp.status_code == 201
    entry_id = entry_resp.json()["id"]

    # link asset
    link_resp = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets",
        json={"asset_id": image_id, "role": "image"},
        headers=auth_a,
    )
    assert link_resp.status_code == 200

    # DELETE /api/rooms/{room_a}/assets/{image_id} -> 409 asset_in_use
    del_asset = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/assets/{image_id}",
        headers=auth_a,
    )
    assert del_asset.status_code == 409
    assert del_asset.json()["error"]["code"] == "asset_in_use"

    # unlink
    unlink_resp = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets/{image_id}",
        headers=auth_a,
    )
    assert unlink_resp.status_code == 200

    # DELETE asset -> 204
    del_asset2 = api_fixture.client.delete(
        f"/api/rooms/{api_fixture.room_a_id}/assets/{image_id}",
        headers=auth_a,
    )
    assert del_asset2.status_code == 204


def test_invalid_payload_and_parent_map_to_400(api_fixture: AdventureApiFixture) -> None:
    auth_a = _auth(api_fixture.token_owner_a)

    adv1 = _create_adventure(
        api_fixture.client,
        api_fixture.token_owner_a,
        api_fixture.room_a_id,
        "Adv 1",
    )
    adv1_id = adv1["id"]

    adv2 = _create_adventure(
        api_fixture.client,
        api_fixture.token_owner_a,
        api_fixture.room_a_id,
        "Adv 2",
    )
    adv2_id = adv2["id"]

    entry_adv2 = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv2_id}/entries",
        json={"kind": "section", "title": "Adv 2 Section"},
        headers=auth_a,
    )
    assert entry_adv2.status_code == 201
    entry_adv2_id = entry_adv2.json()["id"]

    # POST entry kind suggested_check with dc 99 -> 400 adventure_entry_payload_invalid
    bad_dc = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv1_id}/entries",
        json={
            "kind": "suggested_check",
            "title": "Impossible Check",
            "data": {"ability": "strength", "dc": 99},
        },
        headers=auth_a,
    )
    assert bad_dc.status_code == 400
    assert bad_dc.json()["error"]["code"] == "adventure_entry_payload_invalid"

    # POST entry with parent_entry_id from another adventure -> 400 adventure_entry_parent_invalid
    bad_parent = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv1_id}/entries",
        json={
            "kind": "scene",
            "title": "Scene with cross-adventure parent",
            "parent_entry_id": entry_adv2_id,
        },
        headers=auth_a,
    )
    assert bad_parent.status_code == 400
    assert bad_parent.json()["error"]["code"] == "adventure_entry_parent_invalid"

    # POST entry kind "trap_grid" -> 422 (FastAPI validation of the Literal)
    bad_kind = api_fixture.client.post(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv1_id}/entries",
        json={"kind": "trap_grid", "title": "Unknown"},
        headers=auth_a,
    )
    assert bad_kind.status_code == 422


def test_entry_list_embeds_assets_without_n_plus_one(
    api_fixture: AdventureApiFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_a = _auth(api_fixture.token_owner_a)

    adv = _create_adventure(
        api_fixture.client,
        api_fixture.token_owner_a,
        api_fixture.room_a_id,
        "N+1 Test Adv",
    )
    adv_id = adv["id"]

    # create 3 entries each with one linked image
    for i in range(3):
        img_resp = _upload_asset(
            api_fixture.client,
            api_fixture.token_owner_a,
            room_id=api_fixture.room_a_id,
            kind="image",
            filename=f"img_{i}.png",
            mime="image/png",
            data=f"image-bytes-{i}".encode(),
            visibility="room",
        )
        assert img_resp.status_code == 201
        asset_id = img_resp.json()["id"]

        entry_resp = api_fixture.client.post(
            f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
            json={"kind": "scene", "title": f"Scene {i}"},
            headers=auth_a,
        )
        assert entry_resp.status_code == 201
        entry_id = entry_resp.json()["id"]

        link_resp = api_fixture.client.post(
            f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries/{entry_id}/assets",
            json={"asset_id": asset_id, "role": "image"},
            headers=auth_a,
        )
        assert link_resp.status_code == 200

    # monkeypatch RoomAssetRepository.list_for_room to count calls
    call_count = 0
    original_list_for_room = RoomAssetRepository.list_for_room

    def _counting_list_for_room(self, room_id, kind=None, *, connection=None):
        nonlocal call_count
        call_count += 1
        return original_list_for_room(self, room_id, kind=kind, connection=connection)

    monkeypatch.setattr(RoomAssetRepository, "list_for_room", _counting_list_for_room)

    # GET entries -> exactly 1 call and each entry has 1 asset
    list_resp = api_fixture.client.get(
        f"/api/rooms/{api_fixture.room_a_id}/adventures/{adv_id}/entries",
        headers=auth_a,
    )
    assert list_resp.status_code == 200
    entries = list_resp.json()
    assert len(entries) == 3
    assert call_count == 1
    for entry in entries:
        assert len(entry["assets"]) == 1
        assert entry["assets"][0]["role"] == "image"
