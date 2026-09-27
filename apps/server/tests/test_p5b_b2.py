"""P5-B B2: hidden interruption, DM reposition, B1 review fixes, test gaps (backend only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update

from app.api.rooms.combat import _map_combat_error
from app.domain.combat.board import (
    CombatPlacementInvalidError,
    PlaceCombatantInput,
    UpdateDoorStateInput,
)
from app.domain.combat.event_projection import project_combat_event_payload
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    CombatActionInput,
    CombatActionKind,
    CombatEconomyCost,
    CombatNotFoundError,
    CombatStateConflictError,
    ResolveInitiativeOrderInput,
    StartTacticalCombatInput,
)
from app.domain.combat.movement import (
    CombatMovementConflictError,
    CombatMovementInvalidError,
    CombatMovementStaleError,
    ConfirmMovementInput,
    MovementAnchorInput,
    MovementService,
    PreviewMovementInput,
    RepositionInput,
)
from app.domain.rooms.table_events import TableActorContext, TableEventActorUnauthorizedError
from app.domain.spatial import (
    GridCell,
    PathValidationRequest,
    validate_movement_path,
)
from app.domain.spatial.primitives import BarrierSegment, Footprint
from app.persistence.combat.tables import combat_entries
from app.persistence.battle_maps.tables import (
    battle_map_doors,
    battle_map_terrain,
    battle_maps,
)
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


def _add_monster(table: TacticalTable, *, visibility: str = "public", walk: str = "30 ft.") -> UUID:
    instance = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name="Goblin",
        armor_class=15, max_hp=7, speed={"walk": walk},
        visibility=visibility,
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=instance.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return next(e.id for e in view.entries if e.subject_kind == "monster")


def _patch_character_state(table: TacticalTable, mutate) -> None:
    """Apply a JSON-level patch to the fixture character's state payload.

    Follows the established character-state test pattern: dump, mutate,
    re-validate, and write back with a revision bump.
    """
    from app.content import load_default_content_registry
    from app.domain.character.schemas import CharacterState
    from app.persistence.characters import CharacterRepository, character_states

    repo = CharacterRepository(table.engine, load_default_content_registry())
    character = repo.load_character(table.character_id)
    payload = character.state.model_dump(mode="json")
    mutate(payload)
    CharacterState.model_validate(payload)
    with table.engine.begin() as conn:
        conn.execute(
            update(character_states)
            .where(character_states.c.character_id == table.character_id)
            .values(
                state_payload=payload,
                state_revision=character_states.c.state_revision + 1,
            )
        )


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


def _position(table: TacticalTable, entry_id: UUID) -> tuple[int, int, int]:
    position = table.board.board_repository.get_position(entry_id)
    assert position is not None
    return position.anchor_x, position.anchor_y, position.revision


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


def _reposition(
    table: TacticalTable,
    actor: TableActorContext,
    entry_id: UUID,
    x: int,
    y: int,
    *,
    reason: str = "DM correction",
    expected_position_revision: int = 1,
    idempotency_key: str | None = None,
):
    return _movement(table).reposition(
        actor, entry_id,
        RepositionInput(
            entry_id=entry_id,
            anchor_x=x, anchor_y=y,
            reason=reason,
            expected_position_revision=expected_position_revision,
            idempotency_key=idempotency_key,
        ),
    )


def _event_count(table: TacticalTable, kind: str) -> int:
    with table.engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(session_events).where(
                session_events.c.kind == kind
            )
        ).scalar_one()


def _latest_event(table: TacticalTable, kind: str) -> dict:
    with table.engine.connect() as conn:
        row = conn.execute(
            select(
                session_events.c.payload,
                session_events.c.visibility,
                session_events.c.acting_seat_id,
                session_events.c.subject_seat_id,
                session_events.c.execution_mode,
            ).where(session_events.c.kind == kind)
            .order_by(session_events.c.seq.desc())
            .limit(1)
        ).mappings().one()
    return dict(row)


def _use_action(
    table: TacticalTable, actor: TableActorContext, entry_id: UUID,
    action_kind: CombatActionKind, economy_cost: CombatEconomyCost,
):
    return table.combat.use_action(
        actor, CombatActionInput(
            entry_id=entry_id, action_kind=action_kind,
            economy_cost=economy_cost, payload={},
        ),
    )


def _stranger_actor(table: TacticalTable) -> TableActorContext:
    from app.domain.rooms.table_events import TableActorKind

    return TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        session_id=table.session_id,
        seat_id=table.player_actor.seat_id,
        controlled_seat_ids=(),
        role="player",
        is_current_dm=False,
    )


# ======================================================================
# B.1 bookkeeping
# ======================================================================


def test_orthogonal_move_costs_5_feet() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    result = _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert result.outcome == "committed"
    assert result.used_feet == 5
    assert result.diagonal_steps_used == 0
    assert result.remaining_feet == 25


def test_diagonal_steps_alternate_5_10_5_10() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    result = _confirm(
        table, table.player_actor, char_entry,
        (1, 1), (2, 2), (3, 3), (4, 4), (5, 5),
    )
    assert result.outcome == "committed"
    # 5 + 10 + 5 + 10 = 30: the full walk budget.
    assert result.used_feet == 30
    assert result.diagonal_steps_used == 4
    assert result.remaining_feet == 0


def test_move_attack_move_keeps_diagonal_parity() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    first = _confirm(table, table.player_actor, char_entry, (1, 1), (2, 2), (3, 3))
    assert first.used_feet == 15  # 5 + 10
    assert first.diagonal_steps_used == 2
    _use_action(
        table, table.player_actor, char_entry,
        CombatActionKind.ATTACK_BUDGET, CombatEconomyCost.ACTION,
    )
    second = _confirm(
        table, table.player_actor, char_entry, (3, 3), (4, 4),
        expected_position_revision=2, expected_board_revision=2,
    )
    # The attack did not reset diagonal parity: the 3rd diagonal costs 5.
    assert second.used_feet == 20
    assert second.diagonal_steps_used == 3


def test_new_turn_resets_movement_bookkeeping() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 2))
    assert _bookkeeping(table, char_entry)[:3] == (5, 1, 30)
    table.combat.advance_turn(table.dm_actor)  # monster's turn
    assert _bookkeeping(table, char_entry)[:3] == (5, 1, 30)
    table.combat.advance_turn(table.dm_actor)  # char's turn, new round
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})


def test_dash_increases_budget_without_resetting_parity() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 2))
    _use_action(
        table, table.player_actor, char_entry,
        CombatActionKind.DASH, CombatEconomyCost.ACTION,
    )
    # Dash stacks the budget but never touches used feet or diagonal parity.
    assert _bookkeeping(table, char_entry)[:3] == (5, 1, 60)
    result = _confirm(
        table, table.player_actor, char_entry, (2, 2), (3, 3),
        expected_position_revision=2, expected_board_revision=2,
    )
    # Second diagonal of the turn still costs 10.
    assert result.used_feet == 15
    assert result.diagonal_steps_used == 2
    assert result.remaining_feet == 45


def test_bonus_action_and_extra_attack_do_not_reset_movement() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1))
    _use_action(
        table, table.player_actor, char_entry,
        CombatActionKind.ATTACK_BUDGET, CombatEconomyCost.ACTION,
    )
    _use_action(
        table, table.player_actor, char_entry,
        CombatActionKind.FREEFORM, CombatEconomyCost.BONUS_ACTION,
    )
    try:
        _use_action(
            table, table.player_actor, char_entry,
            CombatActionKind.ATTACK_BUDGET, CombatEconomyCost.ACTION,
        )
    except CombatStateConflictError:
        # The entry's attack budget may not allow a second attack; either way
        # the economy action must not reset movement bookkeeping.
        pass
    result = _confirm(
        table, table.player_actor, char_entry, (3, 1), (4, 1), (5, 1),
        expected_position_revision=2, expected_board_revision=2,
    )
    assert result.used_feet == 20  # 10 + 10
    assert result.diagonal_steps_used == 0
    assert result.budget_feet == 30


# ======================================================================
# B.2 terrain / wall / doors (service level)
# ======================================================================


def _blank_map_row(table: TacticalTable) -> UUID:
    map_id = uuid4()
    now = datetime.now(timezone.utc)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_maps).values(
            id=map_id, room_id=table.room_id, name="b2-test",
            source_kind="blank", image_asset_id=None,
            width_cells=12, height_cells=12,
            grid_pixel_size=None, grid_offset_x=None, grid_offset_y=None,
            revision=1, created_at=now, updated_at=now,
        ))
    return map_id


def _map_with_public_door(table: TacticalTable) -> UUID:
    map_id = _blank_map_row(table)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_map_doors).values(
            id=uuid4(), battle_map_id=map_id,
            x1=3, y1=1, x2=3, y2=2,
            default_state="closed", visibility="public",
        ))
    return map_id


def _map_with_terrain_kinds(table: TacticalTable) -> UUID:
    map_id = _blank_map_row(table)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_map_terrain).values(
            battle_map_id=map_id, x=2, y=1, terrain_kind="difficult",
        ))
        conn.execute(insert(battle_map_terrain).values(
            battle_map_id=map_id, x=4, y=1, terrain_kind="blocked",
        ))
    return map_id


def _door_id(table: TacticalTable) -> UUID:
    board = table.board.get_board(table.dm_actor)
    return next(iter(board.doors)).door_id


def _set_door(table: TacticalTable, door_id: UUID, state: str, expected_revision: int) -> int:
    table.board.update_door_state(
        table.dm_actor, door_id,
        UpdateDoorStateInput(state=state, expected_runtime_revision=expected_revision),
    )
    return expected_revision + 1


def test_public_door_closed_blocks_service_preview() -> None:
    table = setup_tactical_table()
    _start(table, battle_map_id=_map_with_public_door(table))
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    preview = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1))
    assert not preview.valid
    assert preview.failure == "wall_or_door"
    with pytest.raises(CombatMovementInvalidError):
        _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1))
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})
    assert _position(table, char_entry) == (1, 1, 1)


def test_door_state_locked_blocks_open_and_broken_pass() -> None:
    table = setup_tactical_table()
    _start(table, battle_map_id=_map_with_public_door(table))
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    door_id = _door_id(table)

    revision = _set_door(table, door_id, "locked", expected_revision=1)
    preview = _preview(
        table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1),
    )
    assert not preview.valid  # locked still blocks

    revision = _set_door(table, door_id, "open", expected_revision=revision)
    preview = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1))
    assert preview.valid  # open passes

    revision = _set_door(table, door_id, "broken", expected_revision=revision)
    preview = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1))
    assert preview.valid  # broken passes
    assert revision == 4


def test_hidden_wall_does_not_block_player_preview_but_blocks_dm() -> None:
    table = setup_tactical_table()
    _start(table, battle_map_id=insert_battle_map(table))
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    # Place next to the hidden wall segment x in [10, 12], y = 10.
    _running(
        table, char_entry=char_entry, monster_entry=monster_entry,
        char_at=(10, 9), monster_at=(2, 8),
    )
    player_preview = _preview(
        table, table.player_actor, char_entry, (10, 9), (10, 10)
    )
    assert player_preview.valid  # the hidden wall is invisible to Players
    dm_preview = _preview(table, table.dm_actor, char_entry, (10, 9), (10, 10))
    assert not dm_preview.valid
    assert dm_preview.failure == "wall_or_door"
    # The Player preview carries no wall identity: no "hidden" marker and no
    # barrier segment fields (the preview only echoes the requested path).
    payload = json.dumps(player_preview.model_dump(mode="json"))
    assert "hidden" not in payload
    assert "x1" not in payload and "blocker" not in payload


def _map_with_hidden_interior_door(table: TacticalTable) -> UUID:
    # A hidden, closed, unrevealed door in the interior (edge y = 4 between
    # rows 3 and 4), so it actually blocks movement unlike the stock map's
    # boundary door.
    map_id = _blank_map_row(table)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_map_doors).values(
            id=uuid4(), battle_map_id=map_id,
            x1=5, y1=4, x2=6, y2=4,
            default_state="closed", visibility="hidden",
        ))
    return map_id


def test_unrevealed_hidden_door_does_not_block_player_preview_but_interrupts_confirm() -> None:
    table = setup_tactical_table()
    _start(table, battle_map_id=_map_with_hidden_interior_door(table))
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(
        table, char_entry=char_entry, monster_entry=monster_entry,
        char_at=(5, 3), monster_at=(2, 8),
    )
    # The unrevealed hidden door is invisible to the Player's movement plan:
    # the preview plans straight through it and leaks nothing about the door.
    preview = _preview(table, table.player_actor, char_entry, (5, 3), (5, 4))
    assert preview.valid
    payload = json.dumps(preview.model_dump(mode="json"))
    assert "hidden" not in payload
    # The DM plans against full truth and sees the closed door.
    dm_preview = _preview(table, table.dm_actor, char_entry, (5, 3), (5, 4))
    assert not dm_preview.valid
    assert dm_preview.failure == "wall_or_door"
    # But the full-truth Confirm still catches it: interrupted, generic reason.
    result = _confirm(
        table, table.player_actor, char_entry, (5, 3), (5, 4),
        expected_position_revision=1, expected_board_revision=1,
    )
    assert result.outcome == "interrupted"
    assert _position(table, char_entry) == (5, 3, 1)
    event = _latest_event(table, "combat.movement_interrupted")
    assert event["payload"]["blocker_type"] == "door"
    assert event["payload"]["blocker_id"] is not None


def test_difficult_terrain_costs_double_and_blocked_rejects_at_service_level() -> None:
    table = setup_tactical_table()
    _start(table, battle_map_id=_map_with_terrain_kinds(table))
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    preview = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert preview.valid
    assert preview.steps[0].cost_feet == 10  # difficult terrain doubles
    assert preview.steps[0].difficult
    result = _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert result.outcome == "committed"
    assert result.used_feet == 10
    blocked_preview = _preview(
        table, table.player_actor, char_entry, (2, 1), (3, 1), (4, 1)
    )
    assert not blocked_preview.valid
    assert blocked_preview.failure == "blocked_terrain"


# ======================================================================
# B.4 bookkeeping resets across lifecycle transitions
# ======================================================================


def test_finalize_initiative_resets_movement_bookkeeping() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert _bookkeeping(table, char_entry)[:3] == (5, 0, 30)
    # Drive the combat back to initiative_pending and re-finalize: the same
    # production path must clear the four movement fields.
    from app.persistence.combat.tables import combats

    with table.engine.begin() as conn:
        conn.execute(
            update(combats).where(combats.c.campaign_id == table.campaign_id)
            .values(status="initiative_pending")
        )
    table.combat.resolve_initiative_order(
        table.dm_actor, ResolveInitiativeOrderInput(ordered_entry_ids=(char_entry, monster_entry))
    )
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})


def test_advance_turn_resets_movement_bookkeeping() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 2))
    table.combat.advance_turn(table.dm_actor)  # monster's turn
    table.combat.advance_turn(table.dm_actor)  # char's turn again
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})


def test_end_combat_resets_movement_bookkeeping() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 2))
    table.combat.end_combat(table.dm_actor)
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})


def test_withdraw_entry_resets_movement_bookkeeping() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 2))
    # Withdrawal requires the entry not to hold the current turn.
    table.combat.advance_turn(table.dm_actor)
    table.combat.withdraw_entry(table.dm_actor, char_entry)
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})


def test_remove_entry_resets_movement_bookkeeping() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 2))
    # Removal requires the entry not to hold the current turn.
    table.combat.advance_turn(table.dm_actor)
    table.combat.remove_entry(table.dm_actor, char_entry)
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})


# ======================================================================
# B.5 stale previews
# ======================================================================


def test_confirm_rejects_stale_position_after_reposition() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    preview = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert preview.valid
    _reposition(table, table.dm_actor, char_entry, 5, 5)
    with pytest.raises(CombatMovementStaleError):
        _confirm(
            table, table.player_actor, char_entry, (1, 1), (2, 1),
            expected_position_revision=preview.position_revision,
            expected_board_revision=preview.board_revision,
        )
    # Zero side effects from the stale confirm.
    assert _position(table, char_entry) == (5, 5, 2)
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})


def test_reposition_stale_revision_is_rejected() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    with pytest.raises(CombatMovementStaleError):
        _reposition(table, table.dm_actor, char_entry, 5, 5, expected_position_revision=99)
    assert _position(table, char_entry) == (1, 1, 1)
    assert _event_count(table, "combat.position_corrected") == 0


# ======================================================================
# B.7 hidden interruption
# ======================================================================


def _hidden_monster_table() -> tuple[TacticalTable, UUID, UUID]:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    hidden_entry = _add_monster(table, visibility="hidden")
    _running(table, char_entry=char_entry, monster_entry=hidden_entry, monster_at=(3, 1))
    return table, char_entry, hidden_entry


def test_player_confirm_interrupted_by_hidden_monster() -> None:
    table, char_entry, hidden_entry = _hidden_monster_table()
    preview = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1))
    assert preview.valid  # caller-visible: the hidden monster is not there
    result = _confirm(
        table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1),
        expected_position_revision=preview.position_revision,
        expected_board_revision=preview.board_revision,
        idempotency_key="interrupt-once",
    )
    assert result.outcome == "interrupted"
    # Zero movement side effects: not moved, bookkeeping untouched.
    assert (result.anchor_x, result.anchor_y) == (1, 1)
    assert result.used_feet == 0
    assert result.diagonal_steps_used == 0
    assert result.position_revision == 1
    assert _position(table, char_entry) == (1, 1, 1)
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})
    assert _event_count(table, "combat.movement_committed") == 0
    # One interruption event, DM-auditable.
    assert _event_count(table, "combat.movement_interrupted") == 1
    event = _latest_event(table, "combat.movement_interrupted")
    assert event["visibility"] == "public"
    payload = dict(event["payload"])
    assert payload["entry_id"] == str(char_entry)
    assert payload["reason"] == "path_obstructed"
    assert payload["step_index"] == 2  # the (3, 1) step
    assert payload["blocker_type"] == "monster"
    assert payload["blocker_id"] == str(hidden_entry)
    assert event["subject_seat_id"] == table.player_actor.controlled_seat_ids[0]
    assert event["execution_mode"] == "self"  # player moving their own character


def test_interrupted_retry_replays_original_snapshot_after_state_change() -> None:
    table, char_entry, hidden_entry = _hidden_monster_table()
    first = _confirm(
        table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1),
        idempotency_key="interrupt-snapshot",
    )
    assert first.outcome == "interrupted"
    assert (first.anchor_x, first.anchor_y) == (1, 1)
    assert first.used_feet == 0
    # The DM moves the token afterwards; a retry with the same key must still
    # replay the original interruption snapshot, not the current state.
    _reposition(table, table.dm_actor, char_entry, 7, 7)
    assert _position(table, char_entry) == (7, 7, 2)
    replayed = _confirm(
        table, table.player_actor, char_entry, (1, 1), (2, 1),
        idempotency_key="interrupt-snapshot",
    )
    assert replayed.outcome == "interrupted"
    assert (replayed.anchor_x, replayed.anchor_y) == (1, 1)
    assert replayed.used_feet == 0
    assert replayed.position_revision == 1
    assert replayed.board_revision == 1
    assert _event_count(table, "combat.movement_interrupted") == 1


def test_interrupted_confirm_response_json_has_no_hidden_details() -> None:
    table, char_entry, hidden_entry = _hidden_monster_table()
    result = _confirm(
        table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1),
        idempotency_key="interrupt-json",
    )
    assert result.outcome == "interrupted"
    payload = json.dumps(result.model_dump(mode="json"))
    assert str(hidden_entry) not in payload
    assert "monster" not in payload
    assert '"outcome": "interrupted"' in payload


def test_interrupted_event_projection_is_player_safe_and_dm_complete() -> None:
    table, char_entry, hidden_entry = _hidden_monster_table()
    _confirm(
        table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1),
        idempotency_key="interrupt-projection",
    )
    raw = dict(_latest_event(table, "combat.movement_interrupted")["payload"])
    hidden_ids = frozenset({str(hidden_entry)})
    player_view = project_combat_event_payload(
        "combat.movement_interrupted", raw, audience="player", hidden_entry_ids=hidden_ids
    )
    assert player_view == {
        "combat_id": raw["combat_id"],
        "entry_id": raw["entry_id"],
        "reason": "path_obstructed",
    }
    assert str(hidden_entry) not in json.dumps(player_view)
    dm_view = project_combat_event_payload(
        "combat.movement_interrupted", raw, audience="dm", hidden_entry_ids=hidden_ids
    )
    assert dm_view["step_index"] == 2
    assert dm_view["blocker_type"] == "monster"
    assert dm_view["blocker_id"] == str(hidden_entry)
    # The DM payload carries the confirm snapshot used for retry replay.
    assert dm_view["anchor_x"] == 1 and dm_view["anchor_y"] == 1
    assert dm_view["used_feet"] == 0
    assert dm_view["budget_feet"] == 30
    assert dm_view["diagonal_steps_used"] == 0
    assert dm_view["position_revision"] == 1
    assert dm_view["board_revision"] == 1


def test_interrupted_retry_returns_same_result_without_duplicate_event() -> None:
    table, char_entry, hidden_entry = _hidden_monster_table()
    first = _confirm(
        table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1),
        idempotency_key="interrupt-retry",
    )
    assert first.outcome == "interrupted"
    second = _confirm(
        table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1),
        idempotency_key="interrupt-retry",
    )
    assert second == first
    assert _event_count(table, "combat.movement_interrupted") == 1
    assert _position(table, char_entry) == (1, 1, 1)


def test_player_confirm_interrupted_by_hidden_wall() -> None:
    table = setup_tactical_table()
    _start(table, battle_map_id=insert_battle_map(table))
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    # Next to the hidden wall segment x in [10, 12], y = 10.
    _running(
        table, char_entry=char_entry, monster_entry=monster_entry,
        char_at=(10, 9), monster_at=(2, 8),
    )
    preview = _preview(table, table.player_actor, char_entry, (10, 9), (10, 10))
    assert preview.valid  # the hidden wall is invisible to Players
    result = _confirm(
        table, table.player_actor, char_entry, (10, 9), (10, 10),
        expected_position_revision=preview.position_revision,
        expected_board_revision=preview.board_revision,
        idempotency_key="interrupt-wall",
    )
    assert result.outcome == "interrupted"
    assert (result.anchor_x, result.anchor_y) == (10, 9)
    assert _position(table, char_entry) == (10, 9, 1)
    payload = dict(_latest_event(table, "combat.movement_interrupted")["payload"])
    assert payload["blocker_type"] == "wall"
    assert payload["blocker_id"]  # the hidden wall's baseline id, DM-only detail
    player_view = project_combat_event_payload(
        "combat.movement_interrupted", payload, audience="player", hidden_entry_ids=frozenset()
    )
    assert set(player_view) == {"combat_id", "entry_id", "reason"}


def test_dm_caller_is_never_interrupted() -> None:
    table, char_entry, hidden_entry = _hidden_monster_table()
    # DM proxy on a clear path commits.
    result = _confirm(
        table, table.dm_actor, char_entry, (1, 1), (2, 1),
        idempotency_key="dm-clear",
    )
    assert result.outcome == "committed"
    assert (result.anchor_x, result.anchor_y) == (2, 1)
    # The DM sees Server truth in the caller-visible layer too, so a path
    # blocked by a hidden monster is a plain 400 — never an interruption.
    with pytest.raises(CombatMovementInvalidError):
        _confirm(
            table, table.dm_actor, char_entry, (2, 1), (3, 1), (4, 1),
            expected_position_revision=2, expected_board_revision=2,
        )
    assert _event_count(table, "combat.movement_interrupted") == 0


def test_confirm_idempotent_replay_returns_committed_view() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    first = _confirm(
        table, table.player_actor, char_entry, (1, 1), (2, 1),
        idempotency_key="replay-key",
    )
    assert first.outcome == "committed"
    second = _confirm(
        table, table.player_actor, char_entry, (1, 1), (2, 1),
        idempotency_key="replay-key",
    )
    assert second == first
    assert _event_count(table, "combat.movement_committed") == 1
    assert _position(table, char_entry) == (2, 1, 2)


# ======================================================================
# B1 review fixes: replay authorization order + key conflicts
# ======================================================================


def test_confirm_replay_happens_after_authorization() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1), idempotency_key="auth-key")
    stranger = _stranger_actor(table)
    # A stranger must not be able to replay someone else's key: the replay
    # lookup runs after _running_entry/_authorize_entry.
    with pytest.raises(TableEventActorUnauthorizedError):
        _confirm(
            table, stranger, char_entry, (1, 1), (2, 1), idempotency_key="auth-key"
        )
    assert _event_count(table, "combat.movement_committed") == 1


def test_confirm_rejects_idempotency_key_entry_mismatch() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1), idempotency_key="dup-key")
    table.combat.advance_turn(table.dm_actor)  # monster's turn
    # The same key reused by a different entry is a conflict, not a replay.
    with pytest.raises(CombatMovementConflictError):
        _confirm(
            table, table.dm_actor, monster_entry, (8, 8), (7, 8),
            idempotency_key="dup-key",
        )
    # Zero side effects: the monster never moved, no new event.
    assert _position(table, monster_entry) == (8, 8, 1)
    assert _event_count(table, "combat.movement_committed") == 1


def test_confirm_rejects_idempotency_key_actor_mismatch() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1), idempotency_key="seat-key")
    # The DM proxies the same entry with the player's key: acting seat differs.
    with pytest.raises(CombatMovementConflictError):
        _confirm(
            table, table.dm_actor, char_entry, (2, 1), (3, 1),
            expected_position_revision=2, expected_board_revision=2,
            idempotency_key="seat-key",
        )
    assert _position(table, char_entry) == (2, 1, 2)
    assert _event_count(table, "combat.movement_committed") == 1


def test_movement_conflict_maps_to_409() -> None:
    err = _map_combat_error(CombatMovementConflictError("key conflict"))
    assert (err.status_code, err.code) == (409, "combat_movement_conflict")


def test_confirm_replay_view_is_not_overwritten_by_request() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    first = _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1), idempotency_key="view-key")
    # A retry goes through the same entry_id but the view must come from the
    # stored payload, never from the request path.
    second = _confirm(
        table, table.player_actor, char_entry, (2, 1), (3, 1),
        expected_position_revision=2, expected_board_revision=2,
        idempotency_key="view-key",
    )
    assert second == first
    assert (second.anchor_x, second.anchor_y) == (2, 1)
    assert second.used_feet == 5


# ======================================================================
# Actor isolation
# ======================================================================


def test_non_participant_preview_and_confirm_rejected() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    stranger = _stranger_actor(table)
    with pytest.raises(TableEventActorUnauthorizedError):
        _preview(table, stranger, char_entry, (1, 1), (2, 1))
    with pytest.raises(TableEventActorUnauthorizedError):
        _confirm(table, stranger, char_entry, (1, 1), (2, 1))
    assert _event_count(table, "combat.movement_committed") == 0
    assert _event_count(table, "combat.movement_interrupted") == 0
    assert _position(table, char_entry) == (1, 1, 1)


def test_actor_from_another_campaign_is_rejected() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    from app.domain.rooms.table_events import TableActorKind

    outsider = TableActorContext(
        actor_kind=TableActorKind.HUMAN,
        room_id=table.room_id,
        campaign_id=uuid4(),  # no combat is active in this campaign
        session_id=table.session_id,
        seat_id=table.player_actor.seat_id,
        controlled_seat_ids=(table.player_actor.seat_id,),
        role="player",
        is_current_dm=False,
    )
    with pytest.raises(CombatNotFoundError):
        _preview(table, outsider, char_entry, (1, 1), (2, 1))
    with pytest.raises(CombatNotFoundError):
        _confirm(table, outsider, char_entry, (1, 1), (2, 1))
    assert _position(table, char_entry) == (1, 1, 1)


# ======================================================================
# B1 review fix: multi-cell diagonal corner sweep
# ======================================================================


def _corner_request(**overrides) -> PathValidationRequest:
    params: dict = {
        "start": GridCell(0, 0),
        "anchors": (GridCell(0, 0), GridCell(1, 1)),
        "footprint": Footprint(2, 2),
        "mover_size_rank": 3,
        "width_cells": 12,
        "height_cells": 12,
        "blocked_cells": frozenset(),
        "difficult_cells": frozenset(),
        "barriers": (),
        "creatures": (),
        "budget_feet": 30,
        "diagonal_steps_used": 0,
    }
    params.update(overrides)
    return PathValidationRequest(**params)


def test_validator_rejects_large_footprint_diagonal_corner_cut() -> None:
    # A Large (2x2) mover at (0, 0) stepping diagonally to (1, 1) sweeps its
    # leading corner (2, 0) — a blocked corner cell must reject the step.
    result = validate_movement_path(_corner_request(
        blocked_cells=frozenset({GridCell(2, 0)}),
    ))
    assert not result.valid
    assert result.failure == "wall_or_door"
    assert result.failure_step_index == 1


def test_validator_large_diagonal_wall_on_leading_edge() -> None:
    # A wall segment sitting on the footprint's leading edge (x = 2, y 0..1)
    # blocks the Large mover's diagonal even though the anchor path never
    # crosses it.
    result = validate_movement_path(_corner_request(
        barriers=(BarrierSegment(x1=2, y1=0, x2=2, y2=1),),
    ))
    assert not result.valid
    assert result.failure == "wall_or_door"


def test_validator_large_diagonal_clear_path_passes() -> None:
    result = validate_movement_path(_corner_request())
    assert result.valid
    assert result.used_feet == 5  # first diagonal of the turn


# ======================================================================
# B.8 DM reposition
# ======================================================================


def test_dm_reposition_moves_without_budget_or_parity() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _confirm(table, table.player_actor, char_entry, (1, 1), (2, 2))
    assert _bookkeeping(table, char_entry)[:3] == (5, 1, 30)
    result = _reposition(
        table, table.dm_actor, char_entry, 5, 5, expected_position_revision=2
    )
    assert (result.anchor_x, result.anchor_y) == (5, 5)
    assert result.position_revision == 3
    assert result.board_revision == 3  # the earlier Confirm had bumped it to 2
    # Reposition is a correction, not movement: budget/parity untouched.
    assert _bookkeeping(table, char_entry)[:3] == (5, 1, 30)
    assert _position(table, char_entry) == (5, 5, 3)
    assert _event_count(table, "combat.movement_committed") == 1


def test_reposition_is_allowed_off_turn() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry, char_first=False)
    # It is the monster's turn; the DM may still correct the character.
    result = _reposition(table, table.dm_actor, char_entry, 5, 5)
    assert (result.anchor_x, result.anchor_y) == (5, 5)
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})


def test_player_reposition_is_rejected_with_zero_side_effects() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    with pytest.raises(TableEventActorUnauthorizedError):
        _reposition(table, table.player_actor, char_entry, 5, 5)
    assert _position(table, char_entry) == (1, 1, 1)
    assert _event_count(table, "combat.position_corrected") == 0


def test_ai_controller_reposition_is_rejected_with_zero_side_effects() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    ai_actor = table.player_actor.model_copy(update={"ai_controller_grant_id": uuid4()})
    with pytest.raises(TableEventActorUnauthorizedError):
        _reposition(table, ai_actor, char_entry, 5, 5)
    assert _position(table, char_entry) == (1, 1, 1)
    assert _event_count(table, "combat.position_corrected") == 0


def test_reposition_appends_audited_event_with_player_safe_projection() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _reposition(table, table.dm_actor, char_entry, 5, 5, reason="Token was mis-dropped")
    assert _event_count(table, "combat.position_corrected") == 1
    event = _latest_event(table, "combat.position_corrected")
    assert event["visibility"] == "public"
    payload = dict(event["payload"])
    assert payload["entry_id"] == str(char_entry)
    assert payload["anchor_x"] == 5 and payload["anchor_y"] == 5
    assert payload["reason"] == "Token was mis-dropped"
    assert payload["position_revision"] == 2
    assert payload["board_revision"] == 2
    # Audit: the acting DM seat, the subject's seat, proxy execution mode.
    assert event["acting_seat_id"] == table.dm_actor.seat_id
    assert event["subject_seat_id"] == table.player_actor.controlled_seat_ids[0]
    assert event["execution_mode"] == "dm_proxy"
    # Player projection drops the DM's audit reason.
    player_view = project_combat_event_payload(
        "combat.position_corrected", payload, audience="player", hidden_entry_ids=frozenset()
    )
    assert "reason" not in player_view
    assert player_view["entry_id"] == str(char_entry)
    dm_view = project_combat_event_payload(
        "combat.position_corrected", payload, audience="dm", hidden_entry_ids=frozenset()
    )
    assert dm_view["reason"] == "Token was mis-dropped"


def test_reposition_hidden_monster_event_is_dm_only() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    hidden_entry = _add_monster(table, visibility="hidden")
    _running(table, char_entry=char_entry, monster_entry=hidden_entry)
    _reposition(table, table.dm_actor, hidden_entry, 4, 4, reason="secret fix")
    event = _latest_event(table, "combat.position_corrected")
    assert event["visibility"] == "dm_only"
    assert dict(event["payload"])["entry_id"] == str(hidden_entry)


def test_reposition_rejects_bad_targets_with_zero_side_effects() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    # Occupied by the monster.
    with pytest.raises(CombatPlacementInvalidError):
        _reposition(table, table.dm_actor, char_entry, 8, 8)
    # Out of bounds.
    with pytest.raises(CombatPlacementInvalidError):
        _reposition(table, table.dm_actor, char_entry, 99, 99)
    assert _position(table, char_entry) == (1, 1, 1)
    assert _event_count(table, "combat.position_corrected") == 0
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})


def test_reposition_rejects_blocked_terrain() -> None:
    table = setup_tactical_table()
    _start(table, battle_map_id=_map_with_terrain_kinds(table))
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    with pytest.raises(CombatPlacementInvalidError):
        _reposition(table, table.dm_actor, char_entry, 4, 1)  # blocked terrain
    assert _position(table, char_entry) == (1, 1, 1)
    assert _event_count(table, "combat.position_corrected") == 0


def test_reposition_rejects_large_footprint_straddling_wall() -> None:
    from app.persistence.combat.tables import monster_instances

    table = setup_tactical_table()
    _start(table, battle_map_id=insert_battle_map(table))
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    # Make the monster Large (2x2 footprint) via its rules snapshot.
    with table.engine.begin() as conn:
        instance_id = conn.execute(
            select(combat_entries.c.monster_instance_id).where(
                combat_entries.c.id == monster_entry
            )
        ).scalar_one()
        snapshot = dict(conn.execute(
            select(monster_instances.c.rules_snapshot).where(
                monster_instances.c.id == instance_id
            )
        ).scalar_one())
        conn.execute(
            update(monster_instances).where(monster_instances.c.id == instance_id)
            .values(rules_snapshot={**snapshot, "size": "Large"})
        )
    _running(table, char_entry=char_entry, monster_entry=monster_entry, monster_at=(8, 8))
    # The stock map's hidden wall runs x in [10, 12] at y = 10: a Large token
    # anchored at (10, 9) would straddle it through the interior edge y = 10.
    with pytest.raises(CombatPlacementInvalidError):
        _reposition(table, table.dm_actor, monster_entry, 10, 9)
    assert _position(table, monster_entry) == (8, 8, 1)
    assert _event_count(table, "combat.position_corrected") == 0
    # A clear anchor works for the Large token.
    result = _reposition(table, table.dm_actor, monster_entry, 5, 5)
    assert (result.anchor_x, result.anchor_y) == (5, 5)


def test_reposition_next_to_wall_is_allowed() -> None:
    # A wall on the footprint's outer boundary does not block placement: a
    # creature may stand next to a wall.
    table = setup_tactical_table()
    _start(table, battle_map_id=insert_battle_map(table))
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(
        table, char_entry=char_entry, monster_entry=monster_entry,
        char_at=(2, 1), monster_at=(8, 8),
    )
    result = _reposition(table, table.dm_actor, char_entry, 2, 0)
    assert (result.anchor_x, result.anchor_y) == (2, 0)


def test_reposition_requires_nonblank_reason() -> None:
    char_entry = uuid4()
    with pytest.raises(ValidationError):
        RepositionInput(
            entry_id=char_entry, anchor_x=1, anchor_y=1, reason="",
            expected_position_revision=1,
        )
    with pytest.raises(ValidationError):
        RepositionInput(
            entry_id=char_entry, anchor_x=1, anchor_y=1, reason="x" * 501,
            expected_position_revision=1,
        )
    with pytest.raises(ValidationError):
        RepositionInput(
            entry_id=char_entry, anchor_x=1, anchor_y=1, reason="   ",
            expected_position_revision=1,
        )


def test_reposition_is_idempotent() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    first = _reposition(table, table.dm_actor, char_entry, 5, 5, idempotency_key="repo-once")
    second = _reposition(table, table.dm_actor, char_entry, 5, 5, idempotency_key="repo-once")
    assert second == first
    assert _event_count(table, "combat.position_corrected") == 1
    assert _position(table, char_entry) == (5, 5, 2)


def test_reposition_rejects_idempotency_key_entry_mismatch() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _reposition(table, table.dm_actor, char_entry, 5, 5, idempotency_key="repo-dup")
    with pytest.raises(CombatMovementConflictError):
        _reposition(table, table.dm_actor, monster_entry, 7, 7, idempotency_key="repo-dup")
    assert _position(table, monster_entry) == (8, 8, 1)
    assert _event_count(table, "combat.position_corrected") == 1


# ---------------------------------------------------------------------------
# Speed sources: explicit walk speed, speed_zero conditions, exhaustion
# ---------------------------------------------------------------------------

def test_explicit_walk_speed_sets_movement_budget() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table, walk="40 ft.")
    _running(
        table, char_entry=char_entry, monster_entry=monster_entry,
        char_first=False,
    )
    preview = _preview(table, table.dm_actor, monster_entry, (8, 8), (9, 8), (10, 8))
    assert preview.valid
    assert preview.budget_feet == 40
    assert preview.used_feet == 10


def test_grappled_condition_zeroes_movement_budget() -> None:
    from app.persistence.combat.special_attacks import GRAPPLED_REF

    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _patch_character_state(
        table, lambda payload: payload["conditions"].append({"condition_ref": GRAPPLED_REF})
    )
    preview = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert not preview.valid
    assert preview.failure == "budget_exceeded"
    assert preview.budget_feet == 0
    with pytest.raises(CombatMovementInvalidError):
        _confirm(table, table.player_actor, char_entry, (1, 1), (2, 1))
    assert _position(table, char_entry) == (1, 1, 1)
    assert _bookkeeping(table, char_entry) == (0, 0, 0, {})  # zero side effects


def test_exhaustion_level_two_halves_movement_budget() -> None:
    table = setup_tactical_table()
    _start(table, blank_width_cells=12, blank_height_cells=12)
    char_entry = _character_entry_id(table)
    monster_entry = _add_monster(table)
    _running(table, char_entry=char_entry, monster_entry=monster_entry)
    _patch_character_state(table, lambda payload: payload.update({"exhaustion_level": 2}))
    preview = _preview(table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1))
    assert preview.valid
    assert preview.budget_feet == 15  # int(30 * 0.5)
    assert preview.used_feet == 10
    over = _preview(
        table, table.player_actor, char_entry, (1, 1), (2, 1), (3, 1), (4, 1), (5, 1),
    )
    assert not over.valid
    assert over.failure == "budget_exceeded"


# ---------------------------------------------------------------------------
# OpenAPI: entry_id travels in the body, never as a query parameter
# ---------------------------------------------------------------------------

def test_movement_routes_take_entry_id_in_body_not_query() -> None:
    from app.main import app

    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    base = (
        "/api/rooms/{room_id}/campaigns/{campaign_id}"
        "/sessions/{session_id}/combat"
    )
    for suffix, schema_name in (
        ("/board/movement/preview", "PreviewMovementInput"),
        ("/board/movement/confirm", "ConfirmMovementInput"),
        ("/board/reposition", "RepositionInput"),
    ):
        item = spec["paths"].get(base + suffix)
        assert item is not None, suffix
        post = item["post"]
        params = [p["name"] for p in post.get("parameters", [])]
        assert "entry_id" not in params, suffix
        body = post["requestBody"]["content"]["application/json"]["schema"]
        schema = schemas[body["$ref"].rsplit("/", 1)[-1]]
        assert schema_name in body["$ref"], suffix
        assert "entry_id" in schema["properties"], suffix
        assert "entry_id" in schema["required"], suffix
