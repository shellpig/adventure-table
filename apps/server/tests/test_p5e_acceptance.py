"""P5-E acceptance: 測試指南 E.4–E.6 end-to-end through the real services.

Complements test_p5e_opportunity.py / test_p5e_e1b.py with exact outcome
assertions: resume revalidation and re-pause, resume idempotency, the
advance_turn 409 guard with zero side effects, cancel audit, lifecycle
cleanup of pending movement, PostgreSQL restart recovery and the 0039
migration, Grapple drag cost / blocking, and Tactical Shove push through the
full P4 formal-roll flow (walls, occupancy, bounds, hidden blockers).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, func, insert, select, text, update

from app.domain.combat.board import PlaceCombatantInput
from app.domain.combat.lifecycle import (
    AddMonsterInput,
    CombatStateConflictError,
    ResolveInitiativeOrderInput,
    StartTacticalCombatInput,
)
from app.domain.combat.movement import (
    CancelPendingMovementInput,
    CombatMovementInvalidError,
    MovementService,
    ResumeMovementInput,
)
from app.domain.combat.resolution import SpecialAttackKind
from app.domain.combat.special_attacks import (
    CombatSpecialAttackService,
    SpecialAttackAdjudicationInput,
    SpecialAttackRequestInput,
)
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource, RollService
from app.domain.rooms.table_events import (
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.domain.combat.roll_compat import CombatAwareRollRepository
from app.persistence.battle_maps.tables import battle_map_walls, battle_maps
from app.persistence.combat.core_rolls import CombatCoreRollRepository
from app.persistence.combat.special_attacks import SpecialAttackRepository
from app.persistence.combat.tables import combat_entries
from app.persistence.rooms.p3c_runtime import roll_requests
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.table_runtime import TableEventRepository, session_events
from tests.p5a_tactical_helpers import (
    TacticalTable,
    setup_tactical_table,
    wire_tactical_services,
)
from tests.test_p5e_e1b import (
    _combat,
    _confirm,
    _open_window,
    _position,
    _reposition,
    _resolve_window,
    _set_character_grappled,
    _set_character_hp,
    _set_grappled,
)


POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
MOVER_PATH = [(x, 5) for x in range(5, 11)]


# ---------------------------------------------------------------------------
# Helpers


def _movement(table: TacticalTable) -> MovementService:
    return MovementService(
        board_repository=table.board.board_repository,
        board_service=table.board,
        combat_service=table.combat,
    )


def _monster(
    table: TacticalTable, name: str, *, size: str = "Medium", visibility: str = "public"
) -> UUID:
    instance = table.combat.monster_repository.create_instance(
        campaign_id=table.campaign_id,
        name=name,
        rules_snapshot={
            "armor_class": 12,
            "max_hp": 30,
            "speed": {"walk": "30 ft."},
            "size": size,
            "ability_scores": {
                "strength": 10, "dexterity": 10, "constitution": 10,
                "intelligence": 10, "wisdom": 10, "charisma": 10,
            },
            "proficiencies": [],
        },
        visibility=visibility,
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=instance.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return next(e.id for e in view.entries if e.monster_instance_id == instance.id)


def _start(
    table: TacticalTable,
    monsters: list[tuple[str, int, int]],
    *,
    battle_map_id: UUID | None = None,
    visibility: str = "public",
    size: str = "Medium",
) -> tuple[UUID, list[UUID]]:
    """Start Tactical combat: character at (5,5) acts first, then the monsters."""
    if battle_map_id is None:
        start = StartTacticalCombatInput(blank_width_cells=12, blank_height_cells=12)
    else:
        start = StartTacticalCombatInput(battle_map_id=battle_map_id)
    table.combat.start_tactical_combat(table.dm_actor, start)
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    mover_id = view.entries[0].id
    table.board.place_position(
        table.dm_actor, mover_id, PlaceCombatantInput(anchor_x=5, anchor_y=5)
    )
    monster_ids = []
    for name, x, y in monsters:
        entry_id = _monster(table, name, size=size, visibility=visibility)
        table.board.place_position(
            table.dm_actor, entry_id, PlaceCombatantInput(anchor_x=x, anchor_y=y)
        )
        monster_ids.append(entry_id)
    with table.engine.begin() as conn:
        for index, entry_id in enumerate((mover_id, *monster_ids)):
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(initiative_total=20 - index)
            )
    table.combat.resolve_initiative_order(
        table.dm_actor,
        ResolveInitiativeOrderInput(ordered_entry_ids=(mover_id, *monster_ids)),
    )
    assert _combat(table).current_turn_entry_id == mover_id
    return mover_id, monster_ids


def _pending(table: TacticalTable, entry_id: UUID) -> dict:
    entry = table.combat.repository.get_entry(entry_id)
    assert entry is not None
    return dict(entry.pending_movement_state or {})


def _resume(table, movement, actor, mover_id, key=None):
    return movement.resume(
        actor, mover_id,
        ResumeMovementInput(
            entry_id=mover_id,
            expected_pending_revision=int(_pending(table, mover_id)["revision"]),
            idempotency_key=key or f"accept-resume-{uuid4()}",
        ),
    )


def _decline_all(table, reactor_ids):
    for reactor_id in reactor_ids:
        if _open_window(table, reactor_id) is not None:
            _resolve_window(table, reactor_id, accept=False)


def _paused_by_orc(table: TacticalTable):
    """Mover walks (5,5)->(10,5) past an Orc at (6,6): pauses at (7,5)."""
    mover_id, (orc_id,) = _start(table, [("Orc", 6, 6)])
    movement = _movement(table)
    view = _confirm(table, movement, table.player_actor, mover_id, MOVER_PATH)
    assert view.outcome == "paused"
    assert (view.anchor_x, view.anchor_y) == (7, 5)
    assert view.used_feet == 10
    return movement, mover_id, orc_id, view


def _event_rows(table: TacticalTable, kind: str):
    with table.engine.connect() as conn:
        return conn.execute(
            select(session_events.c.visibility, session_events.c.payload)
            .where(
                session_events.c.session_id == table.session_id,
                session_events.c.kind == kind,
            )
            .order_by(session_events.c.seq)
        ).mappings().all()


def _player_payloads(table: TacticalTable) -> str:
    page = table.events.list_after(table.player_actor, after_seq=0, limit=200)
    return repr([(event.kind, event.payload) for event in page.events])


# ---------------------------------------------------------------------------
# E.4 Reaction changes mover / resume


def test_clean_resume_continues_from_durable_index_to_path_end() -> None:
    table = setup_tactical_table()
    movement, mover_id, orc_id, _view = _paused_by_orc(table)
    _decline_all(table, [orc_id])

    result = _resume(table, movement, table.player_actor, mover_id)

    assert result.outcome == "resumed"
    assert (result.anchor_x, result.anchor_y) == (10, 5)
    assert result.used_feet == 25
    assert _pending(table, mover_id) == {}
    position = _position(table, mover_id)
    assert (position.anchor_x, position.anchor_y) == (10, 5)


def test_resume_replay_with_same_key_moves_only_once() -> None:
    table = setup_tactical_table()
    movement, mover_id, orc_id, _view = _paused_by_orc(table)
    _decline_all(table, [orc_id])
    request = ResumeMovementInput(
        entry_id=mover_id,
        expected_pending_revision=int(_pending(table, mover_id)["revision"]),
        idempotency_key="accept-resume-once",
    )
    first = movement.resume(table.player_actor, mover_id, request)
    revision_after_first = _position(table, mover_id).revision

    replay = movement.resume(table.player_actor, mover_id, request)

    assert replay == first
    assert _position(table, mover_id).revision == revision_after_first
    assert len(_event_rows(table, "combat.movement_resumed")) == 1


def test_resume_pauses_again_when_leaving_a_second_reach() -> None:
    table = setup_tactical_table()
    mover_id, (orc_id, ogre_id) = _start(table, [("Orc", 6, 6), ("Ogre", 8, 6)])
    movement = _movement(table)
    first = _confirm(table, movement, table.player_actor, mover_id, MOVER_PATH)
    assert first.outcome == "paused"
    assert first.boundary_reactor_ids == (orc_id,)
    _decline_all(table, [orc_id])

    second = _resume(table, movement, table.player_actor, mover_id)

    assert second.outcome == "paused"
    assert (second.anchor_x, second.anchor_y) == (9, 5)
    assert second.boundary_reactor_ids == (ogre_id,)
    assert _open_window(table, ogre_id) is not None
    assert _open_window(table, orc_id) is None


def test_accepted_oa_makes_resume_dm_only_with_zero_side_effects_for_player() -> None:
    table = setup_tactical_table()
    movement, mover_id, orc_id, _view = _paused_by_orc(table)
    _resolve_window(table, orc_id, accept=True)
    orc = table.combat.repository.get_entry(orc_id)
    assert orc is not None and orc.reaction_available is False
    pending_before = _pending(table, mover_id)
    position_before = _position(table, mover_id)

    with pytest.raises(TableEventActorUnauthorizedError):
        _resume(table, movement, table.player_actor, mover_id)

    assert _pending(table, mover_id) == pending_before
    assert _position(table, mover_id) == position_before
    result = _resume(table, movement, table.dm_actor, mover_id)
    assert result.outcome == "resumed"
    assert (result.anchor_x, result.anchor_y) == (10, 5)


def test_resume_stops_at_zero_hp_without_moving() -> None:
    table = setup_tactical_table()
    movement, mover_id, orc_id, _view = _paused_by_orc(table)
    _resolve_window(table, orc_id, accept=True)
    _set_character_hp(table, mover_id, 0)

    result = _resume(table, movement, table.dm_actor, mover_id)

    assert result.outcome == "stopped"
    assert (result.anchor_x, result.anchor_y) == (7, 5)
    assert _pending(table, mover_id) == {}
    position = _position(table, mover_id)
    assert (position.anchor_x, position.anchor_y) == (7, 5)


def test_resume_stops_when_speed_drops_to_zero() -> None:
    table = setup_tactical_table()
    movement, mover_id, orc_id, _view = _paused_by_orc(table)
    _decline_all(table, [orc_id])
    _set_character_grappled(table, mover_id)

    result = _resume(table, movement, table.player_actor, mover_id)

    assert result.outcome == "stopped"
    position = _position(table, mover_id)
    assert (position.anchor_x, position.anchor_y) == (7, 5)
    assert _pending(table, mover_id) == {}


def test_resume_after_reposition_cancels_remaining_path() -> None:
    table = setup_tactical_table()
    movement, mover_id, orc_id, _view = _paused_by_orc(table)
    _decline_all(table, [orc_id])
    _reposition(table, mover_id, 1, 1)

    result = _resume(table, movement, table.player_actor, mover_id)

    assert result.outcome == "stopped"
    position = _position(table, mover_id)
    assert (position.anchor_x, position.anchor_y) == (1, 1)
    assert _pending(table, mover_id) == {}


def test_player_cannot_resume_a_movement_they_do_not_control() -> None:
    table = setup_tactical_table()
    mover_id, (orc_id,) = _start(table, [("Orc", 6, 5)])
    # The Orc (DM-controlled) walks away from the Player character.
    table.combat.advance_turn(table.dm_actor)
    assert _combat(table).current_turn_entry_id == orc_id
    movement = _movement(table)
    view = _confirm(
        table, movement, table.dm_actor, orc_id, [(6, 5), (7, 5), (8, 5)]
    )
    assert view.outcome == "paused"
    _decline_all(table, [mover_id])
    pending_before = _pending(table, orc_id)

    with pytest.raises(TableEventActorUnauthorizedError):
        _resume(table, movement, table.player_actor, orc_id)

    assert _pending(table, orc_id) == pending_before


# ---------------------------------------------------------------------------
# E.5 advance guard, cancel audit, lifecycle cleanup


def test_advance_turn_is_409_with_zero_side_effects_while_window_open() -> None:
    table = setup_tactical_table()
    movement, mover_id, orc_id, _view = _paused_by_orc(table)
    combat_before = _combat(table)
    mover_before = table.combat.repository.get_entry(mover_id)
    orc_before = table.combat.repository.get_entry(orc_id)
    position_before = _position(table, mover_id)

    with pytest.raises(CombatStateConflictError):
        table.combat.advance_turn(table.dm_actor)

    combat_after = _combat(table)
    assert combat_after.current_turn_entry_id == combat_before.current_turn_entry_id
    assert combat_after.round_number == combat_before.round_number
    assert table.combat.repository.get_entry(mover_id) == mover_before
    assert table.combat.repository.get_entry(orc_id) == orc_before
    assert _position(table, mover_id) == position_before


def test_dm_cancel_pending_is_audited_then_turn_can_advance() -> None:
    table = setup_tactical_table()
    movement, mover_id, orc_id, _view = _paused_by_orc(table)

    cancelled = movement.cancel_pending_movement(
        table.dm_actor, mover_id,
        CancelPendingMovementInput(
            entry_id=mover_id, reason="Orc OA ruled moot", idempotency_key="cancel-1"
        ),
    )

    assert cancelled.cancelled is True
    assert (cancelled.anchor_x, cancelled.anchor_y) == (7, 5)
    assert _pending(table, mover_id) == {}
    rows = _event_rows(table, "combat.movement_cancelled")
    assert len(rows) == 1
    assert "Orc OA ruled moot" in repr(rows[0]["payload"])
    table.combat.advance_turn(table.dm_actor)
    assert _combat(table).current_turn_entry_id == orc_id


def test_stale_pending_is_cleared_at_the_movers_next_turn_start() -> None:
    table = setup_tactical_table()
    movement, mover_id, orc_id, _view = _paused_by_orc(table)
    _decline_all(table, [orc_id])

    table.combat.advance_turn(table.dm_actor)
    assert _combat(table).current_turn_entry_id == orc_id
    assert _pending(table, mover_id) != {}
    table.combat.advance_turn(table.dm_actor)

    assert _combat(table).current_turn_entry_id == mover_id
    assert _pending(table, mover_id) == {}


@pytest.mark.parametrize("operation", ["end", "withdraw", "remove"])
def test_lifecycle_operations_clear_pending_movement(operation: str) -> None:
    table = setup_tactical_table()
    movement, mover_id, orc_id, _view = _paused_by_orc(table)
    assert _pending(table, mover_id) != {}

    if operation != "end":
        # The current-turn entry cannot leave; pending survives the advance.
        _decline_all(table, [orc_id])
        table.combat.advance_turn(table.dm_actor)
        assert _pending(table, mover_id) != {}
    if operation == "end":
        table.combat.end_combat(table.dm_actor)
    elif operation == "withdraw":
        table.combat.withdraw_entry(table.dm_actor, mover_id)
    else:
        table.combat.remove_entry(table.dm_actor, mover_id)

    with table.engine.connect() as conn:
        pending = conn.execute(
            select(combat_entries.c.pending_movement_state)
            .where(combat_entries.c.id == mover_id)
        ).scalar_one_or_none()
    assert not pending


# ---------------------------------------------------------------------------
# E.6 Grapple drag


def test_drag_is_not_doubled_when_the_target_is_two_sizes_smaller() -> None:
    table = setup_tactical_table()
    mover_id, (rat_id,) = _start(table, [("Rat", 5, 6)], size="Tiny")
    _set_grappled(table, rat_id, grappler_id=mover_id)
    movement = _movement(table)

    view = _confirm(
        table, movement, table.player_actor, mover_id,
        [(5, 5), (6, 5), (7, 5)], drag_entry_id=rat_id,
    )

    assert view.outcome == "committed"
    assert view.used_feet == 10
    rat = _position(table, rat_id)
    assert (rat.anchor_x, rat.anchor_y) == (7, 6)


def test_drag_into_an_occupied_cell_rejects_with_zero_side_effects() -> None:
    table = setup_tactical_table()
    mover_id, (victim_id, blocker_id) = _start(
        table, [("Victim", 5, 6), ("Blocker", 7, 6)]
    )
    _set_grappled(table, victim_id, grappler_id=mover_id)
    movement = _movement(table)
    mover_before = _position(table, mover_id)
    victim_before = _position(table, victim_id)

    with pytest.raises(CombatMovementInvalidError):
        _confirm(
            table, movement, table.player_actor, mover_id,
            [(5, 5), (6, 5), (7, 5)], drag_entry_id=victim_id,
        )

    assert _position(table, mover_id) == mover_before
    assert _position(table, victim_id) == victim_before
    entry = table.combat.repository.get_entry(mover_id)
    assert entry is not None and entry.movement_used_feet == 0


def test_drag_requires_the_grapple_to_come_from_the_mover() -> None:
    table = setup_tactical_table()
    mover_id, (victim_id, other_id) = _start(
        table, [("Victim", 5, 6), ("Other", 9, 9)]
    )
    _set_grappled(table, victim_id, grappler_id=other_id)
    movement = _movement(table)

    with pytest.raises(CombatMovementInvalidError):
        _confirm(
            table, movement, table.player_actor, mover_id,
            [(5, 5), (6, 5)], drag_entry_id=victim_id,
        )
    victim = _position(table, victim_id)
    assert (victim.anchor_x, victim.anchor_y) == (5, 6)


# ---------------------------------------------------------------------------
# E.6 Shove push through the full P4 formal-roll flow


def _special_attacks(table: TacticalTable) -> CombatSpecialAttackService:
    rolls = RollService(
        CombatAwareRollRepository(table.engine, table.events.repository),
        ExplorationSubjectRepository(table.engine),
        table.events,
        CharacterRollModifierResolver(table.combat.character_repository, table.registry),
    )
    return CombatSpecialAttackService(
        repository=SpecialAttackRepository(table.engine, table.events.repository),
        core_roll_repository=CombatCoreRollRepository(table.engine, table.events.repository),
        combat_repository=table.combat.repository,
        combat_service=table.combat,
        character_repository=table.combat.character_repository,
        monster_repository=table.combat.monster_repository,
        registry=table.registry,
        roll_service=rolls,
        table_event_service=table.events,
        board_repository=table.board.board_repository,
        board_service=table.board,
    )


def _request_shove(table, service, attacker_id, target_id):
    return service.request_special_attack(
        table.player_actor,
        SpecialAttackRequestInput(
            attacker_entry_id=attacker_id,
            target_entry_id=target_id,
            kind=SpecialAttackKind.SHOVE_PUSH,
            idempotency_key=f"shove-{uuid4()}",
        ),
    )


def _win_shove(table, service, pending):
    resumed = service.adjudicate_special_attack(
        table.dm_actor,
        SpecialAttackAdjudicationInput(
            action_id=pending.action_id, in_reach=True,
            idempotency_key=f"reach-{pending.action_id}",
        ),
    )
    assert resumed.attacker_roll_request_id is not None
    assert resumed.defender_roll_request_id is not None
    service.complete_special_attack_roll(
        table.player_actor,
        FormalRollInput(
            roll_request_id=resumed.attacker_roll_request_id,
            source=FormalRollSource.PHYSICAL, raw_dice=(20,),
            idempotency_key=f"atk-{pending.action_id}",
        ),
    )
    resolved = service.complete_special_attack_roll(
        table.dm_actor,
        FormalRollInput(
            roll_request_id=resumed.defender_roll_request_id,
            source=FormalRollSource.PHYSICAL, raw_dice=(1,),
            idempotency_key=f"def-{pending.action_id}",
        ),
    )
    assert resolved.status == "resolved"
    assert resolved.resolution_result is not None
    assert resolved.resolution_result["status"] == "success"
    return resolved


def _roll_request_count(table: TacticalTable) -> int:
    with table.engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(roll_requests)).scalar_one())


def _monster_hp(table: TacticalTable, entry_id: UUID) -> int:
    entry = table.combat.repository.get_entry(entry_id)
    assert entry is not None and entry.monster_instance_id is not None
    instance = table.combat.monster_repository.get_instance(entry.monster_instance_id)
    assert instance is not None
    return int(instance.current_hp)


def test_shove_push_moves_the_target_5ft_without_oa_or_fall_damage() -> None:
    table = setup_tactical_table()
    attacker_id, (target_id,) = _start(table, [("Orc", 6, 5)])
    service = _special_attacks(table)
    hp_before = _monster_hp(table, target_id)

    _win_shove(table, service, _request_shove(table, service, attacker_id, target_id))

    target = _position(table, target_id)
    assert (target.anchor_x, target.anchor_y) == (7, 5)
    assert _open_window(table, attacker_id) is None
    assert _monster_hp(table, target_id) == hp_before


def _map_with_wall(table: TacticalTable, x1: int, y1: int, x2: int, y2: int) -> UUID:
    map_id = uuid4()
    now = datetime.now(timezone.utc)
    with table.engine.begin() as conn:
        conn.execute(insert(battle_maps).values(
            id=map_id, room_id=table.room_id, name="Wall room",
            source_kind="blank", image_asset_id=None,
            width_cells=12, height_cells=12,
            grid_pixel_size=None, grid_offset_x=None, grid_offset_y=None,
            revision=1, created_at=now, updated_at=now,
        ))
        conn.execute(insert(battle_map_walls).values(
            id=uuid4(), battle_map_id=map_id,
            x1=x1, y1=y1, x2=x2, y2=y2, visibility="public",
        ))
    return map_id


@pytest.mark.parametrize("case", ["wall", "occupied", "out_of_bounds"])
def test_illegal_shove_destination_is_409_at_request_without_rolls(case: str) -> None:
    table = setup_tactical_table()
    if case == "wall":
        # Target at (6,5); the cell edge x=7 between (6,5) and (7,5) is a wall.
        attacker_id, (target_id,) = _start(
            table, [("Orc", 6, 5)], battle_map_id=_map_with_wall(table, 7, 5, 7, 6)
        )
    elif case == "occupied":
        attacker_id, (target_id, _blocker) = _start(
            table, [("Orc", 6, 5), ("Blocker", 7, 5)]
        )
    else:
        attacker_id, (target_id,) = _start(table, [("Orc", 6, 5)])
        _reposition(table, attacker_id, 10, 5)
        _reposition(table, target_id, 11, 5)
    service = _special_attacks(table)
    rolls_before = _roll_request_count(table)
    target_before = _position(table, target_id)

    with pytest.raises(CombatStateConflictError):
        _request_shove(table, service, attacker_id, target_id)

    assert _roll_request_count(table) == rolls_before
    assert _position(table, target_id) == target_before


def test_hidden_blocker_at_completion_keeps_target_and_leaks_nothing() -> None:
    table = setup_tactical_table()
    attacker_id, (target_id,) = _start(table, [("Orc", 6, 5)])
    hidden_id = _monster(table, "Lurker", visibility="hidden")
    table.board.place_position(
        table.dm_actor, hidden_id, PlaceCombatantInput(anchor_x=7, anchor_y=5)
    )
    service = _special_attacks(table)

    _win_shove(table, service, _request_shove(table, service, attacker_id, target_id))

    target = _position(table, target_id)
    assert (target.anchor_x, target.anchor_y) == (6, 5)
    payloads = _player_payloads(table)
    assert str(hidden_id) not in payloads
    assert "Lurker" not in payloads


# ---------------------------------------------------------------------------
# Secrecy


def test_hidden_reactor_does_not_pause_and_leaves_only_a_dm_note() -> None:
    table = setup_tactical_table()
    mover_id, (lurker_id,) = _start(table, [("Lurker", 6, 6)], visibility="hidden")
    movement = _movement(table)

    view = _confirm(table, movement, table.player_actor, mover_id, MOVER_PATH)

    assert view.outcome == "committed"
    assert (view.anchor_x, view.anchor_y) == (10, 5)
    assert _open_window(table, lurker_id) is None
    notes = _event_rows(table, "combat.opportunity_crossing_noted")
    assert len(notes) == 1
    assert notes[0]["visibility"] == "dm_only"
    assert str(lurker_id) not in _player_payloads(table)


def test_hidden_mover_resume_and_cancel_events_are_dm_only() -> None:
    table = setup_tactical_table()
    mover_id, (lurker_id,) = _start(table, [("Lurker", 5, 4)], visibility="hidden")
    table.combat.advance_turn(table.dm_actor)
    movement = _movement(table)
    # The hidden Lurker walks away from the Player character's reach.
    view = _confirm(
        table, movement, table.dm_actor, lurker_id, [(5, 4), (5, 3), (5, 2), (5, 1)]
    )
    assert view.outcome == "paused"
    _decline_all(table, [mover_id])
    _resume(table, movement, table.dm_actor, lurker_id)

    for kind in ("combat.movement_paused", "combat.movement_resumed"):
        rows = _event_rows(table, kind)
        assert rows and all(row["visibility"] == "dm_only" for row in rows)
    assert str(lurker_id) not in _player_payloads(table)


# ---------------------------------------------------------------------------
# PostgreSQL: restart recovery and the 0039 migration


def _pg_head_engine():
    from test_p5a_postgres_migration import _config, _reset

    _reset()
    command.upgrade(_config(), "heads")
    assert POSTGRES_URL is not None
    return create_engine(POSTGRES_URL)


@pytest.mark.xdist_group("postgres")
@pytest.mark.skipif(not POSTGRES_URL, reason="P4_POSTGRES_URL is only supplied by the PostgreSQL job")
def test_postgres_restart_recovers_paused_movement_and_resumes_once() -> None:
    engine = _pg_head_engine()
    try:
        table = setup_tactical_table(engine)
        _movement_before, mover_id, orc_id, paused = _paused_by_orc(table)
        pending_before = _pending(table, mover_id)
        engine.dispose()

        # "Restart": fresh engine and freshly wired services, same database.
        engine = create_engine(POSTGRES_URL)
        events = TableEventService(TableEventRepository(engine))
        combat, board, battle_maps_repo = wire_tactical_services(
            engine, table.registry, table.characters, events
        )
        restarted = TacticalTable(
            engine=engine, room_id=table.room_id, campaign_id=table.campaign_id,
            character_id=table.character_id, session_id=table.session_id,
            dm_actor=table.dm_actor, player_actor=table.player_actor,
            events=events, combat=combat, board=board, battle_maps=battle_maps_repo,
            characters=table.characters, registry=table.registry,
        )
        position = _position(restarted, mover_id)
        assert (position.anchor_x, position.anchor_y) == (7, 5)
        assert _pending(restarted, mover_id) == pending_before
        window = _open_window(restarted, orc_id)
        assert window is not None
        assert window.window_id in paused.pending_window_ids

        _resolve_window(restarted, orc_id, accept=False)
        movement = _movement(restarted)
        request = ResumeMovementInput(
            entry_id=mover_id,
            expected_pending_revision=int(_pending(restarted, mover_id)["revision"]),
            idempotency_key="pg-resume-once",
        )
        first = movement.resume(restarted.player_actor, mover_id, request)
        replay = movement.resume(restarted.player_actor, mover_id, request)
        assert first.outcome == "resumed"
        assert replay == first
        position = _position(restarted, mover_id)
        assert (position.anchor_x, position.anchor_y) == (10, 5)
        assert len(_event_rows(restarted, "combat.movement_resumed")) == 1
    finally:
        engine.dispose()


@pytest.mark.xdist_group("postgres")
@pytest.mark.skipif(not POSTGRES_URL, reason="P4_POSTGRES_URL is only supplied by the PostgreSQL job")
def test_postgres_0039_disengaged_migration_round_trip() -> None:
    from test_p5a_postgres_migration import _config, _reset

    _reset()
    config = _config()
    command.upgrade(config, "0038_p5b_movement_bookkeeping")
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        command.upgrade(config, "0039_p5e_disengaged")
        with engine.connect() as conn:
            column = conn.execute(text(
                "SELECT column_default, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'combat_entries' AND column_name = 'disengaged'"
            )).mappings().one()
        assert column["is_nullable"] == "NO"
        command.downgrade(config, "0038_p5b_movement_bookkeeping")
        with engine.connect() as conn:
            remaining = conn.execute(text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'combat_entries' AND column_name = 'disengaged'"
            )).scalar_one()
        assert remaining == 0
    finally:
        engine.dispose()
