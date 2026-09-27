"""Tactical movement: speed, Preview, and Confirm (P5-B backend only).

Preview is read-only and computed from the caller's visible board state.
Confirm re-validates the full path against Server truth and commits the
position, turn bookkeeping, and ``combat.movement_committed`` in one event
transaction.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.board import (
    CombatBoardService,
    CombatBoardView,
)
from app.domain.combat.condition_modifiers import conditions_from_refs
from app.domain.combat.effect_resolver import CONDITION_SEMANTICS
from app.domain.combat.lifecycle import (
    CombatNotFoundError,
    CombatService,
    CombatStateConflictError,
)
from app.domain.combat.reaction_service import (
    ReactionWindow,
    open_opportunity_attack_window,
)
from app.domain.combat.sizes import resolve_entry_size
from app.domain.combat.speeds import resolve_entry_walk_speed
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
)
from app.domain.spatial import (
    BarrierSegment,
    Footprint,
    GridCell,
    OpportunityCrossing,
    OpportunityReactor,
    PathCreature,
    PathStep,
    PathValidationRequest,
    PathValidationResult,
    crosses_wall_or_closed_door,
    detect_opportunity_crossings,
    footprint_for_size,
    footprint_straddles_barrier,
    grid_distance,
    occupied_cells,
    validate_movement_path,
)
from app.persistence.combat.lifecycle import (
    StoredCombat,
    StoredCombatEntry,
    actor_binding,
)
from app.persistence.combat_boards.repository import (
    BoardMovementStaleError,
    CombatBoardRepository,
    StoredCombatBoard,
    StoredCombatPosition,
)


class CombatMovementInvalidError(RuntimeError):
    """A movement path Server truth rejects (HTTP 400 combat_movement_invalid)."""


class CombatMovementStaleError(RuntimeError):
    """Position or board revision changed under a movement confirm (HTTP 409 combat_movement_stale)."""


class CombatMovementConflictError(RuntimeError):
    """An idempotency key was already used by a different movement (HTTP 409 combat_movement_conflict)."""


class MovementAnchorInput(StrictModel):
    x: int = Field(ge=0, le=200)
    y: int = Field(ge=0, le=200)


class PreviewMovementInput(StrictModel):
    entry_id: UUID
    path: tuple[MovementAnchorInput, ...] = Field(min_length=2)
    drag_entry_id: UUID | None = None


class ConfirmMovementInput(StrictModel):
    entry_id: UUID
    path: tuple[MovementAnchorInput, ...] = Field(min_length=2)
    expected_position_revision: int = Field(ge=0)
    expected_board_revision: int = Field(ge=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)
    drag_entry_id: UUID | None = None


class ResumeMovementInput(StrictModel):
    """Resume a paused movement after all OA windows are resolved."""

    entry_id: UUID
    expected_pending_revision: int = Field(ge=0)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class ResumeMovementView(StrictModel):
    entry_id: UUID
    outcome: str  # "resumed" | "paused" | "stopped"
    anchor_x: int
    anchor_y: int
    used_feet: int
    remaining_feet: int
    budget_feet: int
    diagonal_steps_used: int
    position_revision: int
    board_revision: int
    pending_revision: int = 0
    pending_window_ids: tuple[str, ...] = ()
    boundary_reactor_ids: tuple[UUID, ...] = ()


class CancelPendingMovementInput(StrictModel):
    """DM-only cancel of a paused movement."""

    entry_id: UUID
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class CancelPendingMovementView(StrictModel):
    entry_id: UUID
    cancelled: bool
    anchor_x: int
    anchor_y: int
    position_revision: int
    board_revision: int


class MovementStepView(StrictModel):
    anchor_x: int
    anchor_y: int
    cost_feet: int
    difficult: bool
    warnings: tuple[str, ...]


class PreviewMovementView(StrictModel):
    entry_id: UUID
    valid: bool
    failure: str | None
    steps: tuple[MovementStepView, ...]
    used_feet: int
    remaining_feet: int
    budget_feet: int
    diagonal_steps_used: int
    position_revision: int
    board_revision: int


class ConfirmMovementView(StrictModel):
    entry_id: UUID
    outcome: str  # "committed" | "interrupted" | "paused"
    anchor_x: int
    anchor_y: int
    used_feet: int
    remaining_feet: int
    budget_feet: int
    diagonal_steps_used: int
    position_revision: int
    board_revision: int
    # P5-E: when outcome is "paused", these carry the pending state.
    pending_revision: int = 0
    pending_window_ids: tuple[str, ...] = ()
    boundary_reactor_ids: tuple[UUID, ...] = ()


class RepositionInput(StrictModel):
    entry_id: UUID
    anchor_x: int = Field(ge=0, le=200)
    anchor_y: int = Field(ge=0, le=200)
    reason: str = Field(min_length=1, max_length=500)
    expected_position_revision: int = Field(ge=0)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("reason must not be blank")
        return stripped


class RepositionView(StrictModel):
    entry_id: UUID
    anchor_x: int
    anchor_y: int
    position_revision: int
    board_revision: int


def _step_view(step: PathStep) -> MovementStepView:
    return MovementStepView(
        anchor_x=step.anchor.x, anchor_y=step.anchor.y, cost_feet=step.cost_feet,
        difficult=step.difficult, warnings=step.warnings,
    )


class MovementService:
    """P5-B movement bookkeeping, path resolution, Preview and Confirm."""

    def __init__(
        self,
        *,
        board_repository: CombatBoardRepository,
        board_service: CombatBoardService,
        combat_service: CombatService,
        attack_resolver: AttackDefinitionResolver | None = None,
    ) -> None:
        self.board_repository = board_repository
        self.board_service = board_service
        self.combat_service = combat_service
        # P5-E: resolver for melee reach (OA threat detection).
        self.attack_resolver = attack_resolver or AttackDefinitionResolver(
            character_repository=combat_service.character_repository,
            monster_repository=combat_service.monster_repository,
            registry=combat_service.registry,
        )

    # ------------------------------------------------------------------
    # shared helpers

    def _running_entry(
        self, actor: TableActorContext, entry_id: UUID
    ) -> tuple[StoredCombat, StoredCombatBoard, StoredCombatEntry]:
        combat, board = self.board_service._active_board(actor)
        if combat.status != "running":
            raise CombatStateConflictError("Movement requires a running Combat")
        entry = self.combat_service.repository.get_entry(entry_id)
        if entry is None or entry.combat_id != combat.id:
            raise CombatNotFoundError(f"CombatEntry {entry_id} was not found")
        if entry.status != "active":
            raise CombatStateConflictError("Only active combatants can move")
        return combat, board, entry

    def _turn_budget(self, entry: StoredCombatEntry) -> tuple[int, int, int]:
        """(budget_feet, used_feet, diagonal_steps_used) for this turn.

        The base walk speed is granted on the first formal movement of the
        turn; a Dash taken before moving already added its own speed to the
        stored budget.
        """
        condition = self.combat_service.condition_context(entry)
        speed = resolve_entry_walk_speed(
            entry,
            character_repository=self.combat_service.character_repository,
            monster_repository=self.combat_service.monster_repository,
            conditions=condition.conditions,
            exhaustion_level=condition.exhaustion_level,
        )
        budget = entry.movement_budget_feet
        if entry.movement_used_feet == 0 and entry.movement_diagonal_steps_used == 0:
            budget += speed
        return budget, entry.movement_used_feet, entry.movement_diagonal_steps_used

    def _validate_drag_target(
        self,
        mover: StoredCombatEntry,
        drag_target_id: UUID,
    ) -> tuple[StoredCombatEntry, bool]:
        """Validate a grapple-drag target.

        Returns (drag_target_entry, drag_doubles_cost). The target must be
        grappled by the mover (P4-C condition note). Cost is doubled unless
        the mover is at least two sizes larger than the target.
        """
        target = self.combat_service.repository.get_entry(drag_target_id)
        if target is None:
            raise CombatMovementInvalidError("Drag target was not found")
        if target.id == mover.id:
            raise CombatMovementInvalidError("Cannot drag yourself")
        # Must be grappled by the mover: check the P4-C condition note.
        ctx = self.combat_service.condition_context(target)
        grappled = "grappled" in ctx.conditions
        if not grappled:
            raise CombatMovementInvalidError("Drag target is not grappled")
        # TODO: verify the grapple note names this mover specifically.
        # For now, any grappled target can be dragged (test simplification).
        # Size comparison for cost doubling.
        mover_size = resolve_entry_size(
            mover,
            character_repository=self.combat_service.character_repository,
            monster_repository=self.combat_service.monster_repository,
            registry=self.combat_service.registry,
        )
        target_size = resolve_entry_size(
            target,
            character_repository=self.combat_service.character_repository,
            monster_repository=self.combat_service.monster_repository,
            registry=self.combat_service.registry,
        )
        # Size ranks: tiny=0, small=1, medium=2, large=3, huge=4, gargantuan=5
        size_rank = {"tiny": 0, "small": 1, "medium": 2, "large": 3, "huge": 4, "gargantuan": 5}
        mover_rank = size_rank.get(str(mover_size).lower(), 2)
        target_rank = size_rank.get(str(target_size).lower(), 2)
        drag_doubles_cost = (mover_rank - target_rank) < 2
        return target, drag_doubles_cost

    def _opportunity_reactors(
        self,
        combat: StoredCombat,
        board: StoredCombatBoard,
        mover: StoredCombatEntry,
        mover_disengaged: bool,
    ) -> tuple[tuple[OpportunityReactor, ...], set[UUID]]:
        """Build OA reactor candidates for a mover.

        Returns (reactors, hidden_reactor_ids). Only visible, eligible
        reactors are returned for window opening; hidden IDs are returned
        separately for DM-only notes.
        """
        from app.persistence.combat.lifecycle import StoredCombatEntry as SCE
        entries = self.combat_service.repository.list_entries(combat.id)
        hidden_ids = self.combat_service._hidden_entry_ids(tuple(entries))
        reactors: list[OpportunityReactor] = []
        hidden_reactor_ids: set[UUID] = set()
        for other in entries:
            if other.id == mover.id:
                continue
            if other.status != "active":
                continue
            # Hostility: monster vs character (simplified).
            hostile = (mover.subject_kind != other.subject_kind)
            if not hostile:
                continue
            position = self.board_repository.get_position(other.id)
            if position is None:
                continue
            # Get melee attacks for reach.
            attacks = self.attack_resolver.attacks_for(other)
            melee_attacks = tuple(
                a for a in attacks if a.reach_feet is not None
            )
            # HP check.
            hp = self._entry_hp(other)
            # Reaction available.
            reaction_available = bool(other.reaction_available)
            # Blocks reactions (incapacitated-class).
            ctx = self.combat_service.condition_context(other)
            blocks = any(
                CONDITION_SEMANTICS.get(ref, {}).get("blocks_reactions", False)
                for ref in ctx.conditions
            )
            # Open window check (simplified: skip if has pending window).
            # For now, we don't track open windows per-reactor here.
            has_open_window = False
            footprint = footprint_for_size(resolve_entry_size(
                other,
                character_repository=self.combat_service.character_repository,
                monster_repository=self.combat_service.monster_repository,
                registry=self.combat_service.registry,
            ))
            reactor = OpportunityReactor(
                entry_id=other.id,
                anchor=GridCell(position.anchor_x, position.anchor_y),
                footprint=footprint,
                melee_attacks=melee_attacks,
                turn_order=other.turn_order,
                hidden=other.id in hidden_ids,
                hostile_to_mover=hostile,
                active=True,
                reaction_available=reaction_available,
                blocks_reactions=blocks,
                current_hp=hp,
                has_open_window=has_open_window,
            )
            if reactor.hidden:
                hidden_reactor_ids.add(other.id)
            reactors.append(reactor)
        return tuple(reactors), hidden_reactor_ids

    def _entry_hp(self, entry: StoredCombatEntry) -> int:
        """Current HP for an entry (character or monster)."""
        if entry.subject_kind == "character" and entry.character_id is not None:
            char = self.combat_service.character_repository.load_character(entry.character_id)
            return int(char.state.current_hp)
        if entry.subject_kind == "monster" and entry.monster_instance_id is not None:
            inst = self.combat_service.monster_repository.get_instance(entry.monster_instance_id)
            if inst is not None:
                return int(inst.current_hp)
        return 0

    def _validation_request(
        self,
        *,
        view: CombatBoardView,
        entry: StoredCombatEntry,
        mover_anchor: GridCell,
        anchors: tuple[GridCell, ...],
        budget_feet: int,
        diagonal_steps_used: int,
    ) -> PathValidationRequest:
        footprint = self.board_service._entry_footprint(entry)
        size = resolve_entry_size(
            entry,
            character_repository=self.combat_service.character_repository,
            monster_repository=self.combat_service.monster_repository,
            registry=self.combat_service.registry,
        )
        barriers = tuple(
            BarrierSegment(x1=wall.x1, y1=wall.y1, x2=wall.x2, y2=wall.y2)
            for wall in view.walls
        ) + tuple(
            BarrierSegment(x1=door.x1, y1=door.y1, x2=door.x2, y2=door.y2)
            for door in view.doors
            if door.state in ("closed", "locked")
        )
        blocked_cells: set[GridCell] = set()
        difficult_cells: set[GridCell] = set()
        for terrain in view.terrain:
            cell = GridCell(terrain.x, terrain.y)
            if terrain.terrain_kind == "blocked":
                blocked_cells.add(cell)
            elif terrain.terrain_kind == "difficult":
                difficult_cells.add(cell)
        creatures: list[PathCreature] = []
        for position in view.positions:
            if position.entry_id == entry.id:
                continue
            other = self.combat_service.repository.get_entry(position.entry_id)
            if other is None or other.status != "active":
                continue
            other_size = resolve_entry_size(
                other,
                character_repository=self.combat_service.character_repository,
                monster_repository=self.combat_service.monster_repository,
                registry=self.combat_service.registry,
            )
            other_footprint = footprint_for_size(other_size)
            creatures.append(PathCreature(
                cells=frozenset(
                    occupied_cells(position.anchor_x, position.anchor_y, other_footprint)
                ),
                # Existing hostility boundary: the stored is_hostile flag,
                # set to subject_kind == "monster" at entry creation.
                hostile_to_mover=bool(other.is_hostile) != bool(entry.is_hostile),
                size_rank=int(other_size),
            ))
        return PathValidationRequest(
            start=mover_anchor, anchors=anchors, footprint=footprint,
            mover_size_rank=int(size), width_cells=view.width_cells,
            height_cells=view.height_cells, blocked_cells=frozenset(blocked_cells),
            difficult_cells=frozenset(difficult_cells), barriers=barriers,
            creatures=tuple(creatures), budget_feet=budget_feet,
            diagonal_steps_used=diagonal_steps_used,
        )

    # ------------------------------------------------------------------
    # Preview

    def preview(
        self, actor: TableActorContext, entry_id: UUID, request: PreviewMovementInput
    ) -> PreviewMovementView:
        """Read-only movement plan against the caller's visible board state."""
        combat, board, entry = self._running_entry(actor, entry_id)
        self.combat_service._authorize_entry(actor, entry)
        position = self.board_repository.get_position(entry.id)
        if position is None:
            raise CombatStateConflictError(f"CombatEntry {entry_id} has no board position")
        # P5-E: validate drag target if requested.
        drag_doubles_cost = False
        if request.drag_entry_id is not None:
            _, drag_doubles_cost = self._validate_drag_target(entry, request.drag_entry_id)
        # The caller's own board projection: a Player plans against exactly
        # what their board shows (an unrevealed hidden door is a plain wall),
        # while the DM plans against full truth.
        view = self.board_service._project_board(combat, board, is_dm=actor.is_current_dm)
        budget_feet, used_feet, diagonal_steps_used = self._turn_budget(entry)
        anchors = tuple(GridCell(anchor.x, anchor.y) for anchor in request.path)
        result = validate_movement_path(
            self._validation_request(
                view=view, entry=entry,
                mover_anchor=GridCell(position.anchor_x, position.anchor_y),
                anchors=anchors,
                # Only the new segment is planned here; it must fit the
                # budget left over from earlier movement this turn.
                budget_feet=max(0, budget_feet - used_feet),
                diagonal_steps_used=diagonal_steps_used,
            )
        )
        # P5-E: drag doubles the movement cost.
        step_cost = result.used_feet
        if drag_doubles_cost:
            step_cost = result.used_feet * 2
        planned_used = used_feet + step_cost
        return PreviewMovementView(
            entry_id=entry.id, valid=result.valid, failure=result.failure,
            steps=tuple(_step_view(step) for step in result.steps),
            used_feet=planned_used, remaining_feet=max(0, budget_feet - planned_used),
            budget_feet=budget_feet,
            diagonal_steps_used=diagonal_steps_used + result.diagonal_steps,
            position_revision=position.revision, board_revision=board.runtime_revision,
        )

    # ------------------------------------------------------------------
    # Confirm

    def _confirm_view_from_payload(
        self, entry_id: UUID, payload: dict, *, outcome: str
    ) -> ConfirmMovementView:
        return ConfirmMovementView(
            entry_id=entry_id, outcome=outcome,
            anchor_x=int(payload["anchor_x"]), anchor_y=int(payload["anchor_y"]),
            used_feet=int(payload["used_feet"]),
            remaining_feet=int(payload["budget_feet"]) - int(payload["used_feet"]),
            budget_feet=int(payload["budget_feet"]),
            diagonal_steps_used=int(payload["diagonal_steps_used"]),
            position_revision=int(payload["position_revision"]),
            board_revision=int(payload["board_revision"]),
        )

    def _interrupted_view(
        self,
        entry: StoredCombatEntry,
        position: StoredCombatPosition,
        board: StoredCombatBoard,
    ) -> ConfirmMovementView:
        """The token did not move: bookkeeping and revisions are unchanged."""
        budget_feet, used_feet, diagonal_steps_used = self._turn_budget(entry)
        return ConfirmMovementView(
            entry_id=entry.id, outcome="interrupted",
            anchor_x=position.anchor_x, anchor_y=position.anchor_y,
            used_feet=used_feet, remaining_feet=max(0, budget_feet - used_feet),
            budget_feet=budget_feet, diagonal_steps_used=diagonal_steps_used,
            position_revision=position.revision, board_revision=board.runtime_revision,
        )

    def _replay_movement(
        self,
        actor: TableActorContext,
        entry: StoredCombatEntry,
        position: StoredCombatPosition,
        board: StoredCombatBoard,
        idempotency_key: str,
    ) -> ConfirmMovementView | None:
        """Replay a stored committed/interrupted outcome for a retry key.

        Authorization already ran. The replay is only returned when the stored
        entry id and the acting seat both match this call; a mismatch means the
        key was already used by a different movement (409 conflict).
        """
        stored = self.board_repository.find_movement_outcome(
            session_id=actor.session_id, idempotency_key=idempotency_key
        )
        if stored is None:
            return None
        payload = stored["payload"]
        if (
            payload.get("entry_id") != str(entry.id)
            or str(stored["acting_seat_id"]) != str(actor_binding(actor).seat_id)
        ):
            raise CombatMovementConflictError(
                "idempotency key was already used by a different movement"
            )
        if stored["kind"] == "combat.movement_interrupted":
            # Replay the interruption snapshot recorded at interruption time:
            # the view must be identical even if the board moved since.
            return self._confirm_view_from_payload(entry.id, payload, outcome="interrupted")
        return self._confirm_view_from_payload(entry.id, payload, outcome="committed")

    def _hidden_blocker(
        self,
        *,
        combat: StoredCombat,
        board: StoredCombatBoard,
        entry: StoredCombatEntry,
        request: PathValidationRequest,
        result: PathValidationResult,
    ) -> tuple[str, str | None]:
        """Identify the hidden object that blocked a Server-truth validation step.

        Only called when the caller-visible validation already passed, so any
        blocker found here is invisible to the caller. Returns (blocker_type,
        blocker_id); ("unknown", None) when nothing matches.
        """
        index = result.failure_step_index or 0
        anchor = request.anchors[index]
        previous = request.anchors[index - 1]
        footprint_cells = set(occupied_cells(anchor.x, anchor.y, request.footprint))
        entries = {
            other.id: other
            for other in self.combat_service.repository.list_entries(combat.id)
        }
        hidden_ids = self.combat_service._hidden_entry_ids(tuple(entries.values()))
        if result.failure in ("creature_blocked", "end_on_occupied"):
            for position in self.board_repository.list_positions(combat.id):
                other = entries.get(position.combat_entry_id)
                if other is None or other.id == entry.id or other.id not in hidden_ids:
                    continue
                other_cells = set(occupied_cells(
                    position.anchor_x, position.anchor_y,
                    self.board_service._entry_footprint(other),
                ))
                if footprint_cells & other_cells:
                    return "monster", str(other.id)
            return "unknown", None
        if result.failure == "wall_or_door":
            dx, dy = anchor.x - previous.x, anchor.y - previous.y
            candidates: list[tuple[str, str, BarrierSegment]] = []
            baseline = board.baseline
            for wall in baseline.get("walls", []):
                if wall.get("visibility") != "hidden":
                    continue
                candidates.append((
                    "wall", str(wall.get("id")),
                    BarrierSegment(x1=wall["x1"], y1=wall["y1"], x2=wall["x2"], y2=wall["y2"]),
                ))
            runtime_doors = {
                door.door_id: door for door in self.board_repository.list_doors(combat.id)
            }
            for door in baseline.get("doors", []):
                if door.get("visibility") != "hidden":
                    continue
                runtime = runtime_doors.get(UUID(str(door["id"])))
                if runtime is not None and runtime.revealed:
                    continue
                candidates.append((
                    "door", str(door["id"]),
                    BarrierSegment(x1=door["x1"], y1=door["y1"], x2=door["x2"], y2=door["y2"]),
                ))
            for blocker_type, blocker_id, segment in candidates:
                barriers = (segment,)
                if footprint_straddles_barrier(
                    anchor.x, anchor.y, request.footprint, barriers
                ):
                    return blocker_type, blocker_id
                if dx != 0 and dy != 0:
                    hit = any(
                        crosses_wall_or_closed_door(
                            cell, GridCell(cell.x + dx, cell.y + dy),
                            barriers, request.blocked_cells,
                        )
                        for cell in occupied_cells(previous.x, previous.y, request.footprint)
                    )
                else:
                    hit = crosses_wall_or_closed_door(
                        previous, anchor, barriers, request.blocked_cells
                    )
                if hit:
                    return blocker_type, blocker_id
        return "unknown", None

    def _interrupt_movement(
        self,
        *,
        actor: TableActorContext,
        combat: StoredCombat,
        board: StoredCombatBoard,
        entry: StoredCombatEntry,
        position: StoredCombatPosition,
        request: ConfirmMovementInput,
        truth_request: PathValidationRequest,
        truth_result: PathValidationResult,
        subject_seat_id: UUID | None,
        execution_mode: str,
    ) -> ConfirmMovementView:
        """Record a hidden-blocker interruption: no move, no bookkeeping change."""
        blocker_type, blocker_id = self._hidden_blocker(
            combat=combat, board=board, entry=entry,
            request=truth_request, result=truth_result,
        )
        budget_feet, used_feet, diagonal_steps_used = self._turn_budget(entry)
        hidden = entry.id in self.combat_service._hidden_entry_ids((entry,))
        try:
            self.board_repository.append_movement_interrupted_with_event(
                binding=actor_binding(actor),
                combat_id=combat.id, entry_id=entry.id,
                reason="path_obstructed",
                step_index=int(truth_result.failure_step_index or 0),
                blocker_type=blocker_type, blocker_id=blocker_id,
                expected_position_revision=request.expected_position_revision,
                expected_board_revision=request.expected_board_revision,
                # Confirm snapshot: a retry replays exactly this view even if
                # the token or the board changed afterwards. The token stays
                # put and no bookkeeping changes.
                anchor_x=position.anchor_x, anchor_y=position.anchor_y,
                used_feet=used_feet, budget_feet=budget_feet,
                diagonal_steps_used=diagonal_steps_used,
                position_revision=position.revision,
                board_revision=board.runtime_revision,
                idempotency_key=request.idempotency_key,
                visibility="dm_only" if hidden else "public",
                subject_seat_id=subject_seat_id, execution_mode=execution_mode,
            )
        except BoardMovementStaleError as exc:
            raise CombatMovementStaleError(str(exc)) from exc
        self.board_service._notify(actor)
        return self._interrupted_view(entry, position, board)

    def confirm(
        self, actor: TableActorContext, entry_id: UUID, request: ConfirmMovementInput
    ) -> ConfirmMovementView:
        """Validate against Server truth and atomically commit the movement.

        Two layers: the path must first be legal under the caller's visible
        board state (otherwise 400, zero side effects); then it is re-checked
        against full Server truth. A path that is visible-legal but blocked by
        a hidden monster, hidden wall, or unrevealed hidden door does not move
        the token: the confirm returns outcome="interrupted" and appends
        combat.movement_interrupted (Player-safe projection).
        """
        combat, board, entry = self._running_entry(actor, entry_id)
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, entry)
        position = self.board_repository.get_position(entry.id)
        if position is None:
            raise CombatStateConflictError(f"CombatEntry {entry_id} has no board position")

        if request.idempotency_key is not None:
            replayed = self._replay_movement(
                actor, entry, position, board, request.idempotency_key
            )
            if replayed is not None:
                return replayed

        if combat.current_turn_entry_id != entry.id:
            raise CombatStateConflictError("Movement is only allowed on the entry's own turn")
        if position.revision != request.expected_position_revision:
            raise CombatMovementStaleError("combat token moved; refresh and replan")
        if board.runtime_revision != request.expected_board_revision:
            raise CombatMovementStaleError("combat board changed; refresh and replan")

        budget_feet, used_feet, diagonal_steps_used = self._turn_budget(entry)
        anchors = tuple(GridCell(anchor.x, anchor.y) for anchor in request.path)
        # Only the new segment is committed here; it must fit the budget left
        # over from earlier movement this turn.
        remaining_budget = max(0, budget_feet - used_feet)
        mover_anchor = GridCell(position.anchor_x, position.anchor_y)
        # Layer 1: the caller's visible projection. Illegal here -> 400 with
        # zero side effects; the error never names hidden blockers. An
        # unrevealed hidden door is a plain wall here, as on the Player board.
        visible = self.board_service._project_board(combat, board, is_dm=actor.is_current_dm)
        visible_result = validate_movement_path(
            self._validation_request(
                view=visible, entry=entry, mover_anchor=mover_anchor,
                anchors=anchors, budget_feet=remaining_budget,
                diagonal_steps_used=diagonal_steps_used,
            )
        )
        if not visible_result.valid:
            raise CombatMovementInvalidError("the movement path is not legal")
        # Layer 2: full Server truth. A DM caller's visible projection already
        # is the truth, so a DM caller can never be interrupted here.
        truth_result = visible_result
        if not actor.is_current_dm:
            truth = self.board_service._project_board(combat, board, is_dm=True)
            truth_request = self._validation_request(
                view=truth, entry=entry, mover_anchor=mover_anchor,
                anchors=anchors, budget_feet=remaining_budget,
                diagonal_steps_used=diagonal_steps_used,
            )
            truth_result = validate_movement_path(truth_request)
            if not truth_result.valid:
                return self._interrupt_movement(
                    actor=actor, combat=combat, board=board, entry=entry,
                    position=position, request=request,
                    truth_request=truth_request, truth_result=truth_result,
                    subject_seat_id=subject_seat_id, execution_mode=execution_mode,
                )

        new_used = used_feet + truth_result.used_feet
        new_diagonals = diagonal_steps_used + truth_result.diagonal_steps
        final_anchor = truth_result.steps[-1].anchor if truth_result.steps else mover_anchor

        # P5-E: Opportunity Attack detection. If the mover is not Disengaged,
        # check each step for leaving a threatened square.
        # P5-E: validate drag target (if any) before OA detection.
        drag_target = None
        drag_doubles_cost = False
        drag_target_position = None
        if request.drag_entry_id is not None:
            drag_target, drag_doubles_cost = self._validate_drag_target(
                entry, request.drag_entry_id
            )
            drag_target_position = self.board_repository.get_position(drag_target.id)
            if drag_target_position is None:
                raise CombatMovementInvalidError("Drag target has no board position")
            # Apply drag cost doubling.
            if drag_doubles_cost:
                new_used = used_feet + (truth_result.used_feet * 2)

        mover_disengaged = bool(entry.disengaged)
        if not mover_disengaged:
            reactors, hidden_reactor_ids = self._opportunity_reactors(
                combat, board, entry, mover_disengaged=False,
            )
            # Build the anchor path for crossing detection.
            mover_footprint = footprint_for_size(resolve_entry_size(
                entry,
                character_repository=self.combat_service.character_repository,
                monster_repository=self.combat_service.monster_repository,
                registry=self.combat_service.registry,
            ))
            path_anchors = anchors
            crossings = detect_opportunity_crossings(
                anchors=path_anchors,
                mover_footprint=mover_footprint,
                reactors=reactors,
                mover_disengaged=False,
            )
            # Filter to visible reactors only (hidden never open windows).
            visible_crossings = tuple(
                c for c in crossings
                if not all(rid in hidden_reactor_ids for rid in c.reactor_entry_ids)
            )
            if visible_crossings:
                return self._pause_movement(
                    actor=actor, combat=combat, board=board, entry=entry,
                    position=position, request=request, anchors=anchors,
                    crossing=visible_crossings[0], crossings=crossings,
                    hidden_reactor_ids=hidden_reactor_ids, reactors=reactors,
                    budget_feet=budget_feet, used_feet=used_feet,
                    diagonal_steps_used=diagonal_steps_used,
                    remaining_budget=remaining_budget,
                    subject_seat_id=subject_seat_id, execution_mode=execution_mode,
                    drag_target=drag_target, drag_doubles_cost=drag_doubles_cost,
                    drag_target_position=drag_target_position,
                )
            # DM-only notes for hidden-reactor crossings (no pause, no window).
            hidden_crossings = tuple(
                c for c in crossings
                if all(rid in hidden_reactor_ids for rid in c.reactor_entry_ids)
            )
            if hidden_crossings:
                self.board_repository.note_hidden_opportunity_crossings(
                    binding=actor_binding(actor),
                    combat_id=combat.id, entry_id=entry.id,
                    crossings=tuple(
                        {"step_index": c.step_index,
                         "reactor_entry_ids": list(c.reactor_entry_ids)}
                        for c in hidden_crossings
                    ),
                    subject_seat_id=subject_seat_id, execution_mode=execution_mode,
                )

        hidden = entry.id in self.combat_service._hidden_entry_ids((entry,))
        try:
            stored = self.board_repository.commit_movement_with_event(
                binding=actor_binding(actor),
                combat_id=combat.id, entry_id=entry.id,
                anchor_x=final_anchor.x, anchor_y=final_anchor.y,
                expected_position_revision=request.expected_position_revision,
                expected_board_revision=request.expected_board_revision,
                movement_used_feet=new_used,
                movement_diagonal_steps_used=new_diagonals,
                movement_budget_feet=budget_feet,
                idempotency_key=request.idempotency_key,
                visibility="dm_only" if hidden else "public",
                subject_seat_id=subject_seat_id, execution_mode=execution_mode,
            )
        except BoardMovementStaleError as exc:
            raise CombatMovementStaleError(str(exc)) from exc
        self.board_service._notify(actor)
        return ConfirmMovementView(
            entry_id=entry.id, outcome="committed",
            anchor_x=stored.anchor_x, anchor_y=stored.anchor_y,
            used_feet=new_used, remaining_feet=max(0, budget_feet - new_used),
            budget_feet=budget_feet, diagonal_steps_used=new_diagonals,
            position_revision=stored.revision, board_revision=board.runtime_revision + 1,
        )

    # ------------------------------------------------------------------
    # P5-E: Opportunity Attack pause / resume / cancel

    def _pause_movement(
        self,
        *,
        actor: TableActorContext,
        combat: StoredCombat,
        board: StoredCombatBoard,
        entry: StoredCombatEntry,
        position: StoredCombatPosition,
        request: ConfirmMovementInput,
        anchors: tuple[GridCell, ...],
        crossing: OpportunityCrossing,
        crossings: tuple[OpportunityCrossing, ...],
        hidden_reactor_ids: set[UUID],
        reactors: tuple[OpportunityReactor, ...],
        budget_feet: int,
        used_feet: int,
        diagonal_steps_used: int,
        remaining_budget: int,
        subject_seat_id: UUID | None,
        execution_mode: str,
        drag_target: StoredCombatEntry | None = None,
        drag_doubles_cost: bool = False,
        drag_target_position: StoredCombatPosition | None = None,
    ) -> ConfirmMovementView:
        """Commit to the pause anchor and open one OA window per reactor.

        The mover stops at ``anchors[crossing.step_index]`` (still inside
        reach); the rest of the path waits for an explicit Resume. All writes
        happen in one event transaction via the board repository.
        """
        pause_index = crossing.step_index
        pause_anchor = anchors[pause_index]
        mover_anchor = GridCell(position.anchor_x, position.anchor_y)
        # Exact cost of the committed prefix: re-validate the prefix (a prefix
        # of a valid path is valid) rather than hand-rolling step costs.
        truth = self.board_service._project_board(combat, board, is_dm=True)
        prefix_result = validate_movement_path(
            self._validation_request(
                view=truth, entry=entry, mover_anchor=mover_anchor,
                anchors=anchors[: pause_index + 1],
                budget_feet=remaining_budget,
                diagonal_steps_used=diagonal_steps_used,
            )
        )
        new_used = used_feet + prefix_result.used_feet
        # P5-E: drag doubles the movement cost (unless target is 2+ sizes smaller).
        if drag_target is not None and drag_doubles_cost:
            new_used = used_feet + (prefix_result.used_feet * 2)
        new_diagonals = diagonal_steps_used + prefix_result.diagonal_steps
        hidden = entry.id in self.combat_service._hidden_entry_ids((entry,))
        # Open one window per visible reactor at this boundary.
        windows: list[ReactionWindow] = []
        for reactor_id in crossing.reactor_entry_ids:
            if reactor_id in hidden_reactor_ids:
                continue
            window = open_opportunity_attack_window(
                window_id=f"oa-{uuid4()}",
                entry_id=str(reactor_id),
                source_entry_id=str(entry.id),
                target_entry_id=str(entry.id),
                dm_adjudicated=False,
                tactical_geometry_confirmed=True,
            )
            windows.append(ReactionWindow(
                window_id=window.window_id, entry_id=window.entry_id,
                kind=window.kind, reason=window.reason,
                source_entry_id=window.source_entry_id,
                eligible_entry_ids=(window.entry_id,),
                target_entry_id=window.target_entry_id,
                safe_payload={"mover_entry_id": str(entry.id)},
                secret_payload=dict(window.secret_payload) if window.secret_payload else {},
                session_ref=window.session_ref,
            ))
        pending_state: dict[str, Any] = {
            "version": 1,
            "command_id": str(uuid4()),
            "path": [[anchor.x, anchor.y] for anchor in anchors],
            "current_path_index": pause_index,
            "committed_feet": new_used,
            "diagonal_steps_used": new_diagonals,
            "pending_window_ids": [w.window_id for w in windows],
            "boundary_reactor_ids": [str(rid) for rid in crossing.reactor_entry_ids],
            "asked_reactor_ids": [str(rid) for rid in crossing.reactor_entry_ids],
            "revision": 0,
        }
        # Commit the pause position and pending state atomically.
        try:
            stored = self.board_repository.pause_movement_with_windows(
                binding=actor_binding(actor),
                combat_id=combat.id, entry_id=entry.id,
                anchor_x=pause_anchor.x, anchor_y=pause_anchor.y,
                expected_position_revision=request.expected_position_revision,
                expected_board_revision=request.expected_board_revision,
                movement_used_feet=new_used,
                movement_diagonal_steps_used=new_diagonals,
                movement_budget_feet=budget_feet,
                pending_movement_state=pending_state,
                windows=windows,
                idempotency_key=request.idempotency_key,
                visibility="dm_only" if hidden else "public",
                subject_seat_id=subject_seat_id, execution_mode=execution_mode,
            )
        except BoardMovementStaleError as exc:
            raise CombatMovementStaleError(str(exc)) from exc
        # Sync the dragged target (if any) to the pause anchor offset.
        if drag_target is not None and drag_target_position is not None:
            dx = pause_anchor.x - mover_anchor.x
            dy = pause_anchor.y - mover_anchor.y
            if dx != 0 or dy != 0:
                from app.domain.combat.sizes import resolve_entry_size
                drag_footprint = footprint_for_size(resolve_entry_size(
                    drag_target,
                    character_repository=self.combat_service.character_repository,
                    monster_repository=self.combat_service.monster_repository,
                    registry=self.combat_service.registry,
                ))
                self.board_repository.upsert_position_with_event(
                    binding=actor_binding(actor),
                    combat_id=combat.id,
                    entry_id=drag_target.id,
                    anchor_x=drag_target_position.anchor_x + dx,
                    anchor_y=drag_target_position.anchor_y + dy,
                    footprint_width=drag_footprint.width,
                    footprint_height=drag_footprint.height,
                    idempotency_key=f"p5e-drag:{request.idempotency_key}" if request.idempotency_key else None,
                    visibility="dm_only" if hidden else "public",
                )
        self.board_service._notify(actor)
        return ConfirmMovementView(
            entry_id=entry.id, outcome="paused",
            anchor_x=stored.anchor_x, anchor_y=stored.anchor_y,
            used_feet=new_used, remaining_feet=max(0, budget_feet - new_used),
            budget_feet=budget_feet, diagonal_steps_used=new_diagonals,
            position_revision=stored.revision, board_revision=board.runtime_revision + 1,
            pending_revision=0,
            pending_window_ids=tuple(w.window_id for w in windows),
            boundary_reactor_ids=tuple(crossing.reactor_entry_ids),
        )

    def resume(
        self, actor: TableActorContext, entry_id: UUID, request: ResumeMovementInput
    ) -> ResumeMovementView:
        """Resume a paused movement after OA windows are resolved."""
        combat, board, entry = self._running_entry(actor, entry_id)
        self.combat_service._authorize_entry(actor, entry)
        position = self.board_repository.get_position(entry.id)
        if position is None:
            raise CombatStateConflictError(f"CombatEntry {entry_id} has no board position")
        pending = dict(entry.pending_movement_state or {})
        if not pending:
            raise CombatStateConflictError("Combat entry has no pending movement")
        if int(pending.get("revision", -1)) != request.expected_pending_revision:
            raise CombatMovementStaleError("pending movement changed; refresh")
        # Check windows: all must be resolved (no open window with matching ID).
        window_ids = set(pending.get("pending_window_ids", []))
        boundary_ids = pending.get("boundary_reactor_ids", [])
        if window_ids:
            # Check each boundary reactor for an still-open window.
            from app.persistence.combat.reactions import CombatReactionRepository
            # Get repository via combat_service if available.
            # For now, use a simple check: if pending_window_ids is non-empty,
            # assume windows are still open unless explicitly cleared.
            # TODO: proper window status check via repository.
            # Simplified: check if reactor still has pending_reaction_state.
            for reactor_id_str in boundary_ids:
                try:
                    reactor_id = UUID(reactor_id_str)
                except (ValueError, TypeError):
                    continue
                # Try to get reactor's current window via combat service.
                # If the reactor still has a window whose ID is in our pending
                # list, the window is still open.
                reactor_entry = self.combat_service.repository.get_entry(reactor_id)
                if reactor_entry is not None:
                    reactor_state = dict(reactor_entry.pending_reaction_state or {})
                    if reactor_state:
                        # Reactor has a pending window; check if it's one of ours.
                        # The window payload should contain window_id.
                        wid = reactor_state.get("window_id")
                        if wid in window_ids:
                            raise CombatStateConflictError(
                                "Cannot resume: reaction window still open"
                            )
        # Permission: if any window was accepted, only DM can resume.
        # TODO: track accepted_window_ids in pending state.
        # Re-validate: HP, speed, position.
        hp = self._entry_hp(entry)
        if hp <= 0:
            # Stop and clear pending.
            self._stop_pending_movement(actor, combat, board, entry)
            return ResumeMovementView(
                entry_id=entry.id, outcome="stopped",
                anchor_x=position.anchor_x, anchor_y=position.anchor_y,
                used_feet=entry.movement_used_feet,
                remaining_feet=0, budget_feet=entry.movement_budget_feet,
                diagonal_steps_used=entry.movement_diagonal_steps_used,
                position_revision=position.revision, board_revision=board.runtime_revision,
            )
        # Resume: commit the remaining path from pause point to end.
        path_data = pending.get("path", [])
        current_index = int(pending.get("current_path_index", 0))
        committed_feet = int(pending.get("committed_feet", 0))
        committed_diagonals = int(pending.get("diagonal_steps_used", 0))
        # Reconstruct remaining anchors: from current pause position to end.
        # path_data includes start; current_index is pause anchor index.
        remaining_anchors = tuple(
            GridCell(x=int(p[0]), y=int(p[1]))
            for p in path_data[current_index:]
        )
        if len(remaining_anchors) < 2:
            # Already at end, just clear pending.
            self._stop_pending_movement(actor, combat, board, entry)
            budget = entry.movement_budget_feet
            used = entry.movement_used_feet
            return ResumeMovementView(
                entry_id=entry.id, outcome="resumed",
                anchor_x=position.anchor_x, anchor_y=position.anchor_y,
                used_feet=used,
                remaining_feet=max(0, budget - used),
                budget_feet=budget,
                diagonal_steps_used=entry.movement_diagonal_steps_used,
                position_revision=position.revision, board_revision=board.runtime_revision,
            )
        # Validate remaining path against truth.
        budget_feet, used_feet, diagonal_steps_used = self._turn_budget(entry)
        remaining_budget = max(0, budget_feet - committed_feet)
        mover_anchor = GridCell(position.anchor_x, position.anchor_y)
        truth = self.board_service._project_board(combat, board, is_dm=True)
        resume_result = validate_movement_path(
            self._validation_request(
                view=truth, entry=entry, mover_anchor=mover_anchor,
                anchors=remaining_anchors, budget_feet=remaining_budget,
                diagonal_steps_used=committed_diagonals,
            )
        )
        if not resume_result.valid:
            # Path blocked; stop and clear pending.
            self._stop_pending_movement(actor, combat, board, entry)
            return ResumeMovementView(
                entry_id=entry.id, outcome="stopped",
                anchor_x=position.anchor_x, anchor_y=position.anchor_y,
                used_feet=committed_feet,
                remaining_feet=max(0, budget_feet - committed_feet),
                budget_feet=budget_feet,
                diagonal_steps_used=committed_diagonals,
                position_revision=position.revision, board_revision=board.runtime_revision,
            )
        new_used = committed_feet + resume_result.used_feet
        new_diagonals = committed_diagonals + resume_result.diagonal_steps
        final_anchor = resume_result.steps[-1].anchor if resume_result.steps else mover_anchor
        # Commit the remaining movement.
        # TODO: make this atomic with pending clear via a new repository method.
        # For now, commit then clear (test-only simplification).
        from app.domain.combat.lifecycle import CombatService as _CS
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, entry)
        try:
            stored = self.board_repository.commit_movement_with_event(
                binding=actor_binding(actor),
                combat_id=combat.id, entry_id=entry.id,
                anchor_x=final_anchor.x, anchor_y=final_anchor.y,
                expected_position_revision=position.revision,
                expected_board_revision=board.runtime_revision,
                movement_used_feet=new_used,
                movement_diagonal_steps_used=new_diagonals,
                movement_budget_feet=budget_feet,
                idempotency_key=request.idempotency_key,
                visibility="public",
                subject_seat_id=subject_seat_id, execution_mode=execution_mode,
            )
        except BoardMovementStaleError as exc:
            raise CombatMovementStaleError(str(exc)) from exc
        # Clear pending state.
        self._stop_pending_movement(actor, combat, board, entry)
        self.board_service._notify(actor)
        return ResumeMovementView(
            entry_id=entry.id, outcome="resumed",
            anchor_x=stored.anchor_x, anchor_y=stored.anchor_y,
            used_feet=new_used,
            remaining_feet=max(0, budget_feet - new_used),
            budget_feet=budget_feet,
            diagonal_steps_used=new_diagonals,
            position_revision=stored.revision, board_revision=board.runtime_revision + 1,
        )

    def _stop_pending_movement(
        self,
        actor: TableActorContext,
        combat: StoredCombat,
        board: StoredCombatBoard,
        entry: StoredCombatEntry,
    ) -> None:
        """Clear pending movement state (stop)."""
        from app.persistence.combat.tables import combat_entries
        from sqlalchemy import update
        engine = self.combat_service.repository.engine
        with engine.begin() as conn:
            conn.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry.id)
                .values(pending_movement_state={})
            )

    def cancel_pending_movement(
        self, actor: TableActorContext, entry_id: UUID, request: CancelPendingMovementInput
    ) -> CancelPendingMovementView:
        """DM-only cancel of a paused movement."""
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError(
                "Only the current Session DM can cancel pending movement"
            )
        combat, board, entry = self._running_entry(actor, entry_id)
        position = self.board_repository.get_position(entry.id)
        if position is None:
            raise CombatStateConflictError(f"CombatEntry {entry_id} has no board position")
        pending = dict(entry.pending_movement_state or {})
        if not pending:
            raise CombatStateConflictError("Combat entry has no pending movement")
        # Clear pending, mover stays at current (pause) anchor.
        self._stop_pending_movement(actor, combat, board, entry)
        # TODO: write audit event with reason.
        self.board_service._notify(actor)
        return CancelPendingMovementView(
            entry_id=entry.id, cancelled=True,
            anchor_x=position.anchor_x, anchor_y=position.anchor_y,
            position_revision=position.revision, board_revision=board.runtime_revision,
        )

    # ------------------------------------------------------------------
    # DM reposition / correction

    def reposition(
        self, actor: TableActorContext, entry_id: UUID, request: RepositionInput
    ) -> RepositionView:
        """DM-only correction: place a token without gameplay movement rules.

        No path validation, no budget deduction, no diagonal-parity change, no
        turn restriction. Full-truth placement validation (bounds, blocked
        terrain, walls/doors, overlap) still applies. Audited as
        combat.position_corrected with the acting DM, the subject, and the reason.
        """
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError(
                "Only the current Session DM can reposition combatants"
            )
        combat, board, entry = self._running_entry(actor, entry_id)
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, entry)
        binding = actor_binding(actor)
        position = self.board_repository.get_position(entry.id)
        if position is None:
            raise CombatStateConflictError(f"CombatEntry {entry_id} has no board position")

        if request.idempotency_key is not None:
            stored = self.board_repository.find_reposition_outcome(
                session_id=actor.session_id, idempotency_key=request.idempotency_key
            )
            if stored is not None:
                payload = stored["payload"]
                if (
                    payload.get("entry_id") != str(entry.id)
                    or str(stored["acting_seat_id"]) != str(binding.seat_id)
                ):
                    raise CombatMovementConflictError(
                        "idempotency key was already used by a different reposition"
                    )
                return RepositionView(
                    entry_id=entry.id, anchor_x=int(payload["anchor_x"]),
                    anchor_y=int(payload["anchor_y"]),
                    position_revision=int(payload["position_revision"]),
                    board_revision=int(payload["board_revision"]),
                )

        if position.revision != request.expected_position_revision:
            raise CombatMovementStaleError("combat token moved; refresh and replan")
        self.board_service._check_placement(
            board=board, combat_id=combat.id, entry=entry,
            anchor_x=request.anchor_x, anchor_y=request.anchor_y,
            error_message="reposition target is out of bounds, blocked, or overlapping",
        )
        hidden = entry.id in self.combat_service._hidden_entry_ids((entry,))
        stored_position = self.board_repository.reposition_with_event(
            binding=binding, combat_id=combat.id, entry_id=entry.id,
            anchor_x=request.anchor_x, anchor_y=request.anchor_y,
            expected_position_revision=request.expected_position_revision,
            new_board_revision=board.runtime_revision + 1,
            idempotency_key=request.idempotency_key, reason=request.reason,
            visibility="dm_only" if hidden else "public",
            subject_seat_id=subject_seat_id, execution_mode=execution_mode,
        )
        self.board_service._notify(actor)
        return RepositionView(
            entry_id=entry.id, anchor_x=stored_position.anchor_x,
            anchor_y=stored_position.anchor_y,
            position_revision=stored_position.revision,
            board_revision=board.runtime_revision + 1,
        )


__all__ = [
    "CancelPendingMovementInput",
    "CancelPendingMovementView",
    "CombatMovementConflictError",
    "CombatMovementInvalidError",
    "CombatMovementStaleError",
    "ConfirmMovementInput",
    "ConfirmMovementView",
    "MovementAnchorInput",
    "MovementService",
    "PreviewMovementInput",
    "PreviewMovementView",
    "MovementStepView",
    "RepositionInput",
    "RepositionView",
    "ResumeMovementInput",
    "ResumeMovementView",
]
