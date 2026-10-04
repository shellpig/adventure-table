"""M07-B B.2 / B.3: AI read boundary and the three Tactical start sources."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest
from sqlalchemy import func, select, update

from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_combat_service, get_table_event_service
from app.domain.battle_maps.schemas import (
    BattleMapArchivedError,
    BattleMapInvalidError,
    BattleMapReferencedError,
    TemporaryBattleMapInput,
)
from app.domain.battle_maps.service import BattleMapService
from app.domain.combat.ai_tools import BattleMapIdToolInput
from app.domain.combat.lifecycle import StartCombatInput, StartTacticalCombatInput
from app.domain.rooms.ai_controllers import AIControllerUnauthorizedError
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.main import app
from app.mcp.tools import call_tool
from app.persistence.battle_maps.tables import battle_maps
from app.persistence.combat.tables import combats
from app.persistence.combat_boards.tables import combat_boards
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.tables import room_assets
from app.persistence.rooms.tables import ai_controller_grants
from app.persistence.rooms.workspace import RoomWorkspaceRepository
from app.content.registry import load_default_content_registry
from tests.p5a_tactical_helpers import TacticalTable, insert_battle_map, setup_tactical_table
from tests.test_p5f_tactical_mcp import _dm_token, _event_count, _facade, _player_token

TEMPORARY_MAP = {
    "width_cells": 12,
    "height_cells": 10,
    "walls": [
        {"id": str(uuid4()), "x1": 0, "y1": 0, "x2": 4, "y2": 0, "visibility": "public"},
        {"x1": 6, "y1": 6, "x2": 6, "y2": 9, "visibility": "hidden"},
    ],
    "doors": [{"x1": 4, "y1": 0, "x2": 5, "y2": 0, "default_state": "closed", "visibility": "hidden"}],
    "terrain": [{"x": 2, "y": 2, "terrain_kind": "difficult"}],
    "drawings": [{"payload": {"kind": "note", "text": "altar"}}],
}


def _counts(table: TacticalTable) -> tuple[int, int, int, int, int]:
    with table.engine.connect() as connection:
        return (
            int(connection.scalar(select(func.count()).select_from(combats)) or 0),
            int(connection.scalar(select(func.count()).select_from(combat_boards)) or 0),
            int(connection.scalar(select(func.count()).select_from(battle_maps)) or 0),
            int(connection.scalar(select(func.count()).select_from(room_assets)) or 0),
            _event_count(table),
        )


def _owner(table: TacticalTable) -> RoomAccessContext:
    return RoomAccessContext(
        room_id=table.room_id, access_session_id=uuid4(), authority=RoomAccessAuthority.OWNER,
    )


def _maps(table: TacticalTable) -> BattleMapService:
    return BattleMapService(table.battle_maps, RoomAssetRepository(table.engine), table.events,
                             content_registry=load_default_content_registry())


def _archive(table: TacticalTable, map_id) -> None:
    stored = table.battle_maps.get_map(table.room_id, map_id)
    assert stored is not None
    with table.engine.begin() as connection:
        table.battle_maps.archive_map_in_transaction(
            connection, table.room_id, map_id, expected_revision=stored.revision,
        )


def _mcp(table: TacticalTable, token: str, name: str, arguments: dict) -> dict:
    facade = _facade(table)
    return asyncio.run(call_tool(facade, token=token, auth=facade._auth(token), name=name, arguments=arguments))


# --- B.2 temporary map --------------------------------------------------------


def test_temporary_map_freezes_into_the_board_without_library_rows() -> None:
    table = setup_tactical_table()
    combats_before, boards_before, maps_before, assets_before, _ = _counts(table)

    view = table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(temporary_map=TemporaryBattleMapInput(**TEMPORARY_MAP))
    )

    board = table.board.get_board(table.dm_actor)
    assert board is not None and board.combat_id == view.id
    assert (board.width_cells, board.height_cells) == (12, 10)
    assert (board.source_battle_map_id, board.source_battle_map_revision) == (None, None)
    assert board.has_image is False
    assert len(board.walls) == 2 and len(board.doors) == 1
    # Object ids are Server-assigned, never the client's.
    with table.engine.connect() as connection:
        baseline = connection.scalar(select(combat_boards.c.baseline).where(combat_boards.c.combat_id == view.id))
    assert TEMPORARY_MAP["walls"][0]["id"] not in {wall["id"] for wall in baseline["walls"]}
    assert _counts(table)[:4] == (combats_before + 1, boards_before + 1, maps_before, assets_before)
    # The Player projection hides the hidden wall; the hidden door reads as wall.
    player_board = table.board.get_board(table.player_actor)
    assert player_board is not None
    assert (6, 6, 6, 9) not in {(wall.x1, wall.y1, wall.x2, wall.y2) for wall in player_board.walls}
    assert player_board.doors == ()


@pytest.mark.parametrize(
    "payload",
    [
        {"battle_map_id": str(uuid4()), "temporary_map": TEMPORARY_MAP},
        {"blank_width_cells": 10, "blank_height_cells": 10, "temporary_map": TEMPORARY_MAP},
        {"battle_map_id": str(uuid4()), "blank_width_cells": 10, "blank_height_cells": 10},
        {"blank_width_cells": 10},
        {},
    ],
    ids=["map+temporary", "blank+temporary", "map+blank", "half-blank", "none"],
)
def test_start_sources_are_mutually_exclusive(payload: dict) -> None:
    with pytest.raises(ValidationError):
        StartTacticalCombatInput.model_validate(payload)


@pytest.mark.parametrize(
    "objects",
    [
        {"walls": [{"x1": 0, "y1": 0, "x2": 40, "y2": 0, "visibility": "public"}]},
        {"doors": [{"x1": 0, "y1": 0, "x2": 2, "y2": 0, "default_state": "open", "visibility": "public"}]},
        {"terrain": [{"x": 1, "y": 1, "terrain_kind": "difficult"}, {"x": 1, "y": 1, "terrain_kind": "blocked"}]},
        {"drawings": [{"payload": {"blob": "x" * 70_000}}]},
    ],
    ids=["wall-out-of-bounds", "long-door", "duplicate-terrain", "oversize-drawing"],
)
def test_invalid_temporary_geometry_is_rejected_with_zero_side_effects(objects: dict) -> None:
    table = setup_tactical_table()
    before = _counts(table)
    request = StartTacticalCombatInput(
        temporary_map=TemporaryBattleMapInput(width_cells=12, height_cells=10, **objects)
    )
    with pytest.raises(BattleMapInvalidError):
        table.combat.start_tactical_combat(table.dm_actor, request)
    assert _counts(table) == before


def test_temporary_map_retry_returns_one_combat_and_one_board() -> None:
    table = setup_tactical_table()
    request = StartTacticalCombatInput(
        temporary_map=TemporaryBattleMapInput(**TEMPORARY_MAP), idempotency_key="m07b-temp-start",
    )
    first = table.combat.start_tactical_combat(table.dm_actor, request)
    after_first = _counts(table)
    retried = table.combat.start_tactical_combat(table.dm_actor, request)
    assert retried.id == first.id
    assert _counts(table) == after_first


def test_player_cannot_start_a_temporary_map_combat() -> None:
    table = setup_tactical_table()
    before = _counts(table)
    with pytest.raises(TableEventActorUnauthorizedError):
        table.combat.start_tactical_combat(
            table.player_actor, StartTacticalCombatInput(temporary_map=TemporaryBattleMapInput(**TEMPORARY_MAP))
        )
    assert _counts(table) == before


def test_quick_combat_still_needs_no_map() -> None:
    table = setup_tactical_table()
    view = table.combat.start_quick_combat(table.dm_actor, StartCombatInput())
    assert view.mode == "quick"
    assert _counts(table)[1] == 0


# --- B.1 archive / reference protection --------------------------------------


def test_archived_map_cannot_start_combat_but_an_existing_board_keeps_working() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    table.combat.start_tactical_combat(table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id))
    _archive(table, map_id)

    board = table.board.get_board(table.dm_actor)
    assert board is not None and board.source_battle_map_id == map_id

    fresh = setup_tactical_table()
    archived_id = insert_battle_map(fresh)
    _archive(fresh, archived_id)
    before = _counts(fresh)
    with pytest.raises(BattleMapArchivedError):
        fresh.combat.start_tactical_combat(fresh.dm_actor, StartTacticalCombatInput(battle_map_id=archived_id))
    assert _counts(fresh) == before


def test_active_and_ended_boards_block_map_delete() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    table.combat.start_tactical_combat(table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id))
    maps = _maps(table)

    with pytest.raises(BattleMapReferencedError):
        maps.delete(_owner(table), table.room_id, map_id, expected_revision=3)
    table.combat.end_combat(table.dm_actor)
    with pytest.raises(BattleMapReferencedError):
        maps.delete(_owner(table), table.room_id, map_id, expected_revision=3)
    assert table.battle_maps.get_map(table.room_id, map_id) is not None


def test_room_hard_delete_clears_maps_with_historical_boards() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    table.combat.start_tactical_combat(table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id))
    table.combat.end_combat(table.dm_actor)

    RoomWorkspaceRepository(table.engine).hard_delete_room(table.room_id)

    with table.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(battle_maps)) == 0
        assert connection.scalar(select(func.count()).select_from(combat_boards)) == 0


# --- B.2 Human REST and MCP share the Start schema -----------------------------


def test_human_rest_tactical_start_accepts_a_temporary_map() -> None:
    table = setup_tactical_table()
    contexts = {
        "dm": RoomAccessContext(
            room_id=table.room_id, access_session_id=table.dm_actor.access_session_id,
            authority=RoomAccessAuthority.DM,
        ),
        "player": RoomAccessContext(
            room_id=table.room_id, access_session_id=table.player_actor.access_session_id,
            authority=RoomAccessAuthority.OWNER,
        ),
    }
    current = {"who": "player"}
    app.dependency_overrides[get_room_access_context] = lambda: contexts[current["who"]]
    app.dependency_overrides[get_table_event_service] = lambda: table.events
    app.dependency_overrides[get_combat_service] = lambda: table.combat
    url = f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}/sessions/{table.session_id}/combat/tactical-start"
    try:
        client = TestClient(app)
        before = _counts(table)
        assert client.post(url, json={"temporary_map": TEMPORARY_MAP}).status_code == 403
        bad = client.post(url, json={"temporary_map": TEMPORARY_MAP, "blank_width_cells": 5, "blank_height_cells": 5})
        assert bad.status_code == 422
        assert _counts(table) == before

        current["who"] = "dm"
        invalid = client.post(url, json={"temporary_map": {**TEMPORARY_MAP, "terrain": [{"x": 99, "y": 0, "terrain_kind": "difficult"}]}})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "invalid_combat_input"
        assert _counts(table) == before
        started = client.post(url, json={"temporary_map": TEMPORARY_MAP})
        assert started.status_code == 200
        assert started.json()["mode"] == "tactical"
    finally:
        app.dependency_overrides.clear()


def test_mcp_tactical_start_temporary_map_and_bilingual_errors() -> None:
    table = setup_tactical_table()
    token = _dm_token(table)
    before = _counts(table)

    invalid = _mcp(table, token, "combat_start_tactical", {
        "temporary_map": {**TEMPORARY_MAP, "walls": [{"x1": 0, "y1": 0, "x2": 99, "y2": 0, "visibility": "public"}]},
    })
    assert invalid["structuredContent"]["error"]["code"] == "invalid_arguments"
    archived_id = insert_battle_map(table)
    _archive(table, archived_id)
    archived = _mcp(table, token, "combat_start_tactical", {"battle_map_id": str(archived_id)})
    archived_error = archived["structuredContent"]["error"]
    assert archived_error["code"] == "battle_map_archived"
    assert archived_error["messages"]["en"].strip() and archived_error["messages"]["zh-TW"].strip()
    assert _counts(table)[:2] == before[:2]

    started = _mcp(table, token, "combat_start_tactical", {"temporary_map": TEMPORARY_MAP})
    assert started["structuredContent"]["ok"] is True
    board = table.board.get_board(table.dm_actor)
    assert board is not None and board.source_battle_map_id is None


# --- B.2 AI read-only library -------------------------------------------------


def test_ai_dm_reads_maps_of_its_own_room_only() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    _archive(table, insert_battle_map(table))
    other = setup_tactical_table(table.engine)
    other_map = insert_battle_map(other)
    token = _dm_token(table)

    listed = _mcp(table, token, "battle_map_list", {})
    assert [item["id"] for item in listed["structuredContent"]["data"]["battle_maps"]] == [str(map_id)]
    got = _mcp(table, token, "battle_map_get", {"map_id": str(map_id)})
    assert len(got["structuredContent"]["data"]["walls"]) == 2
    foreign = _mcp(table, token, "battle_map_get", {"map_id": str(other_map)})
    assert foreign["structuredContent"]["error"]["code"] == "not_found"


def test_player_and_revoked_grants_cannot_read_maps() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    facade = _facade(table)

    player = _mcp(table, _player_token(table), "battle_map_list", {})
    assert player["structuredContent"]["error"]["code"] == "permission_denied"

    token = _dm_token(table)
    with table.engine.begin() as connection:
        connection.execute(
            update(ai_controller_grants)
            .where(ai_controller_grants.c.seat_id == table.dm_actor.seat_id)
            .values(status="revoked", revoked_at=datetime.now(UTC))
        )
    with pytest.raises(AIControllerUnauthorizedError):
        facade.battle_map_get(token, BattleMapIdToolInput(map_id=map_id))
