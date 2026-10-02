"""P5-G G.3: PostgreSQL restart preserves the full Tactical Combat state.

Extends the P5-E restart test
(test_postgres_restart_recovers_paused_movement_and_resumes_once) to a
richer running table: round > 1, Difficult Terrain movement bookkeeping,
an OA-paused movement, a pending Reaction window, a pending formal roll,
a hidden token, a hidden wall, and a DM-changed-but-unrevealed hidden
door. After disposing the engine and rewiring fresh services over the
same PostgreSQL database, the DM and Player board projections must be
byte-identical, no secret may leak to the Player, and the paused movement
must resume exactly once before the turn can advance.
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from sqlalchemy import create_engine, insert, update

from app.domain.combat.board import PlaceCombatantInput, UpdateDoorStateInput
from app.domain.combat.lifecycle import (
    ResolveInitiativeOrderInput,
    StartTacticalCombatInput,
)
from app.domain.combat.movement import ResumeMovementInput
from app.domain.combat.roll_compat import CombatAwareRollRepository
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.rolls import RequestCheckInput, RollRequestType, RollService
from app.domain.rooms.table_events import TableEventService
from app.persistence.battle_maps.tables import battle_map_terrain
from app.persistence.combat.tables import combat_entries
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.table_runtime import TableEventRepository, session_events
from tests.p5a_tactical_helpers import (
    TacticalTable,
    insert_battle_map,
    setup_tactical_table,
    wire_tactical_services,
)
from tests.test_p5e_acceptance import (
    POSTGRES_URL,
    _event_rows,
    _monster,
    _movement,
    _pending,
    _pg_head_engine,
)
from tests.test_p5e_e1b import (
    _board,
    _combat,
    _confirm,
    _open_window,
    _position,
    _resolve_window,
)

MOVER_PATH = [(x, 5) for x in range(5, 11)]


def _g3_map(table: TacticalTable) -> UUID:
    """insert_battle_map() plus Difficult Terrain at (6,5), on the mover's path."""
    map_id = insert_battle_map(table)
    with table.engine.begin() as conn:
        conn.execute(
            insert(battle_map_terrain).values(
                battle_map_id=map_id, x=6, y=5, terrain_kind="difficult"
            )
        )
    return map_id


def _g3_start(table: TacticalTable) -> tuple[UUID, UUID, UUID, UUID]:
    """Tactical combat on the G.3 map, round 1, char to act.

    Returns (mover_id, orc_id, hidden_id, hidden_door_id).
    """
    map_id = _g3_map(table)
    table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(battle_map_id=map_id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    mover_id = view.entries[0].id
    table.board.place_position(
        table.dm_actor, mover_id, PlaceCombatantInput(anchor_x=5, anchor_y=5)
    )
    orc_id = _monster(table, "Orc")
    table.board.place_position(
        table.dm_actor, orc_id, PlaceCombatantInput(anchor_x=6, anchor_y=6)
    )
    hidden_id = _monster(table, "Hidden Stalker", visibility="hidden")
    table.board.place_position(
        table.dm_actor, hidden_id, PlaceCombatantInput(anchor_x=9, anchor_y=9)
    )
    with table.engine.begin() as conn:
        for entry_id, total in ((mover_id, 20), (orc_id, 15), (hidden_id, 10)):
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(initiative_total=total)
            )
    table.combat.resolve_initiative_order(
        table.dm_actor,
        ResolveInitiativeOrderInput(ordered_entry_ids=(mover_id, orc_id, hidden_id)),
    )
    assert _combat(table).current_turn_entry_id == mover_id
    hidden_door_id = next(
        d.door_id
        for d in table.board.get_board(table.dm_actor).doors
        if (d.x1, d.y1, d.x2, d.y2) == (5, 0, 6, 0)
    )
    assert hidden_door_id is not None
    return mover_id, orc_id, hidden_id, hidden_door_id


def _rolls(table: TacticalTable) -> RollService:
    return RollService(
        CombatAwareRollRepository(table.engine, table.events.repository),
        ExplorationSubjectRepository(table.engine),
        table.events,
        CharacterRollModifierResolver(table.combat.character_repository, table.registry),
    )


def _request_pending_roll(table: TacticalTable) -> UUID:
    group_id, checks = _rolls(table).request_check(
        table.dm_actor,
        RequestCheckInput(
            target_seat_ids=(table.player_actor.seat_id,),
            request_type=RollRequestType.ABILITY,
            ability_ref="srd5.1:ability:strength",
            label="G.3 pending strength check",
            idempotency_key="g3-pending-roll",
        ),
    )
    assert group_id is not None
    assert len(checks) == 1
    return checks[0].id


def _pending_roll_ids(table: TacticalTable) -> tuple[str, ...]:
    return tuple(
        str(request.id) for request in _rolls(table).list_requests(table.dm_actor)
    )


def _restart(table: TacticalTable) -> TacticalTable:
    """Dispose the engine and rewire fresh services over the same database."""
    table.engine.dispose()
    engine = create_engine(POSTGRES_URL)
    events = TableEventService(TableEventRepository(engine))
    combat, board, battle_maps_repo = wire_tactical_services(
        engine, table.registry, table.characters, events
    )
    return TacticalTable(
        engine=engine,
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        character_id=table.character_id,
        session_id=table.session_id,
        dm_actor=table.dm_actor,
        player_actor=table.player_actor,
        events=events,
        combat=combat,
        board=board,
        battle_maps=battle_maps_repo,
        characters=table.characters,
        registry=table.registry,
    )


def _snapshot(table: TacticalTable, mover_id: UUID) -> dict:
    """Everything the G.3 contract requires to survive the restart."""
    dm_board = table.board.get_board(table.dm_actor).model_dump(mode="json")
    player_board = table.board.get_board(table.player_actor).model_dump(mode="json")
    combat = _combat(table)
    with table.engine.connect() as conn:
        event_count = conn.execute(
            session_events.select().where(
                session_events.c.session_id == table.session_id
            )
        ).fetchall()
    return {
        "dm_board": dm_board,
        "player_board": player_board,
        "round_number": combat.round_number,
        "current_turn_entry_id": str(combat.current_turn_entry_id),
        "position": _position(table, mover_id),
        "pending_movement": _pending(table, mover_id),
        "pending_rolls": _pending_roll_ids(table),
        "event_count": len(event_count),
    }


@pytest.mark.xdist_group("postgres")
@pytest.mark.skipif(not POSTGRES_URL, reason="requires P4_POSTGRES_URL")
def test_p5g_g3_postgres_restart_preserves_full_tactical_state() -> None:
    engine = _pg_head_engine()
    try:
        table = setup_tactical_table(engine)
        mover_id, orc_id, hidden_id, hidden_door_id = _g3_start(table)

        # Round 1, char's turn: DM banks a pending roll and changes the hidden
        # door's runtime state (closed -> open, still unrevealed).
        roll_id = _request_pending_roll(table)
        door_revision = _board(table).runtime_revision
        table.board.update_door_state(
            table.dm_actor,
            hidden_door_id,
            UpdateDoorStateInput(
                state="open",
                revealed=False,
                expected_runtime_revision=door_revision,
                idempotency_key="g3-door-open",
            ),
        )

        # Push to round 2, char's turn again.
        table.combat.advance_turn(table.dm_actor, idempotency_key="g3-advance-1")
        table.combat.advance_turn(table.dm_actor, idempotency_key="g3-advance-2")
        table.combat.advance_turn(table.dm_actor, idempotency_key="g3-advance-3")
        combat = _combat(table)
        assert combat.round_number == 2
        assert combat.current_turn_entry_id == mover_id

        # Round 2: the char walks (5,5)->(10,5) through Difficult Terrain at
        # (6,5) and pauses on the Orc's OA at (7,5). used_feet == 15 proves the
        # terrain cost (10 for the difficult square + 5) is in the bookkeeping.
        movement = _movement(table)
        paused = _confirm(table, movement, table.player_actor, mover_id, MOVER_PATH)
        assert paused.outcome == "paused"
        assert (paused.anchor_x, paused.anchor_y) == (7, 5)
        assert paused.used_feet == 15
        window = _open_window(table, orc_id)
        assert window is not None
        assert window.window_id in paused.pending_window_ids

        before = _snapshot(table, mover_id)
        before_dm_door = next(
            d for d in before["dm_board"]["doors"] if d["door_id"] == str(hidden_door_id)
        )
        assert before_dm_door["state"] == "open"
        assert before_dm_door["revealed"] is False

        # Player projection must already hide every secret before the restart.
        player_positions = {
            p["entry_id"] for p in before["player_board"]["positions"]
        }
        assert str(hidden_id) not in player_positions
        assert len(before["player_board"]["positions"]) == 2
        player_board_text = json.dumps(before["player_board"])
        assert str(hidden_id) not in player_board_text
        assert str(hidden_door_id) not in player_board_text
        assert before["player_board"]["doors"] == []
        # The unrevealed hidden door is projected as a plain wall; walls are
        # sorted by coordinates so their order reveals nothing.
        player_walls = [
            (w["x1"], w["y1"], w["x2"], w["y2"])
            for w in before["player_board"]["walls"]
        ]
        assert player_walls == [(0, 0, 5, 0), (5, 0, 6, 0)]
        assert player_walls == sorted(player_walls)
        assert before["round_number"] == 2
        assert before["current_turn_entry_id"] == str(mover_id)
        assert (before["position"].anchor_x, before["position"].anchor_y) == (7, 5)
        assert before["pending_movement"]["current_path_index"] == 2
        assert before["pending_movement"]["committed_feet"] == 15
        assert before["pending_rolls"] == (str(roll_id),)

        restarted = _restart(table)
        try:
            after = _snapshot(restarted, mover_id)

            # Full state survives: projections, round/turn, position,
            # movement bookkeeping, pending movement, pending roll, events.
            assert after["dm_board"] == before["dm_board"]
            assert after["player_board"] == before["player_board"]
            assert after["round_number"] == 2
            assert after["current_turn_entry_id"] == str(mover_id)
            assert (after["position"].anchor_x, after["position"].anchor_y) == (7, 5)
            assert after["position"].revision == before["position"].revision
            assert after["pending_movement"] == before["pending_movement"]
            assert after["pending_rolls"] == before["pending_rolls"]
            assert after["event_count"] == before["event_count"]

            # The restart itself adds no events and leaks no secrets.
            assert str(hidden_id) not in json.dumps(after["player_board"])
            assert str(hidden_door_id) not in json.dumps(after["player_board"])

            # The DM still sees the changed-but-unrevealed door truth.
            after_dm_door = next(
                d
                for d in after["dm_board"]["doors"]
                if d["door_id"] == str(hidden_door_id)
            )
            assert after_dm_door["state"] == "open"
            assert after_dm_door["revealed"] is False

            # The pending OA window survived with the same window id.
            restarted_window = _open_window(restarted, orc_id)
            assert restarted_window is not None
            assert restarted_window.window_id == window.window_id

            # Resolve the reaction, then resume: exactly once, replay-stable,
            # one combat.movement_resumed event.
            _resolve_window(restarted, orc_id, accept=False)
            restarted_movement = _movement(restarted)
            request = ResumeMovementInput(
                entry_id=mover_id,
                expected_pending_revision=int(
                    _pending(restarted, mover_id)["revision"]
                ),
                idempotency_key="g3-resume-once",
            )
            first = restarted_movement.resume(
                restarted.player_actor, mover_id, request
            )
            replay = restarted_movement.resume(
                restarted.player_actor, mover_id, request
            )
            assert first.outcome == "resumed"
            assert replay == first
            assert (first.anchor_x, first.anchor_y) == (10, 5)
            assert len(_event_rows(restarted, "combat.movement_resumed")) == 1

            # The turn can keep advancing after the restart.
            restarted.combat.advance_turn(
                restarted.dm_actor, idempotency_key="g3-advance-4"
            )
            advanced = _combat(restarted)
            assert advanced.round_number == 2
            assert advanced.current_turn_entry_id == orc_id
        finally:
            restarted.engine.dispose()
    finally:
        engine.dispose()
