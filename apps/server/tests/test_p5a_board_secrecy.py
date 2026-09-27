"""P5-A B6: secrecy — hidden monsters/doors across views, board, events, MCP."""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from sqlalchemy import update

from app.domain.combat.board import PlaceCombatantInput, UpdateDoorStateInput
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    ResolveInitiativeOrderInput,
    StartTacticalCombatInput,
)
from app.persistence.combat.tables import combat_entries
from tests.p5a_tactical_helpers import (
    TacticalTable,
    insert_battle_map,
    setup_tactical_table,
)


def _add_hidden_monster(table: TacticalTable, name: str = "SecretStalker") -> UUID:
    instance = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name=name,
        armor_class=15, max_hp=22, speed={"walk": "30 ft."},
        visibility="hidden",
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=instance.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return next(e.id for e in view.entries if e.subject_kind == "monster")


def _player_event_kinds(table: TacticalTable) -> list[str]:
    page = table.events.list_after(table.player_actor, after_seq=0, limit=200)
    return [event.kind for event in page.events]


def _player_event_payloads(table: TacticalTable) -> str:
    page = table.events.list_after(table.player_actor, after_seq=0, limit=200)
    return json.dumps([event.payload for event in page.events], default=str)


def test_hidden_monster_omitted_from_player_combat_view() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(blank_width_cells=10, blank_height_cells=10)
    )
    hidden_entry = _add_hidden_monster(table)

    dm_view = table.combat.get_active_combat(table.dm_actor)
    assert dm_view is not None
    assert hidden_entry in {e.id for e in dm_view.entries}

    player_view = table.combat.get_active_combat(table.player_actor)
    assert player_view is not None
    assert hidden_entry not in {e.id for e in player_view.entries}
    assert all("SecretStalker" not in (e.display_name or "") for e in player_view.entries)


def test_hidden_monster_position_hidden_from_player_board() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(blank_width_cells=10, blank_height_cells=10)
    )
    hidden_entry = _add_hidden_monster(table)
    table.board.place_position(
        table.dm_actor, hidden_entry, PlaceCombatantInput(anchor_x=6, anchor_y=6)
    )

    dm_board = table.board.get_board(table.dm_actor)
    assert hidden_entry in {p.entry_id for p in dm_board.positions}

    player_board = table.board.get_board(table.player_actor)
    assert hidden_entry not in {p.entry_id for p in player_board.positions}


def test_hidden_monster_placement_event_is_dm_only() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(blank_width_cells=10, blank_height_cells=10)
    )
    hidden_entry = _add_hidden_monster(table)
    table.board.place_position(
        table.dm_actor, hidden_entry, PlaceCombatantInput(anchor_x=6, anchor_y=6)
    )

    dm_kinds = [
        event.kind
        for event in table.events.list_after(table.dm_actor, after_seq=0, limit=200).events
    ]
    assert "combat.position_placed" in dm_kinds
    # Player never sees the hidden placement event...
    assert "combat.position_placed" not in _player_event_kinds(table)
    # ...nor the hidden monster's id or name in any payload they can see.
    payloads = _player_event_payloads(table)
    assert str(hidden_entry) not in payloads
    assert "SecretStalker" not in payloads


def test_hidden_door_state_event_is_dm_only_until_revealed() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    door_id = table.battle_maps.get_objects(map_id).doors[0].id

    # State change without reveal: hidden door stays a wall for players and the
    # event is DM-only.
    table.board.update_door_state(
        table.dm_actor, door_id,
        UpdateDoorStateInput(state="open", expected_runtime_revision=1),
    )
    assert "combat.door_state_changed" not in _player_event_kinds(table)
    player_board = table.board.get_board(table.player_actor)
    assert player_board.doors == ()

    # Revealing publishes a public event and the door (without id) to players.
    table.board.update_door_state(
        table.dm_actor, door_id,
        UpdateDoorStateInput(state="open", revealed=True, expected_runtime_revision=2),
    )
    assert "combat.door_state_changed" in _player_event_kinds(table)
    player_board = table.board.get_board(table.player_actor)
    assert len(player_board.doors) == 1
    assert player_board.doors[0].door_id is None
    assert str(door_id) not in _player_event_payloads(table)


def test_hidden_current_turn_projects_to_none_for_player() -> None:
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(blank_width_cells=10, blank_height_cells=10)
    )
    dm_view = table.combat.get_active_combat(table.dm_actor)
    assert dm_view is not None
    char_entry = next(e.id for e in dm_view.entries if e.subject_kind == "character")
    hidden_entry = _add_hidden_monster(table)

    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    table.board.place_position(
        table.dm_actor, hidden_entry, PlaceCombatantInput(anchor_x=6, anchor_y=6)
    )
    with table.engine.begin() as conn:
        for entry_id, total in ((hidden_entry, 20), (char_entry, 10)):
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(initiative_total=total)
            )
    table.combat.resolve_initiative_order(
        table.dm_actor,
        ResolveInitiativeOrderInput(ordered_entry_ids=(hidden_entry, char_entry)),
    )

    dm_view = table.combat.get_active_combat(table.dm_actor)
    assert dm_view is not None
    assert dm_view.current_turn_entry_id == hidden_entry

    player_view = table.combat.get_active_combat(table.player_actor)
    assert player_view is not None
    assert player_view.current_turn_entry_id is None


def test_mcp_active_combat_shares_player_projection() -> None:
    """MCP combat_get_active goes through get_active_combat(actor)."""
    table = setup_tactical_table()
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(blank_width_cells=10, blank_height_cells=10)
    )
    hidden_entry = _add_hidden_monster(table)
    # The MCP surface calls the same service method with the caller's actor.
    mcp_view = table.combat.get_active_combat(table.player_actor)
    assert mcp_view is not None
    assert hidden_entry not in {e.id for e in mcp_view.entries}
