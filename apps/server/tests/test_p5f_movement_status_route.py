"""P5-F F4: read-only movement status route for the Tactical UI.

The UI needs the current pending-movement revision after reaction windows
resolve (the revision the confirm response carried is stale by then). The
route exposes ``MovementService.movement_status`` to the mover's controller
and the DM only.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.dependencies import get_database_engine
from app.api.rooms.access import get_room_access_context
from app.api.rooms.dependencies import get_movement_service, get_table_event_service
from app.domain.combat.movement import MovementService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.main import app
from test_p5f_tactical_mcp import _running_table


def _client_for(table, actor, authority: RoomAccessAuthority) -> tuple[TestClient, str]:
    service = MovementService(
        board_repository=table.board.board_repository,
        board_service=table.board,
        combat_service=table.combat,
    )
    app.dependency_overrides[get_database_engine] = lambda: table.engine
    app.dependency_overrides[get_movement_service] = lambda: service
    app.dependency_overrides[get_table_event_service] = lambda: table.events
    app.dependency_overrides[get_room_access_context] = lambda: RoomAccessContext(
        room_id=table.room_id,
        access_session_id=actor.access_session_id,
        authority=authority,
    )
    base = (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/board/movement"
    )
    return TestClient(app), base


def test_player_reads_own_movement_status() -> None:
    table, char_entry, _ = _running_table()
    try:
        client, base = _client_for(table, table.player_actor, RoomAccessAuthority.MEMBER)
        response = client.get(f"{base}/{char_entry}/status")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entry_id"] == str(char_entry)
    assert (body["used_feet"], body["remaining_feet"], body["budget_feet"]) == (0, 30, 30)
    assert body["has_pending_movement"] is False
    assert body["pending_revision"] == 0


def test_player_cannot_read_monster_movement_status() -> None:
    table, _, monster_entry = _running_table()
    try:
        client, base = _client_for(table, table.player_actor, RoomAccessAuthority.MEMBER)
        response = client.get(f"{base}/{monster_entry}/status")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403, response.text


def test_dm_reads_monster_movement_status() -> None:
    table, _, monster_entry = _running_table()
    try:
        client, base = _client_for(table, table.dm_actor, RoomAccessAuthority.OWNER)
        response = client.get(f"{base}/{monster_entry}/status")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    assert response.json()["entry_id"] == str(monster_entry)
