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
from app.db import metadata
from app.domain.battle_maps.projector import project_battle_map
from app.domain.battle_maps.schemas import BattleMap
from app.domain.battle_maps.service import BattleMapService
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.main import app
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.battle_maps.tables import battle_maps
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.rooms.tables import rooms


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
class BattleMapFixture:
    client: TestClient
    engine: Engine
    room_a_id: UUID
    room_b_id: UUID
    token_owner_a: str
    token_dm_a: str
    token_member_a: str
    token_owner_b: str


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _upload_asset(
    client: TestClient,
    token: str,
    *,
    room_id: UUID,
    kind: str,
    filename: str,
    mime: str,
    data: bytes,
):
    return client.post(
        f"/api/rooms/{room_id}/assets",
        params={"kind": kind, "filename": filename},
        content=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": mime},
    )


def _map_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(battle_maps)) or 0)


def _error_code(resp) -> str:
    return resp.json()["error"]["code"]


@pytest.fixture
def bm_fixture(tmp_path: Path) -> Generator[BattleMapFixture, None, None]:
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
        BattleMapRepository(engine), asset_repository
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
    token_dm_a = "token-dm-a"
    token_member_a = "token-member-a"
    token_owner_b = "token-owner-b"
    token_to_context = {
        token_owner_a: RoomAccessContext(
            room_id=room_a_id, access_session_id=uuid4(),
            authority=RoomAccessAuthority.OWNER, display_name="Owner A",
        ),
        token_dm_a: RoomAccessContext(
            room_id=room_a_id, access_session_id=uuid4(),
            authority=RoomAccessAuthority.DM, display_name="DM A",
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
        for name in ("battle_map_service", "room_asset_service")
    }
    app.state.battle_map_service = battle_map_service
    app.state.room_asset_service = asset_service
    app.dependency_overrides[get_database_engine] = lambda: engine
    app.dependency_overrides[get_room_access_context] = _override_access_context

    client = TestClient(app)
    try:
        yield BattleMapFixture(
            client=client, engine=engine,
            room_a_id=room_a_id, room_b_id=room_b_id,
            token_owner_a=token_owner_a, token_dm_a=token_dm_a,
            token_member_a=token_member_a, token_owner_b=token_owner_b,
        )
    finally:
        for name, value in previous_state.items():
            if value is None:
                app.state._state.pop(name, None)
            else:
                app.state._state[name] = value
        app.dependency_overrides.pop(get_database_engine, None)
        app.dependency_overrides.pop(get_room_access_context, None)


def _create_map(fx: BattleMapFixture, token: str, room_id: UUID, payload: dict) -> object:
    return fx.client.post(
        f"/api/rooms/{room_id}/battle-maps", json=payload, headers=_auth(token)
    )


def _blank_payload(name: str = "Cave") -> dict:
    return {
        "name": name,
        "source_kind": "blank",
        "width_cells": 10,
        "height_cells": 8,
    }


def _objects_payload(expected_revision: int) -> dict:
    return {
        "expected_revision": expected_revision,
        "walls": [
            {"id": str(uuid4()), "x1": 0, "y1": 0, "x2": 5, "y2": 0, "visibility": "public"},
            {"x1": 0, "y1": 1, "x2": 0, "y2": 4, "visibility": "hidden"},
        ],
        "doors": [
            {"id": str(uuid4()), "x1": 2, "y1": 0, "x2": 3, "y2": 0,
             "default_state": "open", "visibility": "public"},
            {"x1": 5, "y1": 1, "x2": 5, "y2": 2,
             "default_state": "locked", "visibility": "public"},
            {"x1": 6, "y1": 2, "x2": 7, "y2": 2,
             "default_state": "broken", "visibility": "hidden"},
            {"x1": 1, "y1": 3, "x2": 2, "y2": 3,
             "default_state": "closed", "visibility": "public"},
        ],
        "terrain": [
            {"x": 3, "y": 3, "terrain_kind": "difficult"},
            {"x": 4, "y": 4, "terrain_kind": "blocked"},
        ],
        "drawings": [
            {"payload": {"kind": "circle", "cx": 2, "cy": 2, "r": 1}},
        ],
    }


# --- create / get / list ----------------------------------------------------


def test_owner_creates_blank_map(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    resp = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Cave"
    assert body["source_kind"] == "blank"
    assert body["image_asset_id"] is None
    assert body["width_cells"] == 10
    assert body["height_cells"] == 8
    assert body["revision"] == 1
    assert body["walls"] == []
    assert body["doors"] == []
    assert body["terrain"] == []
    assert body["drawings"] == []


def test_dm_creates_image_map(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    upload = _upload_asset(
        fx.client, fx.token_owner_a, room_id=fx.room_a_id,
        kind="battle_map_image", filename="map.png",
        mime="image/png", data=b"\x89PNG\r\n\x1a\nmap-bytes",
    )
    assert upload.status_code == 201
    assert upload.json()["kind"] == "battle_map_image"
    asset_id = upload.json()["id"]

    resp = _create_map(
        fx, fx.token_dm_a, fx.room_a_id,
        {
            "name": "Dungeon",
            "source_kind": "image",
            "image_asset_id": asset_id,
            "width_cells": 20,
            "height_cells": 20,
            "grid_pixel_size": 50,
            "grid_offset_x": 2,
            "grid_offset_y": -3,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_kind"] == "image"
    assert body["image_asset_id"] == asset_id
    assert body["grid_pixel_size"] == 50
    assert body["grid_offset_x"] == 2
    assert body["grid_offset_y"] == -3


def test_create_image_with_plain_image_asset_rejected(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    upload = _upload_asset(
        fx.client, fx.token_owner_a, room_id=fx.room_a_id,
        kind="image", filename="portrait.png",
        mime="image/png", data=b"\x89PNG\r\n\x1a\nportrait",
    )
    assert upload.status_code == 201
    before = _map_count(fx.engine)

    resp = _create_map(
        fx, fx.token_owner_a, fx.room_a_id,
        {
            "name": "Bad", "source_kind": "image",
            "image_asset_id": upload.json()["id"],
            "width_cells": 10, "height_cells": 10,
        },
    )
    assert resp.status_code == 400
    assert _error_code(resp) == "battle_map_asset_invalid"
    assert _map_count(fx.engine) == before


def test_create_image_with_other_room_asset_rejected(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    upload = _upload_asset(
        fx.client, fx.token_owner_b, room_id=fx.room_b_id,
        kind="battle_map_image", filename="b.png",
        mime="image/png", data=b"\x89PNG\r\n\x1a\nb",
    )
    assert upload.status_code == 201
    before = _map_count(fx.engine)

    resp = _create_map(
        fx, fx.token_owner_a, fx.room_a_id,
        {
            "name": "Bad", "source_kind": "image",
            "image_asset_id": upload.json()["id"],
            "width_cells": 10, "height_cells": 10,
        },
    )
    assert resp.status_code == 400
    assert _error_code(resp) == "battle_map_asset_invalid"
    assert _map_count(fx.engine) == before


def test_create_image_without_asset_id_rejected(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    resp = _create_map(
        fx, fx.token_owner_a, fx.room_a_id,
        {"name": "Bad", "source_kind": "image", "width_cells": 10, "height_cells": 10},
    )
    assert resp.status_code == 400
    assert _error_code(resp) == "battle_map_invalid"


def test_create_blank_with_grid_fields_rejected(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    payload = _blank_payload()
    payload["grid_pixel_size"] = 50
    resp = _create_map(fx, fx.token_owner_a, fx.room_a_id, payload)
    assert resp.status_code == 400
    assert _error_code(resp) == "battle_map_invalid"


def test_create_with_invalid_dimensions_rejected(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    payload = _blank_payload()
    payload["width_cells"] = 0
    resp = _create_map(fx, fx.token_owner_a, fx.room_a_id, payload)
    assert resp.status_code == 422


def test_get_and_list(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    id1 = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload("One")).json()["id"]
    id2 = _create_map(fx, fx.token_dm_a, fx.room_a_id, _blank_payload("Two")).json()["id"]

    listed = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps", headers=_auth(fx.token_owner_a)
    )
    assert listed.status_code == 200
    assert {m["id"] for m in listed.json()} == {id1, id2}
    assert all("walls" not in m for m in listed.json())

    got = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{id1}", headers=_auth(fx.token_dm_a)
    )
    assert got.status_code == 200
    assert got.json()["id"] == id1
    assert got.json()["name"] == "One"


def test_get_missing_map_is_404(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    resp = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{uuid4()}",
        headers=_auth(fx.token_owner_a),
    )
    assert resp.status_code == 404
    assert _error_code(resp) == "battle_map_not_found"


# --- member authority: 404 on every route, zero side effects -----------------


def test_member_everything_is_404_with_zero_side_effects(
    bm_fixture: BattleMapFixture,
) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload())
    map_id = created.json()["id"]
    member = _auth(fx.token_member_a)

    assert fx.client.post(
        f"/api/rooms/{fx.room_a_id}/battle-maps", json=_blank_payload("M"), headers=member
    ).status_code == 404
    assert fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps", headers=member
    ).status_code == 404
    assert fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}", headers=member
    ).status_code == 404
    assert fx.client.patch(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        json={"name": "Hacked", "expected_revision": 1}, headers=member,
    ).status_code == 404
    assert fx.client.put(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}/objects",
        json=_objects_payload(1), headers=member,
    ).status_code == 404
    assert fx.client.delete(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}", headers=member
    ).status_code == 404

    # Zero side effects: the map is untouched and nothing new exists.
    after = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        headers=_auth(fx.token_owner_a),
    )
    assert after.status_code == 200
    assert after.json()["name"] == "Cave"
    assert after.json()["revision"] == 1
    assert _map_count(fx.engine) == 1


# --- cross-room isolation -----------------------------------------------------


def test_cross_room_map_access_is_404(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload())
    map_id = created.json()["id"]
    owner_b = _auth(fx.token_owner_b)

    assert fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}", headers=owner_b
    ).status_code == 404
    assert fx.client.patch(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        json={"name": "Hacked", "expected_revision": 1}, headers=owner_b,
    ).status_code == 404
    assert fx.client.put(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}/objects",
        json=_objects_payload(1), headers=owner_b,
    ).status_code == 404
    assert fx.client.delete(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}", headers=owner_b
    ).status_code == 404

    # Room B context must not see the Room A map either (room mismatch -> 404).
    listed_b = fx.client.get(
        f"/api/rooms/{fx.room_b_id}/battle-maps", headers=owner_b
    )
    assert listed_b.status_code == 200
    assert listed_b.json() == []

    after = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        headers=_auth(fx.token_owner_a),
    )
    assert after.json()["name"] == "Cave"
    assert after.json()["revision"] == 1


# --- patch ------------------------------------------------------------------


def test_patch_rename_and_resize(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    map_id = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()["id"]

    resp = fx.client.patch(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        json={"name": "Deep Cave", "width_cells": 12, "expected_revision": 1},
        headers=_auth(fx.token_dm_a),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Deep Cave"
    assert body["width_cells"] == 12
    assert body["revision"] == 2


def test_patch_revision_conflict(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    map_id = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()["id"]

    resp = fx.client.patch(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        json={"name": "Stale", "expected_revision": 999},
        headers=_auth(fx.token_owner_a),
    )
    assert resp.status_code == 409
    assert _error_code(resp) == "battle_map_revision_conflict"

    after = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        headers=_auth(fx.token_owner_a),
    )
    assert after.json()["name"] == "Cave"
    assert after.json()["revision"] == 1


def test_patch_shrink_with_out_of_bounds_objects_is_409(
    bm_fixture: BattleMapFixture,
) -> None:
    fx = bm_fixture
    map_id = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()["id"]
    put = fx.client.put(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}/objects",
        json={
            "expected_revision": 1,
            "walls": [{"x1": 8, "y1": 0, "x2": 10, "y2": 0, "visibility": "public"}],
            "terrain": [{"x": 9, "y": 7, "terrain_kind": "difficult"}],
        },
        headers=_auth(fx.token_owner_a),
    )
    assert put.status_code == 200
    assert put.json()["revision"] == 2

    resp = fx.client.patch(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        json={"width_cells": 5, "expected_revision": 2},
        headers=_auth(fx.token_owner_a),
    )
    assert resp.status_code == 409
    assert _error_code(resp) == "battle_map_revision_conflict"

    after = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        headers=_auth(fx.token_owner_a),
    )
    assert after.json()["width_cells"] == 10
    assert after.json()["revision"] == 2


def test_patch_explicit_null_is_400(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    map_id = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()["id"]
    resp = fx.client.patch(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        json={"name": None, "expected_revision": 1},
        headers=_auth(fx.token_owner_a),
    )
    assert resp.status_code == 422


def test_patch_blank_map_grid_fields_rejected(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    map_id = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()["id"]
    resp = fx.client.patch(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        json={"grid_pixel_size": 50, "expected_revision": 1},
        headers=_auth(fx.token_owner_a),
    )
    assert resp.status_code == 400
    assert _error_code(resp) == "battle_map_invalid"


# --- replace objects ---------------------------------------------------------


def test_put_objects_roundtrip_with_id_retention(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    map_id = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()["id"]
    payload = _objects_payload(1)
    kept_wall_id = payload["walls"][0]["id"]
    kept_door_id = payload["doors"][0]["id"]

    resp = fx.client.put(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}/objects",
        json=payload, headers=_auth(fx.token_owner_a),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["revision"] == 2
    assert len(body["walls"]) == 2
    assert len(body["doors"]) == 4
    assert len(body["terrain"]) == 2
    assert len(body["drawings"]) == 1
    # Client-supplied ids are retained; server generates the rest.
    assert kept_wall_id in {w["id"] for w in body["walls"]}
    assert kept_door_id in {d["id"] for d in body["doors"]}
    assert {d["default_state"] for d in body["doors"]} == {"open", "closed", "locked", "broken"}
    assert {t["terrain_kind"] for t in body["terrain"]} == {"difficult", "blocked"}
    assert body["drawings"][0]["payload"] == {"kind": "circle", "cx": 2, "cy": 2, "r": 1}

    # Second PUT replaces everything atomically.
    resp2 = fx.client.put(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}/objects",
        json={"expected_revision": 2, "walls": [], "doors": [], "terrain": [], "drawings": []},
        headers=_auth(fx.token_owner_a),
    )
    assert resp2.status_code == 200
    assert resp2.json()["revision"] == 3
    assert resp2.json()["walls"] == []
    assert resp2.json()["doors"] == []
    assert resp2.json()["terrain"] == []
    assert resp2.json()["drawings"] == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["walls"].append({"x1": 0, "y1": 0, "x2": 2, "y2": 2, "visibility": "public"}),  # diagonal
        lambda p: p["walls"].append({"x1": 3, "y1": 3, "x2": 3, "y2": 3, "visibility": "public"}),  # zero length
        lambda p: p["walls"].append({"x1": 0, "y1": 0, "x2": 11, "y2": 0, "visibility": "public"}),  # out of bounds
        lambda p: p["doors"].append({"x1": 0, "y1": 5, "x2": 2, "y2": 5, "default_state": "open", "visibility": "public"}),  # door length 2
        lambda p: p["doors"].append({"x1": 0, "y1": 0, "x2": 1, "y2": 1, "default_state": "open", "visibility": "public"}),  # diagonal door
        lambda p: p["terrain"].append({"x": 10, "y": 0, "terrain_kind": "difficult"}),  # cell out of bounds
        lambda p: p["terrain"].append({"x": 3, "y": 3, "terrain_kind": "blocked"}),  # duplicate cell
        lambda p: p["drawings"].append({"payload": {"kind": "blob", "data": "x" * (64 * 1024 + 1)}}),  # oversize drawing
    ],
    ids=[
        "diagonal-wall", "zero-length-wall", "wall-out-of-bounds",
        "door-length-2", "diagonal-door", "terrain-out-of-bounds",
        "duplicate-terrain-cell", "oversize-drawing",
    ],
)
def test_put_objects_invalid_geometry_is_400_and_atomic(
    bm_fixture: BattleMapFixture, mutate,
) -> None:
    fx = bm_fixture
    map_id = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()["id"]
    baseline = _objects_payload(1)
    put = fx.client.put(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}/objects",
        json=baseline, headers=_auth(fx.token_owner_a),
    )
    assert put.status_code == 200

    bad = _objects_payload(2)
    mutate(bad)
    resp = fx.client.put(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}/objects",
        json=bad, headers=_auth(fx.token_owner_a),
    )
    assert resp.status_code == 400
    assert _error_code(resp) == "battle_map_invalid"

    # Atomic: the earlier objects are untouched.
    after = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        headers=_auth(fx.token_owner_a),
    )
    assert after.json()["revision"] == 2
    assert len(after.json()["walls"]) == 2
    assert len(after.json()["doors"]) == 4


def test_put_objects_revision_conflict_is_409(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    map_id = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()["id"]
    payload = _objects_payload(999)
    resp = fx.client.put(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}/objects",
        json=payload, headers=_auth(fx.token_owner_a),
    )
    assert resp.status_code == 409
    assert _error_code(resp) == "battle_map_revision_conflict"

    after = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        headers=_auth(fx.token_owner_a),
    )
    assert after.json()["revision"] == 1
    assert after.json()["walls"] == []


# --- delete ------------------------------------------------------------------


def test_delete_map(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    map_id = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()["id"]
    assert _map_count(fx.engine) == 1

    resp = fx.client.delete(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        headers=_auth(fx.token_dm_a),
    )
    assert resp.status_code == 204
    assert _map_count(fx.engine) == 0

    got = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}",
        headers=_auth(fx.token_owner_a),
    )
    assert got.status_code == 404
    assert _error_code(got) == "battle_map_not_found"

    listed = fx.client.get(
        f"/api/rooms/{fx.room_a_id}/battle-maps", headers=_auth(fx.token_owner_a)
    )
    assert listed.json() == []


# --- projector secrecy --------------------------------------------------------


def test_player_projection_omits_hidden_geometry(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    map_id = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()["id"]
    hidden_wall_id = str(uuid4())
    hidden_door_id = str(uuid4())
    public_door_id = str(uuid4())
    payload = {
        "expected_revision": 1,
        "walls": [
            {"x1": 0, "y1": 0, "x2": 5, "y2": 0, "visibility": "public"},
            {"id": hidden_wall_id, "x1": 1, "y1": 6, "x2": 4, "y2": 6, "visibility": "hidden"},
        ],
        "doors": [
            {"id": public_door_id, "x1": 2, "y1": 0, "x2": 3, "y2": 0,
             "default_state": "locked", "visibility": "public"},
            {"id": hidden_door_id, "x1": 7, "y1": 7, "x2": 8, "y2": 7,
             "default_state": "broken", "visibility": "hidden"},
        ],
        "terrain": [{"x": 3, "y": 3, "terrain_kind": "difficult"}],
        "drawings": [{"payload": {"kind": "arrow"}}],
    }
    put = fx.client.put(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}/objects",
        json=payload, headers=_auth(fx.token_owner_a),
    )
    assert put.status_code == 200

    definition = BattleMap.model_validate(put.json())
    player_view = project_battle_map(definition, "player")
    dumped = player_view.model_dump_json()

    # Hidden wall is fully omitted; hidden door becomes a plain wall segment.
    assert hidden_wall_id not in dumped
    assert hidden_door_id not in dumped
    assert public_door_id in dumped

    walls = player_view.walls
    assert len(walls) == 2
    # Player walls have no id field at all.
    assert "id" not in type(walls[0]).model_fields
    assert {(w.x1, w.y1, w.x2, w.y2) for w in walls} == {
        (0, 0, 5, 0),   # the public wall
        (7, 7, 8, 7),   # the hidden door, projected as a wall
    }
    # Serialized walls carry coordinates only: no id, no state, no visibility.
    for wall in walls:
        assert set(wall.model_dump(exclude_none=True).keys()) == {
            "x1", "y1", "x2", "y2",
        }
    walls_dumped = "[" + ",".join(
        w.model_dump_json(exclude_none=True) for w in walls
    ) + "]"
    assert "hidden" not in walls_dumped
    assert "state" not in walls_dumped
    assert "visibility" not in walls_dumped

    doors = player_view.doors
    assert len(doors) == 1
    assert doors[0].id == UUID(public_door_id)
    assert doors[0].state == "locked"

    # Terrain and drawings pass through untouched.
    assert len(player_view.terrain) == 1
    assert len(player_view.drawings) == 1


def test_dm_projection_returns_full_definition(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    map_id = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()["id"]
    put = fx.client.put(
        f"/api/rooms/{fx.room_a_id}/battle-maps/{map_id}/objects",
        json=_objects_payload(1), headers=_auth(fx.token_owner_a),
    )
    definition = BattleMap.model_validate(put.json())
    assert project_battle_map(definition, "dm") is definition
