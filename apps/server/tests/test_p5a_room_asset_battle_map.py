from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
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
from app.content import load_default_content_registry
from app.db import metadata
from app.domain.battle_maps.service import BattleMapService
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventService
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.main import app
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.battle_maps.tables import (
    battle_map_doors,
    battle_map_drawings,
    battle_map_terrain,
    battle_map_walls,
    battle_maps,
)
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.room_assets.tables import room_assets
from app.persistence.rooms.tables import rooms
from app.persistence.rooms.table_runtime import TableEventRepository


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
class AssetBattleMapFixture:
    client: TestClient
    engine: Engine
    storage: FilesystemAssetStorage
    tmp_path: Path
    room_a_id: UUID
    room_b_id: UUID
    token_owner_a: str
    token_member_a: str
    token_owner_b: str


@pytest.fixture
def ab_fixture(tmp_path: Path) -> Generator[AssetBattleMapFixture, None, None]:
    engine = _engine()
    storage = FilesystemAssetStorage(tmp_path)
    asset_repository = RoomAssetRepository(engine)
    asset_service = RoomAssetService(
        asset_repository,
        storage,
        max_image_bytes=20 * 1024 * 1024,
        max_source_document_bytes=20 * 1024 * 1024,
    )
    battle_map_service = BattleMapService(
        BattleMapRepository(engine),
        asset_repository,
        TableEventService(TableEventRepository(engine)),
        content_registry=load_default_content_registry(),
    )

    room_a_id = uuid4()
    room_b_id = uuid4()
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            insert(rooms).values(
                id=room_a_id, code="ROOMA", name="Room A",
                password_salt=b"salt", password_hash=b"pw",
                owner_key_hash=b"owner", dm_key_hash=b"dm",
                created_at=now, updated_at=now,
            )
        )
        conn.execute(
            insert(rooms).values(
                id=room_b_id, code="ROOMB", name="Room B",
                password_salt=b"salt", password_hash=b"pw",
                owner_key_hash=b"owner", dm_key_hash=b"dm",
                created_at=now, updated_at=now,
            )
        )

    token_owner_a = "token-owner-a"
    token_member_a = "token-member-a"
    token_owner_b = "token-owner-b"
    token_to_context = {
        token_owner_a: RoomAccessContext(
            room_id=room_a_id, access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER, display_name="Owner A",
        ),
        token_member_a: RoomAccessContext(
            room_id=room_a_id, access_session_id=uuid4(),
            authority=RoomAccessAuthority.MEMBER, display_name="Member A",
        ),
        token_owner_b: RoomAccessContext(
            room_id=room_b_id, access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER, display_name="Owner B",
        ),
    }

    def _override_access_context(request: Request) -> RoomAccessContext:
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        token_clean = token.strip()
        if token_clean in token_to_context:
            return token_to_context[token_clean]
        raise APIError(401, "room_access_required", "Room access token is required")

    previous_state = {
        name: app.state._state.get(name)
        for name in (
            "battle_map_service",
            "room_asset_service",
            "room_workspace_service",
            "character_engine",
        )
    }
    app.state.battle_map_service = battle_map_service
    app.state.room_asset_service = asset_service
    app.state.room_workspace_service = RoomCharacterWorkspaceService(
        engine, load_default_content_registry()
    )
    app.state.character_engine = engine
    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_room_access_context] = _override_access_context

    client = TestClient(app)
    try:
        yield AssetBattleMapFixture(
            client=client, engine=engine, storage=storage, tmp_path=tmp_path,
            room_a_id=room_a_id, room_b_id=room_b_id,
            token_owner_a=token_owner_a, token_member_a=token_member_a,
            token_owner_b=token_owner_b,
        )
    finally:
        for name, value in previous_state.items():
            if value is None:
                app.state._state.pop(name, None)
            else:
                app.state._state[name] = value
        app.dependency_overrides.pop(get_database_engine, None)
        app.dependency_overrides.pop(get_room_access_context, None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


PNG_BYTES = b"\x89PNG\r\n\x1a\nbattle-map-image"


def _upload(
    fx: AssetBattleMapFixture,
    token: str,
    kind: str,
    mime: str,
    data: bytes,
    room_id: UUID | None = None,
):
    return fx.client.post(
        f"/api/rooms/{room_id or fx.room_a_id}/assets",
        params={"kind": kind, "filename": "map.png"},
        content=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": mime},
    )


def _asset_rows(fx: AssetBattleMapFixture) -> int:
    with fx.engine.connect() as conn:
        return int(conn.scalar(select(func.count()).select_from(room_assets)) or 0)


def _files(fx: AssetBattleMapFixture) -> list[Path]:
    return [f for f in fx.tmp_path.rglob("*") if f.is_file()]


# --- upload ------------------------------------------------------------------


def test_upload_battle_map_image_ok(ab_fixture: AssetBattleMapFixture) -> None:
    fx = ab_fixture
    resp = _upload(fx, fx.token_owner_a, kind="battle_map_image", mime="image/png", data=PNG_BYTES)
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "battle_map_image"
    assert body["mime_type"] == "image/png"
    assert body["size_bytes"] == len(PNG_BYTES)
    asset_path = fx.tmp_path / str(fx.room_a_id) / f"{body['id']}.png"
    assert asset_path.is_file()
    assert asset_path.read_bytes() == PNG_BYTES


def test_upload_battle_map_image_rejects_non_image_mime(
    ab_fixture: AssetBattleMapFixture,
) -> None:
    fx = ab_fixture
    resp = _upload(
        fx, fx.token_owner_a, kind="battle_map_image",
        mime="text/plain", data=b"not an image",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "asset_media_type_not_supported"
    assert _asset_rows(fx) == 0
    assert _files(fx) == []


def test_upload_battle_map_image_size_limit_no_orphan(
    ab_fixture: AssetBattleMapFixture,
) -> None:
    fx = ab_fixture
    app.state.room_asset_service = RoomAssetService(
        RoomAssetRepository(fx.engine),
        fx.storage,
        max_image_bytes=64,
        max_source_document_bytes=64,
    )
    resp = _upload(
        fx, fx.token_owner_a, kind="battle_map_image",
        mime="image/png", data=b"\x89PNG\r\n\x1a\n" + b"x" * 64,
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "asset_too_large"
    assert _asset_rows(fx) == 0
    assert _files(fx) == []


# --- referenced asset protection ----------------------------------------------


def _create_image_map(fx: AssetBattleMapFixture, asset_id: str) -> str:
    resp = fx.client.post(
        f"/api/rooms/{fx.room_a_id}/battle-maps",
        json={
            "name": "Ref Map", "source_kind": "image", "image_asset_id": asset_id,
            "width_cells": 10, "height_cells": 10,
        },
        headers=_auth(fx.token_owner_a),
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def test_referenced_battle_map_image_cannot_be_deleted(
    ab_fixture: AssetBattleMapFixture,
) -> None:
    fx = ab_fixture
    asset_id = _upload(
        fx, fx.token_owner_a, kind="battle_map_image", mime="image/png", data=PNG_BYTES
    ).json()["id"]
    _create_image_map(fx, asset_id)

    resp = fx.client.delete(
        f"/api/rooms/{fx.room_a_id}/assets/{asset_id}", headers=_auth(fx.token_owner_a)
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "asset_in_use"

    listed = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/assets", headers=_auth(fx.token_owner_a)
    )
    assert listed.status_code == 200
    assert asset_id in {a["id"] for a in listed.json()}


def test_unreferenced_battle_map_image_can_be_deleted(
    ab_fixture: AssetBattleMapFixture,
) -> None:
    fx = ab_fixture
    body = _upload(
        fx, fx.token_owner_a, kind="battle_map_image", mime="image/png", data=PNG_BYTES
    ).json()
    asset_id = body["id"]
    assert (fx.tmp_path / str(fx.room_a_id) / f"{asset_id}.png").is_file()

    resp = fx.client.delete(
        f"/api/rooms/{fx.room_a_id}/assets/{asset_id}", headers=_auth(fx.token_owner_a)
    )
    assert resp.status_code == 204
    assert _asset_rows(fx) == 0


# --- hard delete ----------------------------------------------------------------


def test_room_hard_delete_removes_battle_maps_and_asset_files(
    ab_fixture: AssetBattleMapFixture,
) -> None:
    fx = ab_fixture
    asset_id = _upload(
        fx, fx.token_owner_a, kind="battle_map_image", mime="image/png", data=PNG_BYTES
    ).json()["id"]
    map_id = _create_image_map(fx, asset_id)
    put = fx.client.put(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}/objects",
        json={
            "expected_revision": 1,
            "walls": [{"x1": 0, "y1": 0, "x2": 3, "y2": 0, "visibility": "public"}],
            "doors": [],
            "terrain": [{"x": 1, "y": 1, "terrain_kind": "difficult"}],
            "drawings": [{"payload": {"kind": "x"}}],
        },
        headers=_auth(fx.token_owner_a),
    )
    assert put.status_code == 200

    # Room B control group: its map must survive Room A's hard delete.
    b_asset_id = _upload(
        fx, fx.token_owner_b, kind="battle_map_image", mime="image/png",
        data=PNG_BYTES, room_id=fx.room_b_id,
    ).json()["id"]
    b_map_resp = fx.client.post(
        f"/api/rooms/{fx.room_b_id}/battle-maps",
        json={
            "name": "B Map", "source_kind": "image", "image_asset_id": b_asset_id,
            "width_cells": 10, "height_cells": 10,
        },
        headers=_auth(fx.token_owner_b),
    )
    assert b_map_resp.status_code == 201
    b_map_id = b_map_resp.json()["id"]

    resp = fx.client.delete(
        f"/api/rooms/{fx.room_a_id}", headers=_auth(fx.token_owner_a)
    )
    assert resp.status_code == 204

    with fx.engine.connect() as conn:
        map_uuid = UUID(map_id)
        b_map_uuid = UUID(b_map_id)
        for table in (
            battle_map_walls, battle_map_doors,
            battle_map_terrain, battle_map_drawings,
        ):
            count = conn.scalar(
                select(func.count()).select_from(table).where(
                    table.c.battle_map_id == map_uuid
                )
            )
            assert count == 0
        assert conn.scalar(
            select(func.count()).select_from(battle_maps).where(
                battle_maps.c.id == map_uuid
            )
        ) == 0
        remaining_assets = conn.scalar(
            select(func.count()).select_from(room_assets).where(
                room_assets.c.room_id == fx.room_a_id
            )
        )
        assert remaining_assets == 0
        assert conn.scalar(
            select(func.count()).select_from(battle_maps).where(
                battle_maps.c.id == b_map_uuid
            )
        ) == 1

    # Room A asset file is gone; Room B files remain.
    assert not (fx.tmp_path / str(fx.room_a_id) / f"{asset_id}.png").exists()
    assert (fx.tmp_path / str(fx.room_b_id) / f"{b_asset_id}.png").is_file()
