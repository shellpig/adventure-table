"""P5-A B3: tactical start — blank/map board freeze, idempotency, quick isolation."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.battle_maps.schemas import BattleMapNotFoundError
from app.domain.combat.lifecycle import (
    ActiveCombatExistsError,
    CombatStateConflictError,
    StartCombatInput,
    StartTacticalCombatInput,
)
from tests.p5a_tactical_helpers import (
    insert_battle_map,
    setup_tactical_table,
)


def test_tactical_start_blank_board() -> None:
    table = setup_tactical_table()
    view = table.combat.start_tactical_combat(
        table.dm_actor,
        StartTacticalCombatInput(blank_width_cells=24, blank_height_cells=18),
    )
    assert view.mode == "tactical"
    assert view.status == "initiative_pending"

    board_view = table.board.get_board(table.dm_actor)
    assert board_view is not None
    assert board_view.combat_id == view.id
    assert (board_view.width_cells, board_view.height_cells) == (24, 18)
    assert board_view.source_battle_map_id is None
    assert board_view.has_image is False
    assert board_view.runtime_revision == 1
    # Active party was included by default.
    assert len(board_view.positions) == 0  # placement happens separately


def test_tactical_start_requires_dimensions_without_map() -> None:
    table = setup_tactical_table()
    with pytest.raises(Exception, match="blank"):
        StartTacticalCombatInput()


def test_tactical_start_freezes_map_baseline() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    view = table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    board_view = table.board.get_board(table.dm_actor)
    assert board_view is not None
    assert (board_view.width_cells, board_view.height_cells) == (20, 15)
    assert board_view.grid_pixel_size is None  # blank map carries no grid alignment
    assert board_view.source_battle_map_id == map_id
    assert board_view.source_battle_map_revision == 3
    # The DM keeps full semantic objects: both walls (incl. the hidden one) and the
    # unrevealed hidden door as a door with its id.
    assert [(w.x1, w.y1, w.x2, w.y2) for w in board_view.walls] == [
        (0, 0, 5, 0), (10, 10, 12, 10),
    ]
    assert len(board_view.doors) == 1
    dm_door = board_view.doors[0]
    assert dm_door.door_id is not None
    assert (dm_door.x1, dm_door.y1, dm_door.x2, dm_door.y2) == (5, 0, 6, 0)
    assert (dm_door.state, dm_door.revealed) == ("closed", False)

    # Player sees public walls plus the hidden door rendered as a wall (hidden
    # walls stay DM-only); the hidden door is indistinguishable from a wall.
    player_view = table.board.get_board(table.player_actor)
    assert player_view is not None
    assert [(w.x1, w.y1, w.x2, w.y2) for w in player_view.walls] == [
        (0, 0, 5, 0), (5, 0, 6, 0),
    ]
    assert player_view.doors == ()

    # DM reveals the hidden door (door id comes from the battle-map definition).
    from app.domain.combat.board import UpdateDoorStateInput

    door_id = table.battle_maps.get_objects(map_id).doors[0].id
    revealed = table.board.update_door_state(
        table.dm_actor, door_id,
        UpdateDoorStateInput(state="open", revealed=True, expected_runtime_revision=1),
    )
    assert revealed.door_id == door_id
    assert revealed.revealed is True

    board_view = table.board.get_board(table.dm_actor)
    assert len(board_view.walls) == 2
    assert len(board_view.doors) == 1
    assert board_view.doors[0].door_id == door_id
    assert board_view.doors[0].state == "open"
    assert board_view.runtime_revision == 2

    # Player sees the revealed door but without its id; the hidden wall stays
    # DM-only.
    player_view = table.board.get_board(table.player_actor)
    assert [(w.x1, w.y1, w.x2, w.y2) for w in player_view.walls] == [(0, 0, 5, 0)]
    assert len(player_view.doors) == 1
    assert player_view.doors[0].door_id is None
    assert player_view.doors[0].state == "open"


def test_tactical_start_unknown_map() -> None:
    table = setup_tactical_table()
    with pytest.raises(BattleMapNotFoundError):
        table.combat.start_tactical_combat(
            table.dm_actor, StartTacticalCombatInput(battle_map_id=uuid4())
        )


def test_tactical_start_idempotent_retry() -> None:
    table = setup_tactical_table()
    payload = StartTacticalCombatInput(
        blank_width_cells=10, blank_height_cells=10, idempotency_key="key-1"
    )
    first = table.combat.start_tactical_combat(table.dm_actor, payload)
    second = table.combat.start_tactical_combat(table.dm_actor, payload)
    assert first.id == second.id
    # Only one combat.started event was emitted.
    started_events = [
        event for event in table.events.list_after(
            table.dm_actor, after_seq=0, limit=100
        ).events
        if event.kind == "combat.started"
    ]
    assert len(started_events) == 1


def test_tactical_start_rejects_second_combat() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(blank_width_cells=8, blank_height_cells=8)
    )
    with pytest.raises(ActiveCombatExistsError):
        table.combat.start_tactical_combat(
            table.dm_actor, StartTacticalCombatInput(blank_width_cells=8, blank_height_cells=8)
        )


def test_quick_start_still_works_alongside() -> None:
    table = setup_tactical_table()
    quick = table.combat.start_quick_combat(
        table.dm_actor, StartCombatInput(include_active_party=True)
    )
    assert quick.mode == "quick"
    # Quick combat has no board: the board read rejects it.
    with pytest.raises(CombatStateConflictError):
        table.board.get_board(table.dm_actor)
    # And a tactical start is rejected while quick is active.
    with pytest.raises(ActiveCombatExistsError):
        table.combat.start_tactical_combat(
            table.dm_actor,
            StartTacticalCombatInput(blank_width_cells=8, blank_height_cells=8),
        )
