"""M07-B B.1 / B.3: Room map library lifecycle over the Human REST routes."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine

from app.api.rooms.dependencies import get_battle_map_service
from app.domain.battle_maps.service import BattleMapService
from app.domain.rooms.table_events import TableEventService
from app.main import app
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.tables import room_assets
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import campaign_seats
from app.content.registry import load_default_content_registry
from tests.test_m07a_authorization_and_mcp import AuthFixture, auth_fixture  # noqa: F401
from tests.test_p5a_battle_maps import (  # noqa: F401
    BattleMapFixture,
    _auth,
    _blank_payload,
    _create_map,
    _error_code,
    _map_count,
    _objects_payload,
    _upload_asset,
    bm_fixture,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\nm07b-map"


def _maps_url(room_id: UUID, suffix: str = "") -> str:
    return f"/api/rooms/{room_id}/battle-maps{suffix}"


def _asset_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.scalar(select(func.count()).select_from(room_assets)) or 0)


def _map_with_objects(fx: BattleMapFixture) -> dict:
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload())
    assert created.status_code == 201
    put = fx.client.put(
        _maps_url(fx.room_a_id, f"/{created.json()['id']}/objects"),
        json=_objects_payload(1), headers=_auth(fx.token_owner_a),
    )
    assert put.status_code == 200
    return put.json()


def _library_state(fx: BattleMapFixture) -> list[dict]:
    listed = fx.client.get(
        _maps_url(fx.room_a_id), params={"include_archived": True}, headers=_auth(fx.token_owner_a)
    )
    assert listed.status_code == 200
    return [
        fx.client.get(_maps_url(fx.room_a_id, f"/{item['id']}"), headers=_auth(fx.token_owner_a)).json()
        for item in listed.json()
    ]


def _geometry(body: dict) -> dict:
    """Object geometry without ids; rows are ordered by id, so compare sorted."""
    return {
        "walls": sorted((w["x1"], w["y1"], w["x2"], w["y2"], w["visibility"]) for w in body["walls"]),
        "doors": sorted(
            (d["x1"], d["y1"], d["x2"], d["y2"], d["default_state"], d["visibility"]) for d in body["doors"]
        ),
        "terrain": sorted((t["x"], t["y"], t["terrain_kind"]) for t in body["terrain"]),
        "drawings": sorted(json.dumps(d["payload"], sort_keys=True) for d in body["drawings"]),
    }


def _object_ids(body: dict) -> set[str]:
    return {item["id"] for key in ("walls", "doors", "drawings") for item in body[key]}


def test_room_rest_create_edit_reopen_without_session(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    edited = _map_with_objects(fx)
    reopened = fx.client.get(_maps_url(fx.room_a_id, f"/{edited['id']}"), headers=_auth(fx.token_dm_a))
    assert reopened.status_code == 200
    assert reopened.json()["revision"] == 2
    assert reopened.json()["archived_at"] is None
    assert _geometry(reopened.json()) == _geometry(edited)


def test_copy_gets_new_identity_and_object_ids_sharing_the_image(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    asset_id = _upload_asset(
        fx.client, fx.token_owner_a, room_id=fx.room_a_id, kind="battle_map_image",
        filename="map.png", mime="image/png", data=PNG_BYTES,
    ).json()["id"]
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, {
        "name": "Crypt", "source_kind": "image", "image_asset_id": asset_id,
        "width_cells": 10, "height_cells": 8, "grid_pixel_size": 50,
    }).json()
    source = fx.client.put(
        _maps_url(fx.room_a_id, f"/{created['id']}/objects"),
        json=_objects_payload(1), headers=_auth(fx.token_owner_a),
    ).json()
    assets_before = _asset_count(fx.engine)

    copied = fx.client.post(
        _maps_url(fx.room_a_id, f"/{source['id']}/copy"),
        json={"expected_revision": source["revision"]}, headers=_auth(fx.token_dm_a),
    )

    assert copied.status_code == 201
    body = copied.json()
    assert body["id"] != source["id"]
    assert body["name"] == "Crypt (Copy)"
    assert (body["revision"], body["archived_at"]) == (1, None)
    assert body["image_asset_id"] == asset_id
    assert _geometry(body) == _geometry(source)
    assert _object_ids(body).isdisjoint(_object_ids(source))
    assert _asset_count(fx.engine) == assets_before

    # The copy is independent: editing it leaves the source untouched.
    fx.client.put(
        _maps_url(fx.room_a_id, f"/{body['id']}/objects"),
        json={"expected_revision": 1, "walls": [], "doors": [], "terrain": [], "drawings": []},
        headers=_auth(fx.token_owner_a),
    )
    reread = fx.client.get(_maps_url(fx.room_a_id, f"/{source['id']}"), headers=_auth(fx.token_owner_a)).json()
    assert reread["revision"] == source["revision"]
    assert _geometry(reread) == _geometry(source)
    assert _object_ids(reread) == _object_ids(source)


def test_copy_accepts_a_name(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    source = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    copied = fx.client.post(
        _maps_url(fx.room_a_id, f"/{source['id']}/copy"),
        json={"expected_revision": 1, "name": "  Cave B  "}, headers=_auth(fx.token_owner_a),
    )
    assert copied.status_code == 201
    assert copied.json()["name"] == "Cave B"


def test_archive_hides_from_default_list_but_stays_readable_and_copyable(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    kept = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload("Kept")).json()
    source = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload("Old")).json()

    archived = fx.client.post(
        _maps_url(fx.room_a_id, f"/{source['id']}/archive"),
        json={"expected_revision": 1}, headers=_auth(fx.token_owner_a),
    )
    assert archived.status_code == 200
    assert archived.json()["revision"] == 2
    assert archived.json()["archived_at"] is not None

    default_list = fx.client.get(_maps_url(fx.room_a_id), headers=_auth(fx.token_owner_a)).json()
    assert [item["id"] for item in default_list] == [kept["id"]]
    full_list = fx.client.get(
        _maps_url(fx.room_a_id), params={"include_archived": True}, headers=_auth(fx.token_owner_a)
    ).json()
    assert {item["id"] for item in full_list} == {kept["id"], source["id"]}

    assert fx.client.get(_maps_url(fx.room_a_id, f"/{source['id']}"), headers=_auth(fx.token_dm_a)).status_code == 200
    copied = fx.client.post(
        _maps_url(fx.room_a_id, f"/{source['id']}/copy"),
        json={"expected_revision": 2}, headers=_auth(fx.token_dm_a),
    )
    assert copied.status_code == 201
    assert copied.json()["archived_at"] is None


def test_stale_revision_is_409_with_zero_side_effects(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    edited = _map_with_objects(fx)
    before = _library_state(fx)
    headers = _auth(fx.token_owner_a)
    stale = {"expected_revision": 1}

    responses = [
        fx.client.post(_maps_url(fx.room_a_id, f"/{edited['id']}/copy"), json=stale, headers=headers),
        fx.client.post(_maps_url(fx.room_a_id, f"/{edited['id']}/archive"), json=stale, headers=headers),
        fx.client.patch(_maps_url(fx.room_a_id, f"/{edited['id']}"), json={**stale, "name": "X"}, headers=headers),
        fx.client.delete(_maps_url(fx.room_a_id, f"/{edited['id']}"), params=stale, headers=headers),
    ]

    for response in responses:
        assert response.status_code == 409
        assert _error_code(response) == "battle_map_revision_conflict"
    assert _library_state(fx) == before


def test_delete_requires_revision_and_removes_an_unreferenced_map(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()

    missing_revision = fx.client.delete(_maps_url(fx.room_a_id, f"/{created['id']}"), headers=_auth(fx.token_owner_a))
    assert missing_revision.status_code == 422
    assert _map_count(fx.engine) == 1

    deleted = fx.client.delete(
        _maps_url(fx.room_a_id, f"/{created['id']}"), params={"expected_revision": 1}, headers=_auth(fx.token_owner_a)
    )
    assert deleted.status_code == 204
    assert _map_count(fx.engine) == 0


def test_member_and_other_room_cannot_copy_or_archive(bm_fixture: BattleMapFixture) -> None:
    fx = bm_fixture
    created = _create_map(fx, fx.token_owner_a, fx.room_a_id, _blank_payload()).json()
    before = _library_state(fx)

    for token in (fx.token_member_a, fx.token_owner_b):
        for action in ("copy", "archive"):
            response = fx.client.post(
                _maps_url(fx.room_a_id, f"/{created['id']}/{action}"),
                json={"expected_revision": 1}, headers=_auth(token),
            )
            assert response.status_code == 404
    assert _library_state(fx) == before


def _attach_battle_maps(fix: AuthFixture) -> None:
    service = BattleMapService(
        BattleMapRepository(fix.engine), RoomAssetRepository(fix.engine),
        TableEventService(TableEventRepository(fix.engine)),
        content_registry=load_default_content_registry(),
    )
    app.dependency_overrides[get_battle_map_service] = lambda: service


def test_room_authority_not_seat_role_decides_map_authoring(auth_fixture: AuthFixture) -> None:  # noqa: F811
    fix = auth_fixture
    _attach_battle_maps(fix)

    # The Room Owner controls a Player Seat today and still authors maps.
    owner_created = fix.client.post(
        _maps_url(fix.room_id), json=_blank_payload("Owner map"), headers=_auth(fix.owner_token)
    )
    assert owner_created.status_code == 201

    # A Member controlling the DM Seat has no Room DM authority.
    with fix.engine.begin() as connection:
        connection.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == fix.dm_seat_id)
            .values(controller_access_session_id=fix.member_context.access_session_id)
        )
    member_created = fix.client.post(
        _maps_url(fix.room_id), json=_blank_payload("Seat only"), headers=_auth(fix.member_token)
    )
    assert member_created.status_code == 404
    listed = fix.client.get(_maps_url(fix.room_id), headers=_auth(fix.owner_token)).json()
    assert [item["name"] for item in listed] == ["Owner map"]
