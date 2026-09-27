"""Tactical movement: speed, Preview, and Confirm (P5-B backend only).

Preview is read-only and computed from the caller's visible board state.
Confirm re-validates the full path against Server truth and commits the
position, turn bookkeeping, and ``combat.movement_committed`` in one event
transaction.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.domain.combat.board import (
    CombatBoardService,
    CombatBoardView,
)
from app.domain.combat.lifecycle import (
    CombatNotFoundError,
    CombatService,
    CombatStateConflictError,
)
from app.domain.combat.sizes import resolve_entry_size
from app.domain.combat.speeds import resolve_entry_walk_speed
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import TableActorContext
from app.domain.spatial import (
    BarrierSegment,
    GridCell,
    PathCreature,
    PathStep,
    PathValidationRequest,
    footprint_for_size,
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
)


class CombatMovementInvalidError(RuntimeError):
    """A movement path Server truth rejects (HTTP 400 combat_movement_invalid)."""


class CombatMovementStaleError(RuntimeError):
    """Position or board revision changed under a movement confirm (HTTP 409 combat_movement_stale)."""


class MovementAnchorInput(StrictModel):
    x: int = Field(ge=0, le=200)
    y: int = Field(ge=0, le=200)


class PreviewMovementInput(StrictModel):
    entry_id: UUID
    path: tuple[MovementAnchorInput, ...] = Field(min_length=2)


class ConfirmMovementInput(StrictModel):
    entry_id: UUID
    path: tuple[MovementAnchorInput, ...] = Field(min_length=2)
    expected_position_revision: int = Field(ge=0)
    expected_board_revision: int = Field(ge=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


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
    anchor_x: int
    anchor_y: int
    used_feet: int
    remaining_feet: int
    budget_feet: int
    diagonal_steps_used: int
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
    ) -> None:
        self.board_repository = board_repository
        self.board_service = board_service
        self.combat_service = combat_service

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
        planned_used = used_feet + result.used_feet
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

    def _confirm_view_from_payload(self, entry_id: UUID, payload: dict) -> ConfirmMovementView:
        return ConfirmMovementView(
            entry_id=entry_id, anchor_x=int(payload["anchor_x"]),
            anchor_y=int(payload["anchor_y"]), used_feet=int(payload["used_feet"]),
            remaining_feet=int(payload["budget_feet"]) - int(payload["used_feet"]),
            budget_feet=int(payload["budget_feet"]),
            diagonal_steps_used=int(payload["diagonal_steps_used"]),
            position_revision=int(payload["position_revision"]),
            board_revision=int(payload["board_revision"]),
        )

    def confirm(
        self, actor: TableActorContext, entry_id: UUID, request: ConfirmMovementInput
    ) -> ConfirmMovementView:
        """Validate against Server truth and atomically commit the movement."""
        if request.idempotency_key is not None:
            replay = self.board_repository.find_movement_commit(
                session_id=actor.session_id, idempotency_key=request.idempotency_key
            )
            if replay is not None:
                return self._confirm_view_from_payload(entry_id, replay)

        combat, board, entry = self._running_entry(actor, entry_id)
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, entry)
        if combat.current_turn_entry_id != entry.id:
            raise CombatStateConflictError("Movement is only allowed on the entry's own turn")
        position = self.board_repository.get_position(entry.id)
        if position is None:
            raise CombatStateConflictError(f"CombatEntry {entry_id} has no board position")
        if position.revision != request.expected_position_revision:
            raise CombatMovementStaleError("combat token moved; refresh and replan")
        if board.runtime_revision != request.expected_board_revision:
            raise CombatMovementStaleError("combat board changed; refresh and replan")

        budget_feet, used_feet, diagonal_steps_used = self._turn_budget(entry)
        anchors = tuple(GridCell(anchor.x, anchor.y) for anchor in request.path)
        # Server truth: DM projection sees hidden monsters, walls, and doors.
        # Only the new segment is committed here; it must fit the budget left
        # over from earlier movement this turn.
        truth = self.board_service._project_board(combat, board, is_dm=True)
        result = validate_movement_path(
            self._validation_request(
                view=truth, entry=entry,
                mover_anchor=GridCell(position.anchor_x, position.anchor_y),
                anchors=anchors, budget_feet=max(0, budget_feet - used_feet),
                diagonal_steps_used=diagonal_steps_used,
            )
        )
        if not result.valid:
            # B1: a generic invalid; the response never carries hidden
            # identities or coordinates (hidden blockers fail the same way).
            raise CombatMovementInvalidError("the movement path is not legal")

        new_used = used_feet + result.used_feet
        new_diagonals = diagonal_steps_used + result.diagonal_steps
        final_anchor = result.steps[-1].anchor if result.steps else GridCell(
            position.anchor_x, position.anchor_y
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
            entry_id=entry.id, anchor_x=stored.anchor_x, anchor_y=stored.anchor_y,
            used_feet=new_used, remaining_feet=max(0, budget_feet - new_used),
            budget_feet=budget_feet, diagonal_steps_used=new_diagonals,
            position_revision=stored.revision, board_revision=board.runtime_revision + 1,
        )


__all__ = [
    "CombatMovementInvalidError",
    "CombatMovementStaleError",
    "ConfirmMovementInput",
    "ConfirmMovementView",
    "MovementAnchorInput",
    "MovementService",
    "PreviewMovementInput",
    "PreviewMovementView",
    "MovementStepView",
]
