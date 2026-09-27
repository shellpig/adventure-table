"""P5-B B1: movement bookkeeping, path resolution, Preview/Confirm (backend only)."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select, update

from app.api.rooms.combat import _map_combat_error
from app.domain.combat.board import PlaceCombatantInput, UpdateDoorStateInput
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    CombatActionInput,
    CombatActionKind,
    CombatEconomyCost,
    CombatStateConflictError,
    ResolveInitiativeOrderInput,
    StartCombatInput,
    StartTacticalCombatInput,
)
from app.domain.combat.movement import (
    CombatMovementInvalidError,
    CombatMovementStaleError,
    ConfirmMovementInput,
    MovementAnchorInput,
    MovementService,
    PreviewMovementInput,
)
from app.domain.rooms.table_events import TableActorContext, TableEventActorUnauthorizedError
from app.domain.spatial import (
    GridCell,
    PathCreature,
    PathValidationRequest,
    cell_distance,
    grid_distance,
    step_cost,
    validate_movement_path,
)
from app.domain.spatial.primitives import BarrierSegment, Footprint
from app.persistence.combat.tables import combat_entries
from app.persistence.rooms.table_runtime import session_events
from tests.p5a_tactical_helpers import (
    TacticalTable,
    insert_battle_map,
    setup_tactical_table,
)


def _movement(table: TacticalTable) -> MovementService:
    return MovementService(
        board_repository=table.board.board_repository,
        board_service=table.board,
        combat_service=table.combat,
    )


def _start(table: TacticalTable, **kwargs):
    return table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(**kwargs)
    )


def _character_entry_id(table: TacticalTable) -> UUID:
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return view.entries[0].id


def _add_monster(table: TacticalTable, *, visibility: str = "public") -> UUID:
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


def _running(
    table: TacticalTable,
    *,
    char_entry: UUID,
    monster_entry: UUID,
    char_first: bool = True,
    char_at: tuple[int, int] = (1, 1),
    monster_at: tuple[int, int] = (8, 8),
) -> None:
    """Place both combatants, set initiative, and finalize to running status."""
    table.board.place_position(
        table.dm_actor, char_entry, PlaceCombatantInput(anchor_x=char_at[0], anchor_y=char_at[1])
    )
    table.board.place_position(
        table.dm_actor, monster_entry,
        PlaceCombatantInput(anchor_x=monster_at[0], anchor_y=monster_at[1]),
    )
    with table.engine.begin() as conn:
        conn.execute(
            update(combat_entries)
            .where(combat_entries.c.id == char_entry)
            .values(initiative_total=20 if char_first else 10)
        )
        conn.execute(
            update(combat_entries)
            .where(combat_entries.c.id == monster_entry)
            .values(initiative_total=10 if char_first else 20)
        )
    first, second = (char_entry, monster_entry) if char_first else (monster_entry, char_entry)
    table.combat.resolve_initiative_order(
        table.dm_actor, ResolveInitiativeOrderInput(ordered_entry_ids=(first, second))
    )


def _bookkeeping(table: TacticalTable, entry_id: UUID) -> tuple[int, int, int, dict]:
    with table.engine.connect() as conn:
        row = conn.execute(
            select(
                combat_entries.c.movement_used_feet,
                combat_entries.c.movement_diagonal_steps_used,
                combat_entries.c.movement_budget_feet,
                combat_entries.c.pending_movement_state,
            ).where(combat_entries.c.id == entry_id)
        ).mappings().one()
    return (
        int(row["movement_used_feet"]),
        int(row["movement_diagonal_steps_used"]),
        int(row["movement_budget_feet"]),
        dict(row["pending_movement_state"]),
    )


def _path(*coords: tuple[int, int]) -> tuple[MovementAnchorInput, ...]:
    return tuple(MovementAnchorInput(x=x, y=y) for x, y in coords)


def _preview(table: TacticalTable, actor: TableActorContext, entry_id: UUID, *coords):
    return _movement(table).preview(
        actor, entry_id, PreviewMovementInput(entry_id=entry_id, path=_path(*coords))
    )


def _confirm(
    table: TacticalTable,
    actor: TableActorContext,
    entry_id: UUID,
    *coords: tuple[int, int],
    expected_position_revision: int = 1,
    expected_board_revision: int = 1,
    idempotency_key: str | None = None,
):
    return _movement(table).confirm(
        actor, entry_id,
        ConfirmMovementInput(
            entry_id=entry_id,
            path=_path(*coords),
            expected_position_revision=expected_position_revision,
            expected_board_revision=expected_board_revision,
            idempotency_key=idempotency_key,
        ),
    )


def _movement_event_count(table: TacticalTable) -> int:
    with table.engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(session_events).where(
                session_events.c.kind == "combat.movement_committed"
            )
        ).scalar_one()


def _movement_event_visibility(table: TacticalTable) -> str | None:
    with table.engine.connect() as conn:
        row = conn.execute(
            select(session_events.c.visibility).where(
                session_events.c.kind == "combat.movement_committed"
            )
        ).mappings().one_or_none()
    return row["visibility"] if row else None


# ----------------------------------------------------------------------
# B.1 — spatial primitives: distance, step cost, diagonal alternation


def test_grid_distance_uses_nearest_occupied_cell_pair() -> None:
    # A 2-wide footprint at (0,0) occupies (0,0),(1,0); nearest pair to (3,0) is (1,0)->(3,0).
    from_cells = (GridCell(0, 0), GridCell(1, 0))
    result = grid_distance(from_cells, (GridCell(3, 0),))
    assert (result.feet, result.diagonal_steps) == (10, 0)


def test_cell_distance_diagonal_alternates_5_10() -> None:
    assert cell_distance(GridCell(0, 0), GridCell(1, 1)).feet == 5
    assert cell_distance(GridCell(0, 0), GridCell(2, 2)).feet == 15
    assert cell_distance(GridCell(0, 0), GridCell(3, 3)).feet == 20
    assert cell_distance(GridCell(0, 0), GridCell(4, 4)).feet == 30
    assert cell_distance(GridCell(0, 0), GridCell(2, 1)).feet == 10  # 1 diag + 1 orth


def test_step_cost_diagonal_parity_and_difficult() -> None:
    assert step_cost(diagonal=True, diagonal_steps_used=0, difficult=False) == 5
    assert step_cost(diagonal=True, diagonal_steps_used=1, difficult=False) == 10
    assert step_cost(diagonal=True, diagonal_steps_used=2, difficult=False) == 5
    assert step_cost(diagonal=False, diagonal_steps_used=0, difficult=False) == 5
    assert step_cost(diagonal=False, diagonal_steps_used=0, difficult=True) == 10
    assert step_cost(diagonal=True, diagonal_steps_used=1, difficult=True) == 20


def _simple_request(**overrides) -> PathValidationRequest:
    base = dict(
        start=GridCell(1, 1),
        anchors=(GridCell(1, 1),),
        footprint=Footprint(1, 1),
        mover_size_rank=2,
        width_cells=12,
        height_cells=12,
        blocked_cells=frozenset(),
        difficult_cells=frozenset(),
        barriers=(),
        creatures=(),
        budget_feet=30,
        diagonal_steps_used=0,
    )
    base.update(overrides)
    return PathValidationRequest(**base)


def test_validator_rejects_empty_and_mismatched_start() -> None:
    assert validate_movement_path(_simple_request()).failure == "empty_path"
    bad = _simple_request(anchors=(GridCell(2, 2), GridCell(3, 2)))
    assert validate_movement_path(bad).failure == "path_start_mismatch"


def test_validator_rejects_non_adjacent_and_out_of_bounds() -> None:
    jump = _simple_request(anchors=(GridCell(1, 1), GridCell(3, 1)))
    assert validate_movement_path(jump).failure == "not_adjacent"
    oob = _simple_request(
        start=GridCell(10, 10),
        anchors=(GridCell(10, 10), GridCell(11, 10), GridCell(12, 10)),
    )
    assert validate_movement_path(oob).failure == "out_of_bounds"


def test_validator_rejects_blocked_terrain_and_wall_crossing() -> None:
    blocked = _simple_request(
        anchors=(GridCell(1, 1), GridCell(2, 1)),
        blocked_cells=frozenset({GridCell(2, 1)}),
    )
    assert validate_movement_path(blocked).failure == "blocked_terrain"
    wall = _simple_request(
        anchors=(GridCell(1, 1), GridCell(2, 1)),
        barriers=(BarrierSegment(x1=2, y1=1, x2=2, y2=2),),
    )
    assert validate_movement_path(wall).failure == "wall_or_door"


def test_validator_rejects_diagonal_corner_cut() -> None:
    # Wall along the north edge of the start cell: the diagonal (1,1)->(2,2)
    # would cut the corner through it.
    req = _simple_request(
        anchors=(GridCell(1, 1), GridCell(2, 2)),
        barriers=(BarrierSegment(x1=1, y1=2, x2=2, y2=2),),
    )
    assert validate_movement_path(req).failure == "wall_or_door"
    # Blocked corner cell also forbids the diagonal.
    req = _simple_request(
        anchors=(GridCell(1, 1), GridCell(2, 2)),
        blocked_cells=frozenset({GridCell(2, 1)}),
    )
    assert validate_movement_path(req).failure == "wall_or_door"


def test_validator_footprint_sweep_blocks_large_mover() -> None:
    # A 2x2 mover stepping east sweeps (3,1),(3,2): the wall on that edge blocks.
    req = _simple_request(
        start=GridCell(1, 1),
        anchors=(GridCell(1, 1), GridCell(2, 1)),
        footprint=Footprint(2, 2),
        barriers=(BarrierSegment(x1=3, y1=1, x2=3, y2=3),),
    )
    assert validate_movement_path(req).failure == "wall_or_door"


def test_validator_open_and_broken_doors_do_not_block() -> None:
    # Closed door blocks; broken does not (validator only receives blockers).
    closed = _simple_request(
        anchors=(GridCell(1, 1), GridCell(2, 1)),
        barriers=(BarrierSegment(x1=2, y1=1, x2=2, y2=2),),
    )
    assert validate_movement_path(closed).failure == "wall_or_door"
    open_door = _simple_request(anchors=(GridCell(1, 1), GridCell(2, 1)))
    result = validate_movement_path(open_door)
    assert result.valid and result.used_feet == 5


def test_validator_creature_space_rules() -> None:
    other_cells = frozenset({GridCell(2, 1)})
    hostile_same = PathCreature(cells=other_cells, hostile_to_mover=True, size_rank=2)
    # Hostile, same size: cannot pass through.
    req = _simple_request(
        anchors=(GridCell(1, 1), GridCell(2, 1), GridCell(3, 1)),
        creatures=(hostile_same,),
    )
    assert validate_movement_path(req).failure == "creature_blocked"
    # Hostile, two sizes larger: passable but difficult (5 -> 10).
    huge = PathCreature(cells=other_cells, hostile_to_mover=True, size_rank=4)
    req = _simple_request(
        anchors=(GridCell(1, 1), GridCell(2, 1), GridCell(3, 1)),
        creatures=(huge,),
    )
    result = validate_movement_path(req)
    assert result.valid
    assert result.steps[0].cost_feet == 10
    assert "creature_space" in result.steps[0].warnings
    # Nonhostile, same size: passable but difficult.
    ally = PathCreature(cells=other_cells, hostile_to_mover=False, size_rank=2)
    req = _simple_request(
        anchors=(GridCell(1, 1), GridCell(2, 1), GridCell(3, 1)),
        creatures=(ally,),
    )
    result = validate_movement_path(req)
    assert result.valid and result.steps[0].cost_feet == 10
    # Nobody may end on another creature's space.
    req = _simple_request(
        anchors=(GridCell(1, 1), GridCell(2, 1)),
        creatures=(ally,),
    )
    assert validate_movement_path(req).failure == "end_on_occupied"


def test_validator_enforces_budget() -> None:
    req = _simple_request(
        anchors=(GridCell(1, 1), GridCell(2, 1), GridCell(3, 1)),
        budget_feet=5,
    )
    result = validate_movement_path(req)
    assert not result.valid and result.failure == "budget_exceeded"
    assert result.failure_step_index == 2


# ----------------------------------------------------------------------
# B.2 — Preview: read-only plan from caller-visible state


def test_preview_returns_costs_and_revisions_without_persisting() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    events_before = _movement_event_count(table)
    view = _preview(
        table, table.player_actor, char_entry,
        (1, 1), (2, 1), (3, 2),  # orth 5 + diag 5
    )
    assert view.valid
    assert [s.cost_feet for s in view.steps] == [5, 5]
    assert view.used_feet == 10
    assert view.budget_feet == 30  # fighter fixture falls back to 30 ft
    assert view.remaining_feet == 20
    assert view.position_revision == 1
    assert view.board_revision == 1

    # Nothing persisted: position, bookkeeping, and events are untouched.
    position = table.board.board_repository.get_position(char_entry)
    assert position is not None and (position.anchor_x, position.anchor_y) == (1, 1)
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})
    assert _movement_event_count(table) == events_before


def test_preview_invalid_path_reports_failure() -> None:
    from datetime import datetime, timezone
    from uuid import uuid4

    from sqlalchemy import insert

    from app.persistence.battle_maps.tables import battle_map_walls, battle_maps

    table = setup_tactical_table()
    map_id = uuid4()
    now = datetime.now(timezone.utc)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_maps).values(
            id=map_id, room_id=table.room_id, name="WallRoom",
            source_kind="blank", image_asset_id=None,
            width_cells=12, height_cells=12,
            grid_pixel_size=None, grid_offset_x=None, grid_offset_y=None,
            revision=1, created_at=now, updated_at=now,
        ))
        conn.execute(insert(battle_map_walls).values(
            id=uuid4(), battle_map_id=map_id,
            x1=3, y1=0, x2=3, y2=5, visibility="public",
        ))
    _start(table, battle_map_id=map_id)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry, char_at=(2, 2))

    # The public wall runs along x=3: stepping (2,2)->(3,2) crosses it.
    view = _preview(
        table, table.player_actor, char_entry,
        (2, 2), (3, 2),
    )
    assert not view.valid
    assert view.failure == "wall_or_door"
    assert view.steps == ()


def test_preview_shows_difficult_terrain_warning() -> None:
    from datetime import datetime, timezone

    from sqlalchemy import insert

    from app.persistence.battle_maps.tables import battle_map_terrain

    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    now = datetime.now(timezone.utc)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_map_terrain).values(
            battle_map_id=map_id, x=2, y=1, terrain_kind="difficult",
        ))
    _start(table, battle_map_id=map_id)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    view = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert view.valid
    assert view.steps[0].difficult
    assert view.steps[0].cost_feet == 10
    assert "difficult_terrain" in view.steps[0].warnings


# ----------------------------------------------------------------------
# B.3 — Confirm: atomic commit, idempotency, stale, illegal


def test_confirm_commits_position_bookkeeping_and_event() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    result = _confirm(
        table, table.player_actor, char_entry,
        (1, 1), (2, 1), (3, 2),
        idempotency_key="move-once",
    )
    assert (result.anchor_x, result.anchor_y) == (3, 2)
    assert result.used_feet == 10
    assert result.budget_feet == 30
    assert result.remaining_feet == 20
    assert result.diagonal_steps_used == 1
    assert result.position_revision == 2
    assert result.board_revision == 2

    position = table.board.board_repository.get_position(char_entry)
    assert position is not None
    assert (position.anchor_x, position.anchor_y) == (3, 2)
    assert position.revision == 2
    assert _bookkeeping(table, char_entry) == (10, 1, 30, {})

    with table.engine.connect() as conn:
        payload = conn.execute(
            select(session_events.c.payload, session_events.c.visibility).where(
                session_events.c.kind == "combat.movement_committed"
            )
        ).mappings().one()
    assert payload["visibility"] == "public"
    data = dict(payload["payload"])
    assert data["entry_id"] == str(char_entry)
    assert (data["anchor_x"], data["anchor_y"]) == (3, 2)
    assert data["used_feet"] == 10


def test_confirm_is_idempotent_on_retry() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    first = _confirm(
        table, table.player_actor, char_entry, (1, 1), (2, 1),
        idempotency_key="retry-me",
    )
    second = _confirm(
        table, table.player_actor, char_entry, (1, 1), (2, 1),
        idempotency_key="retry-me",
    )
    assert second == first
    assert _movement_event_count(table) == 1
    position = table.board.board_repository.get_position(char_entry)
    assert position is not None and position.revision == 2
    assert _bookkeeping(table, char_entry)[0] == 5


def test_confirm_rejects_stale_revisions_with_zero_side_effects() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    with pytest.raises(CombatMovementStaleError):
        _confirm(
            table, table.player_actor, char_entry, (1, 1), (2, 1),
            expected_position_revision=99,
        )
    with pytest.raises(CombatMovementStaleError):
        _confirm(
            table, table.player_actor, char_entry, (1, 1), (2, 1),
            expected_board_revision=99,
        )
    position = table.board.board_repository.get_position(char_entry)
    assert position is not None and (position.anchor_x, position.anchor_y) == (1, 1)
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})
    assert _movement_event_count(table) == 0


def test_confirm_rejects_illegal_path_with_zero_side_effects() -> None:
    from datetime import datetime, timezone
    from uuid import uuid4

    from sqlalchemy import insert

    from app.persistence.battle_maps.tables import battle_map_walls, battle_maps

    table = setup_tactical_table()
    map_id = uuid4()
    now = datetime.now(timezone.utc)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_maps).values(
            id=map_id, room_id=table.room_id, name="WallRoom",
            source_kind="blank", image_asset_id=None,
            width_cells=12, height_cells=12,
            grid_pixel_size=None, grid_offset_x=None, grid_offset_y=None,
            revision=1, created_at=now, updated_at=now,
        ))
        conn.execute(insert(battle_map_walls).values(
            id=uuid4(), battle_map_id=map_id,
            x1=3, y1=0, x2=3, y2=5, visibility="public",
        ))
    _start(table, battle_map_id=map_id)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry, char_at=(2, 2))

    with pytest.raises(CombatMovementInvalidError):
        _confirm(table, table.player_actor, char_entry, (2, 2), (3, 2))
    position = table.board.board_repository.get_position(char_entry)
    assert position is not None and (position.anchor_x, position.anchor_y) == (2, 2)
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})
    assert _movement_event_count(table) == 0


# ----------------------------------------------------------------------
# B.4 — budget, dash, split movement, lifecycle resets


def test_split_movement_across_attack_keeps_bookkeeping() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    service = _movement(table)

    first = service.confirm(
        table.player_actor, char_entry,
        ConfirmMovementInput(
            entry_id=char_entry,
            path=_path((1, 1), (2, 1), (3, 1)),
            expected_position_revision=1, expected_board_revision=1,
        ),
    )
    assert first.used_feet == 10

    table.combat.use_action(
        table.player_actor,
        CombatActionInput(
            entry_id=char_entry, action_kind=CombatActionKind.ATTACK_BUDGET,
            economy_cost=CombatEconomyCost.ACTION,
        ),
    )
    # Board revisions are unchanged by the attack; the position revision bumped once.
    second = service.confirm(
        table.player_actor, char_entry,
        ConfirmMovementInput(
            entry_id=char_entry,
            path=_path((3, 1), (4, 1), (5, 1)),
            expected_position_revision=2, expected_board_revision=2,
        ),
    )
    assert second.used_feet == 20
    assert second.remaining_feet == 10
    assert _bookkeeping(table, char_entry)[:3] == (20, 0, 30)


def test_dash_after_partial_move_adds_budget_without_touching_used() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1))
    table.combat.use_action(
        table.player_actor,
        CombatActionInput(
            entry_id=char_entry, action_kind=CombatActionKind.DASH,
            economy_cost=CombatEconomyCost.ACTION,
        ),
    )
    # Budget was 30, dash adds another 30; used feet and diagonal parity untouched.
    assert _bookkeeping(table, char_entry)[:3] == (10, 0, 60)


def test_dash_before_move_grants_base_plus_dash() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    table.combat.use_action(
        table.player_actor,
        CombatActionInput(
            entry_id=char_entry, action_kind=CombatActionKind.DASH,
            economy_cost=CombatEconomyCost.ACTION,
        ),
    )
    assert _bookkeeping(table, char_entry)[:3] == (0, 0, 30)
    result = _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1), (5, 1))
    assert result.budget_feet == 60
    assert result.used_feet == 20
    assert result.remaining_feet == 40


def test_advance_turn_resets_movement_bookkeeping() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert _bookkeeping(table, char_entry)[:3] == (5, 0, 30)

    table.combat.advance_turn(table.dm_actor)
    assert _bookkeeping(table, monster_entry) == (0, 0, 0, {})
    table.combat.advance_turn(table.dm_actor)
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})


def test_monster_speed_parses_from_rules_snapshot() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry, char_first=False)

    # Goblin quick enemy has speed {"walk": "30 ft."}: one step of 30 ft budget.
    result = _confirm(
        table, table.dm_actor, monster_entry,
        (8, 8), (7, 8), (6, 8), (5, 8), (4, 8), (3, 8), (2, 8),
    )
    assert result.budget_feet == 30
    assert result.used_feet == 30
    assert result.remaining_feet == 0
    with pytest.raises(CombatMovementInvalidError):
        _confirm(
            table, table.dm_actor, monster_entry,
            (2, 8), (1, 8),
            expected_position_revision=2, expected_board_revision=2,
        )


# ----------------------------------------------------------------------
# B.5 — stale preview: the world moved under the plan


def test_confirm_rejects_stale_board_after_door_change() -> None:
    table = setup_tactical_table()
    map_id = insert_battle_map(table)
    _start(table, battle_map_id=map_id)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    preview = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert preview.valid

    board = table.board.get_board(table.dm_actor)
    door_id = next(d.door_id for d in board.doors if d.door_id is not None)
    table.board.update_door_state(
        table.dm_actor, door_id,
        UpdateDoorStateInput(state="open", expected_runtime_revision=board.runtime_revision),
    )
    with pytest.raises(CombatMovementStaleError):
        _confirm(
            table, table.player_actor, char_entry, (1, 1), (2, 1),
            expected_position_revision=preview.position_revision,
            expected_board_revision=preview.board_revision,
        )
    assert _movement_event_count(table) == 0


def test_confirm_rejects_stale_position_after_token_moved() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    preview = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert preview.valid

    # The DM moves the token via a confirmed movement; the preview revision is stale.
    _confirm(
        table, table.dm_actor, char_entry, (1, 1), (1, 2),
        expected_position_revision=preview.position_revision,
        expected_board_revision=preview.board_revision,
    )
    with pytest.raises(CombatMovementStaleError):
        _confirm(
            table, table.player_actor, char_entry, (1, 1), (2, 1),
            expected_position_revision=preview.position_revision,
            expected_board_revision=preview.board_revision,
        )
    position = table.board.board_repository.get_position(char_entry)
    assert position is not None and (position.anchor_x, position.anchor_y) == (1, 2)
    assert _movement_event_count(table) == 1


# ----------------------------------------------------------------------
# B.6 — authority, turn gate, quick gate, hidden secrecy


def test_player_cannot_move_other_character_or_monster() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    # The monster's turn: the player may not move it, nor anyone else's character.
    with pytest.raises(TableEventActorUnauthorizedError):
        _preview(table, table.player_actor, monster_entry, (8, 8), (7, 8))
    with pytest.raises(TableEventActorUnauthorizedError):
        _confirm(table, table.player_actor, monster_entry, (8, 8), (7, 8))

    # A session participant who controls no character may not move anything.
    from app.domain.rooms.table_events import TableActorKind

    stranger_actor = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        session_id=table.session_id,
        seat_id=table.player_actor.seat_id,
        controlled_seat_ids=(),
        role="player",
        is_current_dm=False,
    )
    with pytest.raises(TableEventActorUnauthorizedError):
        _confirm(table, stranger_actor, char_entry, (1, 1), (2, 1))
    assert _movement_event_count(table) == 0


def test_cannot_move_off_turn() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry, char_first=False)

    # Monster's turn: moving the character is rejected even by the DM proxy.
    with pytest.raises(CombatStateConflictError):
        _confirm(table, table.dm_actor, char_entry, (1, 1), (2, 1))
    assert _movement_event_count(table) == 0


def test_quick_combat_rejects_movement() -> None:
    table = setup_tactical_table()
    table.combat.start_quick_combat(table.dm_actor, StartCombatInput())
    with pytest.raises(CombatStateConflictError):
        _preview(table, table.dm_actor, _character_entry_id(table), (1, 1), (2, 1))


def test_hidden_monster_does_not_block_player_preview_but_blocks_dm() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    hidden_entry = _add_monster(table, visibility="hidden")
    # Hidden goblin sits at (3,1); the player plans straight through it.
    _running(table, char_entry=char_entry, monster_entry=hidden_entry, monster_at=(3, 1))
    player_view = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1))
    assert player_view.valid

    dm_view = _preview(table, table.dm_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1))
    assert not dm_view.valid
    assert dm_view.failure == "creature_blocked"


def test_player_confirm_into_hidden_blocker_fails_generic() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    hidden_entry = _add_monster(table, visibility="hidden")
    _running(table, char_entry=char_entry, monster_entry=hidden_entry, monster_at=(3, 1))

    preview = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1))
    assert preview.valid
    with pytest.raises(CombatMovementInvalidError) as exc_info:
        _confirm(
            table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1),
            expected_position_revision=preview.position_revision,
            expected_board_revision=preview.board_revision,
        )
    # B1: generic invalid; the response carries no hidden identity or coordinates.
    assert str(hidden_entry) not in str(exc_info.value)
    assert "(3, 1)" not in str(exc_info.value)
    assert _movement_event_count(table) == 0
    position = table.board.board_repository.get_position(char_entry)
    assert position is not None and (position.anchor_x, position.anchor_y) == (1, 1)


def test_hidden_monster_movement_event_is_dm_only() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    hidden_entry = _add_monster(table, visibility="hidden")
    _running(table, char_entry=char_entry, monster_entry=hidden_entry, char_first=False)

    result = _confirm(table, table.dm_actor, hidden_entry, (8, 8), (7, 8))
    assert (result.anchor_x, result.anchor_y) == (7, 8)
    assert _movement_event_visibility(table) == "dm_only"


def test_dm_proxy_movement_keeps_dm_audit_subject() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    # DM moves the player's character on the character's turn: the event is
    # audited as a DM proxy with the acting DM seat and the subject seat.
    result = _confirm(table, table.dm_actor, char_entry, (1, 1), (2, 1))
    assert (result.anchor_x, result.anchor_y) == (2, 1)
    with table.engine.connect() as conn:
        row = conn.execute(
            select(session_events.c.acting_seat_id, session_events.c.subject_seat_id,
                   session_events.c.execution_mode)
            .where(session_events.c.kind == "combat.movement_committed")
        ).mappings().one()
    assert row["acting_seat_id"] == table.dm_actor.seat_id
    assert row["subject_seat_id"] == table.player_actor.seat_id
    assert row["execution_mode"] == "dm_proxy"


def test_dm_can_proxy_any_entry_under_normal_rules() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)

    # DM moves the player's character on the character's turn: allowed.
    result = _confirm(table, table.dm_actor, char_entry, (1, 1), (2, 1))
    assert (result.anchor_x, result.anchor_y) == (2, 1)


# ----------------------------------------------------------------------
# error-code mapping


def test_movement_error_codes() -> None:
    invalid = _map_combat_error(CombatMovementInvalidError("the movement path is not legal"))
    assert (invalid.status_code, invalid.code) == (400, "combat_movement_invalid")
    stale = _map_combat_error(CombatMovementStaleError("stale"))
    assert (stale.status_code, stale.code) == (409, "combat_movement_stale")
