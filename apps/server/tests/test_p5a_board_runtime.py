"""P5-A B4/B5: board runtime — placement authority/timing/validation, doors, image."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert, update

from app.domain.combat.board import (
    CombatBoardImageNotFoundError,
    CombatPlacementInvalidError,
    PlaceCombatantInput,
    UpdateDoorStateInput,
)
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    CombatPlacementIncompleteError,
    CombatStateConflictError,
    ResolveInitiativeOrderInput,
    StartTacticalCombatInput,
)
from app.domain.rooms.table_events import TableEventActorUnauthorizedError
from app.persistence.battle_maps.tables import battle_map_terrain, battle_map_walls
from tests.p5a_tactical_helpers import (
    TacticalTable,
    insert_battle_map,
    setup_tactical_table,
)


def _start(table: TacticalTable, **kwargs):
    return table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(**kwargs)
    )


def _character_entry_id(table: TacticalTable):
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return view.entries[0].id


def _add_monster(table: TacticalTable, *, visibility: str = "public"):
    instance = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name="Goblin",
        armor_class=15, max_hp=7, speed={"walk": "30 ft."},
        visibility=visibility,
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=instance.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return next(e.id for e in view.entries if e.subject_kind == "monster")


def _set_initiative(table: TacticalTable, entry_id, total: int = 15) -> None:
    """Test setup: bypass the roll flow; the gate under test is placement."""
    from app.persistence.combat.tables import combat_entries

    with table.engine.begin() as conn:
        conn.execute(
            update(combat_entries)
            .where(combat_entries.c.id == entry_id)
            .values(initiative_total=total)
        )


def test_player_places_own_character_dm_places_anything() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=10, blank_height_cells=10)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)

    # Player places their own character.
    placed = table.board.place_position(
        table.player_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    assert (placed.anchor_x, placed.anchor_y) == (1, 1)

    # Player cannot place the DM's monster.
    with pytest.raises(TableEventActorUnauthorizedError):
        table.board.place_position(
            table.player_actor, monster_entry,
            PlaceCombatantInput(anchor_x=3, anchor_y=3),
        )

    # DM can place the monster.
    placed = table.board.place_position(
        table.dm_actor, monster_entry, PlaceCombatantInput(anchor_x=5, anchor_y=5)
    )
    assert (placed.anchor_x, placed.anchor_y) == (5, 5)


def test_initiative_pending_allows_replace() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=10, blank_height_cells=10)
    char_entry = _character_entry_id(table)

    first = table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    second = table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=2, anchor_y=2)
    )
    assert second.revision == first.revision + 1
    board = table.board.get_board(table.dm_actor)
    assert [(p.anchor_x, p.anchor_y) for p in board.positions] == [(2, 2)]


def test_placement_validation_rejects_with_generic_code() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    # Blocked terrain at (3,3); the map also has a wall (0,0)-(5,0).
    now = datetime.now(timezone.utc)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_map_terrain).values(
            battle_map_id=map_id, x=3, y=3, terrain_kind="blocked",
        ))
    # A Large (2x2) monster vs a wall through the middle of the map: insert a
    # vertical wall at x=8 spanning y 5..7, then anchor the 2x2 at (7,5) so the
    # wall runs along its interior edge (rejected), and at (9,5) where the
    # wall is outside the footprint (legal).
    with table.engine.begin() as conn:
        conn.execute(insert(battle_map_walls).values(
            id=uuid4(), battle_map_id=map_id,
            x1=8, y1=5, x2=8, y2=7, visibility="public",
        ))
    _start(table, battle_map_id=map_id)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)

    # Out of bounds (map is 20x15; x=20 is outside).
    with pytest.raises(CombatPlacementInvalidError):
        table.board.place_position(
            table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=20, anchor_y=0)
        )
    # Blocked terrain.
    with pytest.raises(CombatPlacementInvalidError):
        table.board.place_position(
            table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=3, anchor_y=3)
        )
    # Overlap with another entry.
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    with pytest.raises(CombatPlacementInvalidError):
        table.board.place_position(
            table.dm_actor, monster_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
        )
    # A Large (2x2) monster straddling the frozen wall (0,0)-(5,0): anchoring at
    # (0,0) puts the wall along the footprint's interior edge x=... — anchoring
    # at (4,1) keeps the wall on the boundary (legal), anchoring at (4,0) puts
    # the wall through the interior (rejected with the same generic code).
    large = table.combat.monster_repository.create_instance(
        campaign_id=table.campaign_id, name="Ogre",
        rules_snapshot={
            "size": "large", "armor_class": 11, "max_hp": 59,
            "speed": {"walk": "40 ft."},
        },
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=large.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    large_entry = next(e.id for e in view.entries if e.display_name == "Ogre")
    # Anchor (7,5): the 2x2 spans x in {7,8}, y in {5,6}; the wall at x=8
    # runs along its interior edge -> rejected with the generic code.
    with pytest.raises(CombatPlacementInvalidError):
        table.board.place_position(
            table.dm_actor, large_entry, PlaceCombatantInput(anchor_x=7, anchor_y=5)
        )
    # Anchor (9,5): the wall is outside the footprint -> legal.
    table.board.place_position(
        table.dm_actor, large_entry, PlaceCombatantInput(anchor_x=9, anchor_y=5)
    )


def test_hidden_blocker_uses_same_generic_code() -> None:
    """A placement blocked only by hidden geometry reports the generic code."""
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_map_walls).values(
            id=uuid4(), battle_map_id=map_id,
            x1=8, y1=5, x2=8, y2=7, visibility="hidden",
        ))
    _start(table, battle_map_id=map_id)
    large = table.combat.monster_repository.create_instance(
        campaign_id=table.campaign_id, name="Ogre",
        rules_snapshot={
            "size": "large", "armor_class": 11, "max_hp": 59,
            "speed": {"walk": "40 ft."},
        },
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=large.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    large_entry = next(e.id for e in view.entries if e.display_name == "Ogre")
    # Only the hidden wall blocks this anchor; the error must not name it.
    with pytest.raises(CombatPlacementInvalidError) as exc_info:
        table.board.place_position(
            table.dm_actor, large_entry, PlaceCombatantInput(anchor_x=7, anchor_y=5)
        )
    assert "hidden" not in str(exc_info.value).lower()


def test_running_gate_and_mid_combat_entrant() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=10, blank_height_cells=10)
    char_entry = _character_entry_id(table)
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    _set_initiative(table, char_entry)
    table.combat.resolve_initiative_order(
        table.dm_actor, ResolveInitiativeOrderInput(ordered_entry_ids=(char_entry,))
    )
    # Running: repositioning an already-placed entry is rejected.
    with pytest.raises(CombatPlacementInvalidError):
        table.board.place_position(
            table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=2, anchor_y=2)
        )
    # A mid-combat entrant added while running can still be placed once.
    monster_entry = _add_monster(table)
    placed = table.board.place_position(
        table.dm_actor, monster_entry, PlaceCombatantInput(anchor_x=4, anchor_y=4)
    )
    assert (placed.anchor_x, placed.anchor_y) == (4, 4)


def test_initiative_gate_requires_all_placed() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=10, blank_height_cells=10)
    char_entry = _character_entry_id(table)
    _add_monster(table)
    # Monster has no position: initiative cannot proceed.
    with pytest.raises(CombatPlacementIncompleteError):
        table.combat.resolve_initiative_order(
            table.dm_actor,
            ResolveInitiativeOrderInput(ordered_entry_ids=(char_entry,)),
        )
    # Quick combat is unaffected by the gate.
    table.combat.end_combat(table.dm_actor)
    from app.domain.combat.lifecycle import StartCombatInput

    quick = table.combat.start_quick_combat(
        table.dm_actor, StartCombatInput(include_active_party=True)
    )
    assert quick.mode == "quick"


def test_withdraw_and_remove_delete_position_end_keeps_board() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=10, blank_height_cells=10)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    table.board.place_position(
        table.dm_actor, monster_entry, PlaceCombatantInput(anchor_x=2, anchor_y=2)
    )

    table.combat.withdraw_entry(table.dm_actor, monster_entry)
    board = table.board.get_board(table.dm_actor)
    assert [p.entry_id for p in board.positions] == [char_entry]

    table.combat.remove_entry(table.dm_actor, char_entry)
    board = table.board.get_board(table.dm_actor)
    assert board.positions == ()

    # Ending the combat keeps the frozen board and positions for history.
    combat_view = table.combat.end_combat(table.dm_actor)
    assert combat_view.status == "ended"


def test_door_update_bumps_runtime_revision_not_map() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    _start(table, battle_map_id=map_id)
    before = table.battle_maps.get_map(table.room_id, map_id)
    assert before is not None

    door_id = table.battle_maps.get_objects(map_id).doors[0].id
    table.board.update_door_state(
        table.dm_actor, door_id,
        UpdateDoorStateInput(state="open", revealed=True, expected_runtime_revision=1),
    )
    board = table.board.get_board(table.dm_actor)
    assert board.runtime_revision == 2
    assert board.source_battle_map_revision == before.revision

    # Map Definition is untouched: same revision, same objects.
    after = table.battle_maps.get_map(table.room_id, map_id)
    assert after is not None
    assert after.revision == before.revision
    objects = table.battle_maps.get_objects(map_id)
    assert objects.doors[0].default_state == "closed"

    # Stale revision is rejected.
    with pytest.raises(CombatStateConflictError):
        table.board.update_door_state(
            table.dm_actor, door_id,
            UpdateDoorStateInput(state="closed", expected_runtime_revision=1),
        )


def test_player_wall_order_is_sorted_regardless_of_hidden_source() -> None:
    """Wall order cannot leak which segments came from hidden doors."""
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    _start(table, battle_map_id=map_id)
    player_view = table.board.get_board(table.player_actor)
    coords = [(w.x1, w.y1, w.x2, w.y2) for w in player_view.walls]
    assert coords == sorted(coords)
    # The hidden door's segment sits in sorted position, not insertion order.
    assert (5, 0, 6, 0) in coords


def test_board_image_missing_returns_404_code() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=10, blank_height_cells=10)
    with pytest.raises(CombatBoardImageNotFoundError):
        table.board.open_board_image(table.player_actor)


def test_reorder_running_gate_rejects_unplaced_mid_combat_entrant() -> None:
    from app.domain.combat.order import CombatOrderService, ReorderInitiativeInput
    from app.persistence.combat.order import CombatOrderRepository

    table = setup_tactical_table()
    _start(table, blank_width_cells=10, blank_height_cells=10)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    table.board.place_position(
        table.dm_actor, monster_entry, PlaceCombatantInput(anchor_x=2, anchor_y=2)
    )
    _set_initiative(table, char_entry, 20)
    _set_initiative(table, monster_entry, 10)
    table.combat.resolve_initiative_order(
        table.dm_actor,
        ResolveInitiativeOrderInput(ordered_entry_ids=(char_entry, monster_entry)),
    )

    # Mid-combat entrant joins running combat without a position yet.
    before = {e.id for e in table.combat.get_active_combat(table.dm_actor).entries}
    _add_monster(table)
    after = table.combat.get_active_combat(table.dm_actor)
    assert after is not None
    late_entry = next(e.id for e in after.entries if e.id not in before)
    order = CombatOrderService(
        CombatOrderRepository(table.engine, table.events.repository),
        table.combat, table.events,
    )
    with pytest.raises(CombatPlacementIncompleteError):
        order.reorder_running(
            table.dm_actor,
            ReorderInitiativeInput(
                ordered_entry_ids=(char_entry, monster_entry, late_entry)
            ),
        )
    # Once placed, the same reorder succeeds.
    table.board.place_position(
        table.dm_actor, late_entry, PlaceCombatantInput(anchor_x=3, anchor_y=3)
    )
    _set_initiative(table, late_entry, 15)
    view = order.reorder_running(
        table.dm_actor,
        ReorderInitiativeInput(
            ordered_entry_ids=(char_entry, late_entry, monster_entry)
        ),
    )
    assert view.status == "running"


def test_end_combat_retains_board_and_positions() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=10, blank_height_cells=10)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    table.board.place_position(
        table.dm_actor, monster_entry, PlaceCombatantInput(anchor_x=2, anchor_y=2)
    )
    _set_initiative(table, char_entry, 20)
    _set_initiative(table, monster_entry, 10)
    table.combat.resolve_initiative_order(
        table.dm_actor,
        ResolveInitiativeOrderInput(ordered_entry_ids=(char_entry, monster_entry)),
    )
    # Frozen board and positions survive for history review (persistence level;
    # the runtime board view intentionally requires an active combat).
    combat_id = table.combat.end_combat(table.dm_actor).id
    stored = table.board.board_repository.get_board(combat_id)
    assert stored is not None
    assert stored.width_cells == 10
    assert {
        position.combat_entry_id
        for position in table.board.board_repository.list_positions(combat_id)
    } == {char_entry, monster_entry}


def _owner_context(table: TacticalTable):
    from app.domain.rooms.schemas import RoomAccessContext, RoomAccessAuthority

    return RoomAccessContext(
        room_id=table.room_id, access_session_id=uuid4(),
        authority=RoomAccessAuthority.OWNER, display_name="Owner",
    )


_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _upload_map_image(table: TacticalTable):
    return table.board.room_asset_service.create(
        _owner_context(table), room_id=table.room_id,
        kind="battle_map_image", filename="dungeon.png",
        mime_type="image/png", data=_PNG_BYTES,
    )


def _insert_image_map(table: TacticalTable, asset_id) -> object:
    from app.persistence.battle_maps.tables import battle_maps

    map_id = uuid4()
    now = datetime.now(timezone.utc)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_maps).values(
            id=map_id, room_id=table.room_id, name="Dungeon",
            source_kind="image", image_asset_id=asset_id,
            width_cells=20, height_cells=15,
            grid_pixel_size=None, grid_offset_x=None, grid_offset_y=None,
            revision=1, created_at=now, updated_at=now,
        ))
    return map_id


def test_player_can_read_frozen_board_image() -> None:
    table = setup_tactical_table()
    asset = _upload_map_image(table)
    map_id = _insert_image_map(table, asset.id)
    _start(table, battle_map_id=map_id)

    # Frozen at tactical start: the Player reads the board image through the
    # combat surface, no Room Asset read authority required.
    mime_type, filename, handle = table.board.open_board_image(table.player_actor)
    assert mime_type == "image/png"
    assert filename == "dungeon.png"
    assert handle.read() == _PNG_BYTES


def test_board_image_asset_is_referenced_and_cannot_be_deleted() -> None:
    from app.domain.room_assets.schemas import RoomAssetInUseError

    table = setup_tactical_table()
    asset = _upload_map_image(table)
    map_id = _insert_image_map(table, asset.id)
    _start(table, battle_map_id=map_id)

    repository = table.board.room_asset_service.repository
    assert repository.is_referenced(asset.id) is True
    with pytest.raises(RoomAssetInUseError):
        table.board.room_asset_service.delete(
            _owner_context(table), table.room_id, asset.id
        )


def test_room_hard_delete_clears_board_rows() -> None:
    from app.persistence.combat_boards.tables import (
        combat_board_doors,
        combat_boards,
        combat_positions,
    )
    from app.persistence.rooms.workspace import RoomWorkspaceRepository
    from sqlalchemy import func, select

    table = setup_tactical_table()
    _start(table, blank_width_cells=10, blank_height_cells=10)
    char_entry = _character_entry_id(table)
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )
    combat_id = table.combat.get_active_combat(table.dm_actor).id

    RoomWorkspaceRepository(table.engine).hard_delete_room(table.room_id)

    with table.engine.connect() as conn:
        for board_table in (combat_boards, combat_board_doors, combat_positions):
            count = conn.execute(
                select(func.count()).select_from(board_table).where(
                    board_table.c.combat_id == combat_id
                )
            ).scalar()
            assert count == 0, board_table.name


def test_request_initiative_gate_rejects_unplaced_tactical_entry() -> None:
    from app.domain.combat.initiative import CombatInitiativeService, RequestInitiativeInput
    from app.domain.combat.roll_compat import CombatAwareRollRepository
    from app.domain.rooms.character_rolls import CharacterRollModifierResolver
    from app.domain.rooms.rolls import RollService
    from app.persistence.combat.initiative import CombatInitiativeRepository
    from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository

    table = setup_tactical_table()
    _start(table, blank_width_cells=10, blank_height_cells=10)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    # Character placed; monster not.
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=1, anchor_y=1)
    )

    roll_service = RollService(
        CombatAwareRollRepository(table.engine, table.events.repository),
        ExplorationSubjectRepository(table.engine),
        table.events,
        CharacterRollModifierResolver(table.characters, table.registry),
    )
    initiative = CombatInitiativeService(
        CombatInitiativeRepository(table.engine, table.events.repository),
        table.combat.repository,
        table.combat,
        table.combat.monster_repository,
        roll_service,
        table.events,
    )
    with pytest.raises(CombatPlacementIncompleteError):
        initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(entry_ids=(char_entry, monster_entry)),
        )
    # Placing the monster unblocks the request.
    table.board.place_position(
        table.dm_actor, monster_entry, PlaceCombatantInput(anchor_x=2, anchor_y=2)
    )
    response = initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(entry_ids=(char_entry, monster_entry)),
    )
    assert response is not None


def _position_event_count(table: TacticalTable) -> int:
    from sqlalchemy import func, select

    from app.persistence.rooms.table_runtime import session_events

    with table.engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(session_events).where(
                session_events.c.kind == "combat.position_placed"
            )
        ).scalar_one()


def test_placement_retry_with_same_key_does_not_duplicate() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=10, blank_height_cells=10)
    char_entry = _character_entry_id(table)
    request = PlaceCombatantInput(anchor_x=2, anchor_y=3, idempotency_key="place-once")

    first = table.board.place_position(table.dm_actor, char_entry, request)
    second = table.board.place_position(table.dm_actor, char_entry, request)

    assert (second.anchor_x, second.anchor_y) == (first.anchor_x, first.anchor_y) == (2, 3)
    board = table.board.get_board(table.dm_actor)
    assert [p.entry_id for p in board.positions] == [char_entry]
    assert _position_event_count(table) == 1


def test_definition_edit_after_start_does_not_drift_board() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    _start(table, battle_map_id=map_id)
    before = table.board.get_board(table.dm_actor)

    with table.engine.begin() as conn:
        conn.execute(insert(battle_map_walls).values(
            id=uuid4(), battle_map_id=map_id, x1=1, y1=5, x2=4, y2=5, visibility="public",
        ))
        conn.execute(insert(battle_map_terrain).values(
            battle_map_id=map_id, x=7, y=7, terrain_kind="blocked",
        ))

    after = table.board.get_board(table.dm_actor)
    assert after.walls == before.walls
    assert after.terrain == before.terrain
    assert after.runtime_revision == before.runtime_revision
