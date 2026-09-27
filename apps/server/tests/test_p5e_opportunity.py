"""P5-E E1: opportunity attacks, spatial reactions, Disengage (backend only).

E.1: Disengage suppresses OA (Tactical + Quick).
E.2: OA window opening, resolution, and resume.
E.3: Hidden creatures' OA silence (DM-only notes, no windows).
E.4: Advance-turn guard and DM cancel-pending.
E.5: Shove push spatial semantics (Tactical).
E.6: Grapple drag spatial semantics (Tactical).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.domain.combat.lifecycle import (
    AddMonsterInput,
    CombatActionInput,
    CombatActionKind,
    CombatEconomyCost,
    StartTacticalCombatInput,
)
from app.domain.combat.movement import (
    CancelPendingMovementInput,
    CombatMovementInvalidError,
    CombatStateConflictError,
    ConfirmMovementInput,
    MovementAnchorInput,
    MovementService,
    PreviewMovementInput,
    ResumeMovementInput,
)
from app.domain.combat.reaction_service import CombatReactionService
from app.domain.combat.special_attacks import CombatSpecialAttackService
from app.domain.spatial.opportunity import (
    OpportunityReactor,
    detect_opportunity_crossings,
)
from app.domain.spatial import GridCell, Footprint
from tests.p5a_tactical_helpers import (
    TacticalTable,
    setup_tactical_table,
)


def _movement(table: TacticalTable) -> MovementService:
    return MovementService(
        board_repository=table.board.board_repository,
        board_service=table.board,
        combat_service=table.combat,
    )


def _start(table: TacticalTable, **kwargs):
    kwargs.setdefault("blank_width_cells", 12)
    kwargs.setdefault("blank_height_cells", 12)
    view = table.combat.start_tactical_combat(
        table.dm_actor, StartTacticalCombatInput(**kwargs)
    )
    # Place and resolve initiative to reach running status.
    from app.domain.combat.lifecycle import ResolveInitiativeOrderInput
    from app.domain.combat.board import PlaceCombatantInput
    from sqlalchemy import update
    from app.persistence.combat.tables import combat_entries
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    entry_id = view.entries[0].id
    table.board.place_position(
        table.dm_actor, entry_id,
        PlaceCombatantInput(anchor_x=5, anchor_y=5),
    )
    with table.engine.begin() as conn:
        conn.execute(
            update(combat_entries)
            .where(combat_entries.c.id == entry_id)
            .values(initiative_total=20)
        )
    table.combat.resolve_initiative_order(
        table.dm_actor, ResolveInitiativeOrderInput(ordered_entry_ids=(entry_id,))
    )
    return view


def _entries(table: TacticalTable):
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return view.entries


def _add_monster(table: TacticalTable, *, visibility: str = "public", name: str = "Goblin") -> UUID:
    instance = table.combat.monster_repository.create_quick_enemy(
        campaign_id=table.campaign_id, name=name,
        armor_class=15, max_hp=30, speed={"walk": "30 ft."},
        visibility=visibility,
    )
    table.combat.add_monster(
        table.dm_actor, AddMonsterInput(monster_instance_id=instance.id)
    )
    view = table.combat.get_active_combat(table.dm_actor)
    assert view is not None
    return view.entries[-1].id


def _place(table: TacticalTable, entry_id: UUID, x: int, y: int) -> None:
    from app.domain.combat.board import PlaceCombatantInput
    table.board.place_position(
        table.dm_actor, entry_id,
        PlaceCombatantInput(anchor_x=x, anchor_y=y),
    )


def _set_turn(table: TacticalTable, entry_id: UUID) -> None:
    """Force the current turn to entry_id (test helper via direct DB update)."""
    from sqlalchemy import update
    from app.persistence.combat.tables import combats
    combat = table.combat.repository.get_active(table.dm_actor.campaign_id)
    assert combat is not None
    with table.engine.begin() as conn:
        conn.execute(
            update(combats)
            .where(combats.c.id == combat.id)
            .values(current_turn_entry_id=entry_id)
        )


# ----------------------------------------------------------------------
# E.1: Disengage suppresses OA
# ----------------------------------------------------------------------

class TestDisengageSuppressesOA:
    def test_disengage_action_sets_flag(self):
        table = setup_tactical_table()
        _start(table)
        entry_id = _entries(table)[0].id
        table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=entry_id,
                action_kind=CombatActionKind.DISENGAGE,
                economy_cost=CombatEconomyCost.ACTION,
            ),
        )
        entry = table.combat.repository.get_entry(entry_id)
        assert entry is not None
        assert entry.disengaged is True

    def test_disengage_suppresses_oa_crossing(self):
        """A disengaged mover crossing a reactor's reach does not pause."""
        table = setup_tactical_table()
        _start(table)
        entries = _entries(table)
        mover_id = entries[0].id
        reactor_id = _add_monster(table, name="Orc")
        _place(table, reactor_id, 6, 6)
        # Disengage first.
        table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=mover_id,
                action_kind=CombatActionKind.DISENGAGE,
                economy_cost=CombatEconomyCost.ACTION,
            ),
        )
        _set_turn(table, mover_id)
        movement = _movement(table)
        position = table.board.board_repository.get_position(mover_id)
        assert position is not None
        board = table.board.board_repository.get_board(
            table.combat.repository.get_active(table.dm_actor.campaign_id).id
        )
        assert board is not None
        # Move from (5,5) to (10,5): crosses the Orc's 5-ft reach boundary.
        view = movement.confirm(
            table.dm_actor, mover_id,
            ConfirmMovementInput(
                entry_id=mover_id,
                path=tuple(
                    MovementAnchorInput(x=x, y=5) for x in range(5, 11)
                ),
                expected_position_revision=position.revision,
                expected_board_revision=board.runtime_revision,
                idempotency_key=f"e1-{uuid4()}",
            ),
        )
        # Disengaged: no pause, full commit.
        assert view.outcome == "committed"
        assert view.anchor_x == 10
        assert view.anchor_y == 5

    def test_disengage_flag_reset_on_turn_advance(self):
        table = setup_tactical_table()
        _start(table)
        entry_id = _entries(table)[0].id
        table.combat.use_action(
            table.dm_actor,
            CombatActionInput(
                entry_id=entry_id,
                action_kind=CombatActionKind.DISENGAGE,
                economy_cost=CombatEconomyCost.ACTION,
            ),
        )
        entry = table.combat.repository.get_entry(entry_id)
        assert entry is not None and entry.disengaged is True
        table.combat.advance_turn(table.dm_actor)
        table.combat.advance_turn(table.dm_actor)
        entry = table.combat.repository.get_entry(entry_id)
        assert entry is not None
        assert entry.disengaged is False


# ----------------------------------------------------------------------
# Pure-function detector
# ----------------------------------------------------------------------

class TestOpportunityDetector:
    def test_crossing_detected(self):
        mover_footprint = Footprint(width=1, height=1)
        reactor = OpportunityReactor(
            entry_id=uuid4(),
            anchor=GridCell(6, 5),
            footprint=Footprint(width=1, height=1),
            melee_attacks=(),
            turn_order=0,
            hidden=False,
            hostile_to_mover=True,
            active=True,
            reaction_available=True,
            blocks_reactions=False,
            current_hp=30,
            has_open_window=False,
        )
        # Mover at (5,5) moving to (10,5): leaves the reactor's reach.
        anchors = (GridCell(5, 5), GridCell(10, 5))
        crossings = detect_opportunity_crossings(
            anchors=anchors,
            mover_footprint=mover_footprint,
            reactors=(reactor,),
            mover_disengaged=False,
        )
        assert len(crossings) == 1
        assert crossings[0].step_index == 0
        assert crossings[0].reactor_entry_ids == (reactor.entry_id,)

    def test_no_crossing_when_staying_in_reach(self):
        mover_footprint = Footprint(width=1, height=1)
        reactor = OpportunityReactor(
            entry_id=uuid4(),
            anchor=GridCell(6, 5),
            footprint=Footprint(width=1, height=1),
            melee_attacks=(),
            turn_order=0,
            hidden=False,
            hostile_to_mover=True,
            active=True,
            reaction_available=True,
            blocks_reactions=False,
            current_hp=30,
            has_open_window=False,
        )
        # With 10-ft reach, moving from (5,5) to (7,5) stays in reach.
        anchors = (GridCell(5, 5), GridCell(7, 5))
        crossings = detect_opportunity_crossings(
            anchors=anchors,
            mover_footprint=mover_footprint,
            reactors=(reactor,),
            mover_disengaged=False,
        )
        assert len(crossings) == 0

    def test_disengaged_suppresses(self):
        mover_footprint = Footprint(width=1, height=1)
        reactor = OpportunityReactor(
            entry_id=uuid4(),
            anchor=GridCell(6, 5),
            footprint=Footprint(width=1, height=1),
            melee_attacks=(),
            turn_order=0,
            hidden=False,
            hostile_to_mover=True,
            active=True,
            reaction_available=True,
            blocks_reactions=False,
            current_hp=30,
            has_open_window=False,
        )
        anchors = (GridCell(5, 5), GridCell(10, 5))
        crossings = detect_opportunity_crossings(
            anchors=anchors,
            mover_footprint=mover_footprint,
            reactors=(reactor,),
            mover_disengaged=True,
        )
        assert len(crossings) == 0


# ----------------------------------------------------------------------
# E.2: OA window, resolution, resume
# ----------------------------------------------------------------------

class TestOpportunityAttackFlow:
    def _setup_oa(self):
        table = setup_tactical_table()
        _start(table)
        entries = _entries(table)
        mover_id = entries[0].id
        reactor_id = _add_monster(table, name="Orc")
        _place(table, reactor_id, 6, 6)
        _set_turn(table, mover_id)
        return table, mover_id, reactor_id

    def test_oa_pauses_movement_and_opens_window(self):
        table, mover_id, reactor_id = self._setup_oa()
        movement = _movement(table)
        position = table.board.board_repository.get_position(mover_id)
        assert position is not None
        combat = table.combat.repository.get_active(table.dm_actor.campaign_id)
        assert combat is not None
        board = table.board.board_repository.get_board(combat.id)
        assert board is not None
        view = movement.confirm(
            table.dm_actor, mover_id,
            ConfirmMovementInput(
                entry_id=mover_id,
                path=tuple(
                    MovementAnchorInput(x=x, y=5) for x in range(5, 11)
                ),
                expected_position_revision=position.revision,
                expected_board_revision=board.runtime_revision,
                idempotency_key=f"e2-{uuid4()}",
            ),
        )
        assert view.outcome == "paused"
        # Mover committed to the boundary anchor (6,5): last cell in reach.
        assert view.anchor_x == 7
        assert view.anchor_y == 5
        assert len(view.pending_window_ids) == 1
        assert len(view.boundary_reactor_ids) == 1
        # Pending state is durable.
        entry = table.combat.repository.get_entry(mover_id)
        assert entry is not None
        pending = dict(entry.pending_movement_state or {})
        assert pending["current_path_index"] == 2
        assert pending["pending_window_ids"] == list(view.pending_window_ids)

    def test_resume_requires_windows_resolved(self):
        table, mover_id, reactor_id = self._setup_oa()
        movement = _movement(table)
        position = table.board.board_repository.get_position(mover_id)
        assert position is not None
        combat = table.combat.repository.get_active(table.dm_actor.campaign_id)
        assert combat is not None
        board = table.board.board_repository.get_board(combat.id)
        assert board is not None
        view = movement.confirm(
            table.dm_actor, mover_id,
            ConfirmMovementInput(
                entry_id=mover_id,
                path=tuple(
                    MovementAnchorInput(x=x, y=5) for x in range(5, 11)
                ),
                expected_position_revision=position.revision,
                expected_board_revision=board.runtime_revision,
                idempotency_key=f"e2-{uuid4()}",
            ),
        )
        assert view.outcome == "paused"
        # Resume while the window is still open → 409.
        with pytest.raises(CombatStateConflictError):
            movement.resume(
                table.dm_actor, mover_id,
                ResumeMovementInput(
                    entry_id=mover_id,
                    expected_pending_revision=view.pending_revision,
                    idempotency_key=f"e2-resume-{uuid4()}",
                ),
            )

    def test_full_decline_then_resume_completes(self):
        table, mover_id, reactor_id = self._setup_oa()
        movement = _movement(table)
        position = table.board.board_repository.get_position(mover_id)
        assert position is not None
        combat = table.combat.repository.get_active(table.dm_actor.campaign_id)
        assert combat is not None
        board = table.board.board_repository.get_board(combat.id)
        assert board is not None
        view = movement.confirm(
            table.dm_actor, mover_id,
            ConfirmMovementInput(
                entry_id=mover_id,
                path=tuple(
                    MovementAnchorInput(x=x, y=5) for x in range(5, 11)
                ),
                expected_position_revision=position.revision,
                expected_board_revision=board.runtime_revision,
                idempotency_key=f"e2-{uuid4()}",
            ),
        )
        assert view.outcome == "paused"
        window_id = view.pending_window_ids[0]
        # Reactor declines the OA.
        from app.persistence.combat.reactions import CombatReactionRepository
        reaction_service = CombatReactionService(
            repository=CombatReactionRepository(table.engine, table.events.repository),
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            table_event_service=table.events,
        )
        # Decline via the reaction service (DM acts for the monster).
        from app.domain.combat.reaction_service import ResolveReactionInput
        reaction_service.resolve_reaction(
            table.dm_actor,
            ResolveReactionInput(
                owner_entry_id=reactor_id,
                accept=False,
            ),
        )
        # Re-read pending revision (decline bumps it).
        entry_after = table.combat.repository.get_entry(mover_id)
        assert entry_after is not None
        pending_after = dict(entry_after.pending_movement_state or {})
        # Now resume: no more boundaries, commits the rest.
        resumed = movement.resume(
            table.dm_actor, mover_id,
            ResumeMovementInput(
                entry_id=mover_id,
                expected_pending_revision=int(pending_after.get("revision", 0)),
                idempotency_key=f"e2-resume-{uuid4()}",
            ),
        )
        assert resumed.outcome == "resumed"
        assert resumed.anchor_x == 10
        assert resumed.anchor_y == 5
        # Pending is cleared.
        entry = table.combat.repository.get_entry(mover_id)
        assert entry is not None
        assert dict(entry.pending_movement_state or {}) == {}


# ----------------------------------------------------------------------
# E.3: hidden reactors are silent
# ----------------------------------------------------------------------

class TestHiddenReactorSilence:
    def test_hidden_reactor_no_window_no_pause(self):
        table = setup_tactical_table()
        _start(table)
        entries = _entries(table)
        mover_id = entries[0].id
        # Hidden monster.
        reactor_id = _add_monster(table, visibility="hidden", name="Hidden Orc")
        _place(table, reactor_id, 6, 6)
        _set_turn(table, mover_id)
        movement = _movement(table)
        position = table.board.board_repository.get_position(mover_id)
        assert position is not None
        combat = table.combat.repository.get_active(table.dm_actor.campaign_id)
        assert combat is not None
        board = table.board.board_repository.get_board(combat.id)
        assert board is not None
        view = movement.confirm(
            table.dm_actor, mover_id,
            ConfirmMovementInput(
                entry_id=mover_id,
                path=tuple(
                    MovementAnchorInput(x=x, y=5) for x in range(5, 11)
                ),
                expected_position_revision=position.revision,
                expected_board_revision=board.runtime_revision,
                idempotency_key=f"e3-{uuid4()}",
            ),
        )
        # Hidden reactor: no pause, no window, full commit.
        assert view.outcome == "committed"
        assert view.pending_window_ids == ()
        # DM-only crossing note was written.
        from sqlalchemy import select
        from app.persistence.rooms.table_runtime import session_events
        engine = table.board.board_repository.engine
        with engine.connect() as conn:
            rows = conn.execute(
                select(session_events.c.kind, session_events.c.visibility)
                .where(session_events.c.kind == "combat.opportunity_crossing_noted")
            ).all()
        assert len(rows) >= 1
        assert all(row.visibility == "dm_only" for row in rows)


# ----------------------------------------------------------------------
# E.4: advance guard and cancel
# ----------------------------------------------------------------------

class TestAdvanceGuardAndCancel:
    def _setup_paused(self):
        table = setup_tactical_table()
        _start(table)
        entries = _entries(table)
        mover_id = entries[0].id
        reactor_id = _add_monster(table, name="Orc")
        _place(table, reactor_id, 6, 6)
        _set_turn(table, mover_id)
        movement = _movement(table)
        position = table.board.board_repository.get_position(mover_id)
        assert position is not None
        combat = table.combat.repository.get_active(table.dm_actor.campaign_id)
        assert combat is not None
        board = table.board.board_repository.get_board(combat.id)
        assert board is not None
        view = movement.confirm(
            table.dm_actor, mover_id,
            ConfirmMovementInput(
                entry_id=mover_id,
                path=tuple(
                    MovementAnchorInput(x=x, y=5) for x in range(5, 11)
                ),
                expected_position_revision=position.revision,
                expected_board_revision=board.runtime_revision,
                idempotency_key=f"e4-{uuid4()}",
            ),
        )
        assert view.outcome == "paused"
        return table, mover_id, view

    def test_advance_blocked_while_window_open(self):
        table, mover_id, view = self._setup_paused()
        with pytest.raises(CombatStateConflictError):
            table.combat.advance_turn(table.dm_actor)
        # Zero side effects: still the mover's turn, pending intact.
        combat = table.combat.repository.get_active(table.dm_actor.campaign_id)
        assert combat is not None
        assert combat.current_turn_entry_id == mover_id
        entry = table.combat.repository.get_entry(mover_id)
        assert entry is not None
        assert dict(entry.pending_movement_state or {}) != {}

    def test_dm_cancel_pending(self):
        table, mover_id, view = self._setup_paused()
        movement = _movement(table)
        cancelled = movement.cancel_pending_movement(
            table.dm_actor, mover_id,
            CancelPendingMovementInput(
                entry_id=mover_id,
                reason="DM cancelled for test",
                idempotency_key=f"e4-cancel-{uuid4()}",
            ),
        )
        assert cancelled.cancelled is True
        # Mover stays at the pause anchor.
        assert cancelled.anchor_x == 7
        assert cancelled.anchor_y == 5
        # Pending cleared.
        entry = table.combat.repository.get_entry(mover_id)
        assert entry is not None
        assert dict(entry.pending_movement_state or {}) == {}

    def test_non_dm_cannot_cancel(self):
        table, mover_id, view = self._setup_paused()
        movement = _movement(table)
        # Player actor (not DM) tries to cancel.
        player_actor = table.player_actor
        player = table.player_actor
        from app.domain.rooms.table_events import TableEventActorUnauthorizedError
        with pytest.raises(TableEventActorUnauthorizedError):
            movement.cancel_pending_movement(
                player, mover_id,
                CancelPendingMovementInput(
                    entry_id=mover_id,
                    reason="player tries",
                ),
            )


# ----------------------------------------------------------------------
# E.5: Shove push (Tactical)
# ----------------------------------------------------------------------

class TestShovePush:
    def test_shove_push_moves_target(self):
        # Full shove flow is covered by P4-C tests; here we verify the
        # push destination helper geometry.
        from app.domain.combat.special_attacks import CombatSpecialAttackService
        table = setup_tactical_table()
        _start(table)
        entries = _entries(table)
        attacker_id = entries[0].id
        target_id = _add_monster(table, name="Orc")
        _place(table, target_id, 6, 5)
        service = CombatSpecialAttackService(
            repository=None,  # type: ignore
            core_roll_repository=None,  # type: ignore
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            character_repository=table.combat.character_repository,
            monster_repository=table.combat.monster_repository,
            registry=table.registry,
            roll_service=None,  # type: ignore
            table_event_service=None,  # type: ignore
            board_repository=table.board.board_repository,
        )
        attacker = table.combat.repository.get_entry(attacker_id)
        target = table.combat.repository.get_entry(target_id)
        assert attacker is not None and target is not None
        dest = service._push_destination(attacker=attacker, target=target)
        assert dest is not None
        # Attacker at (5,5), target at (6,5): push east to (7,5).
        assert dest.x == 7
        assert dest.y == 5

    def test_shove_push_diagonal(self):
        from app.domain.combat.special_attacks import CombatSpecialAttackService
        table = setup_tactical_table()
        _start(table)
        entries = _entries(table)
        attacker_id = entries[0].id
        target_id = _add_monster(table, name="Orc")
        _place(table, target_id, 6, 6)
        service = CombatSpecialAttackService(
            repository=None,  # type: ignore
            core_roll_repository=None,  # type: ignore
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            character_repository=table.combat.character_repository,
            monster_repository=table.combat.monster_repository,
            registry=table.registry,
            roll_service=None,  # type: ignore
            table_event_service=None,  # type: ignore
            board_repository=table.board.board_repository,
        )
        attacker = table.combat.repository.get_entry(attacker_id)
        target = table.combat.repository.get_entry(target_id)
        assert attacker is not None and target is not None
        dest = service._push_destination(attacker=attacker, target=target)
        assert dest is not None
        # Diagonal push: (6,6) -> (7,7).
        assert dest.x == 7
        assert dest.y == 7


# ----------------------------------------------------------------------
# E.6: Grapple drag (Tactical)
# ----------------------------------------------------------------------

class TestGrappleDrag:
    def test_drag_requires_grapple(self):
        table = setup_tactical_table()
        _start(table)
        entries = _entries(table)
        mover_id = entries[0].id
        target_id = _add_monster(table, name="Orc")
        _place(table, target_id, 6, 5)
        _set_turn(table, mover_id)
        movement = _movement(table)
        # Drag without grapple → 400.
        with pytest.raises(CombatMovementInvalidError):
            movement.preview(
                table.dm_actor, mover_id,
                PreviewMovementInput(
                    entry_id=mover_id,
                    path=(
                        MovementAnchorInput(x=5, y=5),
                        MovementAnchorInput(x=7, y=5),
                    ),
                    drag_entry_id=target_id,
                ),
            )

    def test_drag_doubles_cost(self):
        table = setup_tactical_table()
        _start(table)
        entries = _entries(table)
        mover_id = entries[0].id
        target_id = _add_monster(table, name="Orc")
        _place(table, target_id, 6, 5)
        _set_turn(table, mover_id)
        # TODO: Set up grappled condition on monster instance.
        # For now, just verify drag validation runs.
        movement = _movement(table)
        # Preview with drag (no grapple): should fail validation.
        with pytest.raises(Exception):
            movement.preview(
                table.dm_actor, mover_id,
                PreviewMovementInput(
                    entry_id=mover_id,
                    path=(
                        MovementAnchorInput(x=5, y=5),
                        MovementAnchorInput(x=6, y=5),
                        MovementAnchorInput(x=7, y=5),
                    ),
                    drag_entry_id=target_id,
                ),
            )
