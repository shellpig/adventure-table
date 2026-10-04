"""M07-C C2: REST route wiring for tactical start with ``load_map_monsters``."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_combat_service, get_table_event_service
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.main import app
from tests.test_m07c_combat_load import (
    GOBLIN_KEY,
    _create_map,
    _placement,
    _put_placements,
    _table,
)


def _contexts(table):
    return {
        "dm": RoomAccessContext(
            room_id=table.room_id, access_session_id=table.dm_actor.access_session_id,
            authority=RoomAccessAuthority.DM,
        ),
        "player": RoomAccessContext(
            room_id=table.room_id, access_session_id=table.player_actor.access_session_id,
            authority=RoomAccessAuthority.OWNER,
        ),
    }


def _client(table, who: str) -> TestClient:
    contexts = _contexts(table)
    app.dependency_overrides[get_room_access_context] = lambda: contexts[who]
    app.dependency_overrides[get_table_event_service] = lambda: table.events
    app.dependency_overrides[get_combat_service] = lambda: table.combat
    return TestClient(app)


def _url(table) -> str:
    return (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/tactical-start"
    )


def test_rest_load_flag_without_battle_map_is_422() -> None:
    table, _ = _table()
    client = _client(table, "dm")
    try:
        url = _url(table)
        blank = client.post(url, json={
            "blank_width_cells": 10, "blank_height_cells": 8,
            "load_map_monsters": True,
        })
        assert blank.status_code == 422
        temporary = client.post(url, json={
            "temporary_map": {
                "width_cells": 10, "height_cells": 8,
                "walls": [], "doors": [], "terrain": [], "drawings": [],
            },
            "load_map_monsters": True,
        })
        assert temporary.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_rest_player_cannot_start_with_load_flag() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    client = _client(table, "player")
    try:
        response = client.post(_url(table), json={
            "battle_map_id": str(map_id), "load_map_monsters": True,
        })
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_rest_bad_placement_is_409_with_problems() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps, width=10, height=8)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(9, 7)),
    ])
    # Shrink the map geometry via raw edit so the placement is out of bounds
    # at load time.
    from app.persistence.battle_maps.tables import battle_maps as battle_maps_tbl

    with table.engine.begin() as connection:
        connection.execute(
            battle_maps_tbl.update()
            .where(battle_maps_tbl.c.id == map_id)
            .values(width_cells=8, height_cells=6, revision=2)
        )
    client = _client(table, "dm")
    try:
        response = client.post(_url(table), json={
            "battle_map_id": str(map_id), "load_map_monsters": True,
        })
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "map_monster_placement_invalid"
        assert error["params"]["problems"]
    finally:
        app.dependency_overrides.clear()


def test_rest_idempotency_conflict_is_409() -> None:
    table, battle_maps = _table()
    map_id = _create_map(table, battle_maps)
    _put_placements(table, battle_maps, map_id, [
        _placement(template_key=GOBLIN_KEY, anchor=(1, 1)),
    ])
    client = _client(table, "dm")
    try:
        url = _url(table)
        first = client.post(url, json={
            "battle_map_id": str(map_id), "load_map_monsters": True,
            "idempotency_key": "rest-key-1",
        })
        assert first.status_code == 200
        conflict = client.post(url, json={
            "battle_map_id": str(map_id), "load_map_monsters": False,
            "idempotency_key": "rest-key-1",
        })
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "combat_idempotency_conflict"
        retry = client.post(url, json={
            "battle_map_id": str(map_id), "load_map_monsters": True,
            "idempotency_key": "rest-key-1",
        })
        assert retry.status_code == 200
        assert retry.json()["id"] == first.json()["id"]
    finally:
        app.dependency_overrides.clear()
