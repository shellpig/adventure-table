"""Persistence for tactical combat boards (P5-A)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, Engine

from app.persistence.combat_boards.tables import (
    combat_board_doors,
    combat_boards,
    combat_positions,
)
from app.persistence.rooms.table_runtime import session_events

if TYPE_CHECKING:
    from app.persistence.rooms.table_runtime import StoredTableActorBinding, TableEventRepository


@dataclass(frozen=True)
class StoredCombatBoard:
    combat_id: UUID
    source_battle_map_id: UUID | None
    source_battle_map_revision: int | None
    width_cells: int
    height_cells: int
    grid_pixel_size: int | None
    grid_offset_x: int | None
    grid_offset_y: int | None
    image_asset_id: UUID | None
    baseline: dict[str, Any]
    runtime_revision: int
    created_at: datetime


@dataclass(frozen=True)
class StoredBoardDoor:
    combat_id: UUID
    door_id: UUID
    state: str
    revealed: bool
    created_at: datetime


@dataclass(frozen=True)
class StoredCombatPosition:
    combat_entry_id: UUID
    combat_id: UUID
    anchor_x: int
    anchor_y: int
    footprint_width: int
    footprint_height: int
    revision: int
    created_at: datetime


@dataclass(frozen=True)
class MovementDrag:
    """Dragged target to move atomically with the mover.

    The domain service validates the dragged target's path step-by-step
    before the transaction; the repository CAS-checks the target's position
    revision inside the transaction and moves it by the same delta as the
    mover. The dragged target never triggers opportunity attacks.
    """
    target_entry_id: UUID
    expected_position_revision: int
    anchor_x: int
    anchor_y: int


class BoardNotFoundError(Exception):
    pass


class BoardDoorStateConflictError(Exception):
    pass


class BoardMovementStaleError(Exception):
    """Position or board revision changed under a movement confirm (HTTP 409)."""


DOOR_STATES = ("open", "closed", "locked", "broken")


class CombatBoardRepository:
    def __init__(self, engine: Engine, event_repository: TableEventRepository | None = None) -> None:
        self.engine = engine
        self.event_repository = event_repository

    def insert_board_in_transaction(
        self, connection: Connection, stored: StoredCombatBoard
    ) -> StoredCombatBoard:
        connection.execute(insert(combat_boards).values(**stored.__dict__))
        return stored

    def get_board(
        self, combat_id: UUID, *, connection: Connection | None = None
    ) -> StoredCombatBoard | None:
        query = select(combat_boards).where(combat_boards.c.combat_id == combat_id)
        if connection is not None:
            row = connection.execute(query).mappings().one_or_none()
        else:
            with self.engine.connect() as conn:
                row = conn.execute(query).mappings().one_or_none()
        return StoredCombatBoard(**dict(row)) if row is not None else None

    def insert_doors_in_transaction(
        self, connection: Connection, doors: tuple[StoredBoardDoor, ...]
    ) -> tuple[StoredBoardDoor, ...]:
        for door in doors:
            connection.execute(insert(combat_board_doors).values(**door.__dict__))
        return doors

    def list_doors(
        self, combat_id: UUID, *, connection: Connection | None = None
    ) -> tuple[StoredBoardDoor, ...]:
        query = (
            select(combat_board_doors)
            .where(combat_board_doors.c.combat_id == combat_id)
            .order_by(combat_board_doors.c.door_id)
        )
        if connection is not None:
            rows = connection.execute(query).mappings().all()
        else:
            with self.engine.connect() as conn:
                rows = conn.execute(query).mappings().all()
        return tuple(StoredBoardDoor(**dict(row)) for row in rows)

    def update_door_state_in_transaction(
        self,
        connection: Connection,
        combat_id: UUID,
        door_id: UUID,
        *,
        state: str,
        revealed: bool,
        expected_runtime_revision: int,
    ) -> StoredBoardDoor:
        if state not in DOOR_STATES:
            raise BoardDoorStateConflictError(f"unsupported door state: {state}")
        bumped = connection.execute(
            update(combat_boards)
            .where(
                combat_boards.c.combat_id == combat_id,
                combat_boards.c.runtime_revision == expected_runtime_revision,
            )
            .values(runtime_revision=combat_boards.c.runtime_revision + 1)
        ).rowcount
        if bumped != 1:
            raise BoardDoorStateConflictError("combat board changed; retry the door update")
        updated = connection.execute(
            update(combat_board_doors)
            .where(
                combat_board_doors.c.combat_id == combat_id,
                combat_board_doors.c.door_id == door_id,
            )
            .values(state=state, revealed=revealed)
            .returning(*combat_board_doors.c)
        ).mappings().one_or_none()
        if updated is None:
            raise BoardNotFoundError("board door was not found")
        return StoredBoardDoor(**dict(updated))

    def place_position_in_transaction(
        self, connection: Connection, stored: StoredCombatPosition
    ) -> StoredCombatPosition:
        connection.execute(insert(combat_positions).values(**stored.__dict__))
        return stored

    def get_position(
        self, entry_id: UUID, *, connection: Connection | None = None
    ) -> StoredCombatPosition | None:
        query = select(combat_positions).where(
            combat_positions.c.combat_entry_id == entry_id
        )
        if connection is not None:
            row = connection.execute(query).mappings().one_or_none()
        else:
            with self.engine.connect() as conn:
                row = conn.execute(query).mappings().one_or_none()
        return StoredCombatPosition(**dict(row)) if row is not None else None

    def list_positions(
        self, combat_id: UUID, *, connection: Connection | None = None
    ) -> tuple[StoredCombatPosition, ...]:
        query = (
            select(combat_positions)
            .where(combat_positions.c.combat_id == combat_id)
            .order_by(combat_positions.c.created_at, combat_positions.c.combat_entry_id)
        )
        if connection is not None:
            rows = connection.execute(query).mappings().all()
        else:
            with self.engine.connect() as conn:
                rows = conn.execute(query).mappings().all()
        return tuple(StoredCombatPosition(**dict(row)) for row in rows)

    def delete_position_in_transaction(
        self, connection: Connection, entry_id: UUID
    ) -> bool:
        return (
            connection.execute(
                delete(combat_positions).where(
                    combat_positions.c.combat_entry_id == entry_id
                )
            ).rowcount
            > 0
        )

    def upsert_position_with_event(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        entry_id: UUID,
        anchor_x: int,
        anchor_y: int,
        footprint_width: int,
        footprint_height: int,
        idempotency_key: str | None,
        visibility: str,
    ) -> StoredCombatPosition:
        """Idempotently place (or re-place) a token and emit combat.position_placed."""
        if self.event_repository is None:
            raise BoardNotFoundError("CombatBoardRepository has no event repository")
        now = datetime.now().astimezone()

        def projection(connection: Connection, _event_id: UUID, _seq: int) -> None:
            existing = (
                connection.execute(
                    select(combat_positions)
                    .where(combat_positions.c.combat_entry_id == entry_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if existing is None:
                connection.execute(
                    insert(combat_positions).values(
                        combat_entry_id=entry_id, combat_id=combat_id,
                        anchor_x=anchor_x, anchor_y=anchor_y,
                        footprint_width=footprint_width, footprint_height=footprint_height,
                        revision=1, created_at=now,
                    )
                )
            else:
                connection.execute(
                    update(combat_positions)
                    .where(combat_positions.c.combat_entry_id == entry_id)
                    .values(
                        anchor_x=anchor_x, anchor_y=anchor_y,
                        footprint_width=footprint_width, footprint_height=footprint_height,
                        revision=combat_positions.c.revision + 1,
                    )
                )

        self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.position_placed", acting_seat_id=binding.seat_id, subject_seat_id=None,
            subject_character_id=None, execution_mode="self", visibility=visibility,
            recipient_seat_ids=(), payload_version=1,
            payload={"combat_id": str(combat_id), "entry_id": str(entry_id)},
            idempotency_key=f"p5a-position-place:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        stored = self.get_position(entry_id)
        if stored is None:
            raise BoardNotFoundError(str(entry_id))
        return stored

    def update_door_state_with_event(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        door_id: UUID,
        state: str,
        revealed: bool,
        expected_runtime_revision: int,
        idempotency_key: str | None,
        visibility: str,
        hidden_origin: bool = False,
    ) -> StoredBoardDoor:
        """Apply a runtime door change (Map Definition untouched) and emit combat.door_state_changed."""
        if self.event_repository is None:
            raise BoardNotFoundError("CombatBoardRepository has no event repository")

        def projection(connection: Connection, _event_id: UUID, _seq: int) -> None:
            self.update_door_state_in_transaction(
                connection, combat_id, door_id, state=state, revealed=revealed,
                expected_runtime_revision=expected_runtime_revision,
            )

        self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.door_state_changed", acting_seat_id=binding.seat_id, subject_seat_id=None,
            subject_character_id=None, execution_mode="self", visibility=visibility,
            recipient_seat_ids=(), payload_version=1,
            payload={
                "combat_id": str(combat_id), "door_id": str(door_id), "state": state,
                # Lets the event projector withhold the id from Players for
                # hidden-origin doors (their board view shows door_id=None).
                "hidden_door": hidden_origin,
            },
            idempotency_key=f"p5a-door-state:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        for door in self.list_doors(combat_id):
            if door.door_id == door_id:
                return door
        raise BoardNotFoundError(str(door_id))

    def commit_movement_with_event(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        entry_id: UUID,
        anchor_x: int,
        anchor_y: int,
        expected_position_revision: int,
        expected_board_revision: int,
        movement_used_feet: int,
        movement_diagonal_steps_used: int,
        movement_budget_feet: int,
        idempotency_key: str | None,
        visibility: str,
        subject_seat_id: UUID | None,
        execution_mode: str,
        drag: MovementDrag | None = None,
    ) -> StoredCombatPosition:
        """Atomically move a token, write turn bookkeeping, emit combat.movement_committed.

        The position/board revisions are re-checked inside the event
        transaction (compare-and-set): a concurrent writer fails here even if
        the domain-level check passed a moment earlier.
        """
        if self.event_repository is None:
            raise BoardNotFoundError("CombatBoardRepository has no event repository")
        # Imported here: app.persistence.combat.lifecycle imports this module
        # at top level, so a top-level combat.tables import would be circular.
        from app.persistence.combat.tables import combat_entries

        now = datetime.now().astimezone()

        def projection(connection: Connection, _event_id: UUID, _seq: int) -> None:
            position = (
                connection.execute(
                    select(combat_positions)
                    .where(combat_positions.c.combat_entry_id == entry_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if position is None:
                raise BoardNotFoundError(f"Combat entry {entry_id} has no board position")
            if int(position["revision"]) != expected_position_revision:
                raise BoardMovementStaleError("combat token moved; refresh and replan")
            bumped_board = connection.execute(
                update(combat_boards)
                .where(
                    combat_boards.c.combat_id == combat_id,
                    combat_boards.c.runtime_revision == expected_board_revision,
                )
                .values(runtime_revision=combat_boards.c.runtime_revision + 1)
            ).rowcount
            if bumped_board != 1:
                raise BoardMovementStaleError("combat board changed; refresh and replan")
            connection.execute(
                update(combat_positions)
                .where(combat_positions.c.combat_entry_id == entry_id)
                .values(
                    anchor_x=anchor_x, anchor_y=anchor_y,
                    revision=combat_positions.c.revision + 1,
                )
            )
            # P5-E E1b: move the dragged target in the same transaction.
            # The domain service validated the target's path step-by-step;
            # here we CAS its position revision and apply the move.
            if drag is not None:
                drag_position = (
                    connection.execute(
                        select(combat_positions)
                        .where(combat_positions.c.combat_entry_id == drag.target_entry_id)
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if drag_position is None:
                    raise BoardNotFoundError(
                        f"Drag target {drag.target_entry_id} has no board position"
                    )
                if int(drag_position["revision"]) != drag.expected_position_revision:
                    raise BoardMovementStaleError("drag target moved; refresh and replan")
                connection.execute(
                    update(combat_positions)
                    .where(combat_positions.c.combat_entry_id == drag.target_entry_id)
                    .values(
                        anchor_x=drag.anchor_x, anchor_y=drag.anchor_y,
                        revision=combat_positions.c.revision + 1,
                    )
                )
            from app.persistence.combat.tables import combat_entries
            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(
                    movement_used_feet=movement_used_feet,
                    movement_diagonal_steps_used=movement_diagonal_steps_used,
                    movement_budget_feet=movement_budget_feet,
                    updated_at=now,
                )
            )

        self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.movement_committed", acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id, subject_character_id=None,
            execution_mode=execution_mode, visibility=visibility,
            recipient_seat_ids=(), payload_version=1,
            payload={
                "combat_id": str(combat_id), "entry_id": str(entry_id),
                "anchor_x": anchor_x, "anchor_y": anchor_y,
                "used_feet": movement_used_feet,
                "diagonal_steps_used": movement_diagonal_steps_used,
                "budget_feet": movement_budget_feet,
                "position_revision": expected_position_revision + 1,
                "board_revision": expected_board_revision + 1,
            },
            idempotency_key=f"p5b-movement-commit:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        stored = self.get_position(entry_id)
        if stored is None:
            raise BoardNotFoundError(str(entry_id))
        return stored

    def _find_idempotent_outcome(
        self, *, session_id: UUID, kind: str, key_prefix: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Stored outcome (kind, payload, acting seat) of an idempotent board write."""
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(session_events.c.payload, session_events.c.acting_seat_id)
                    .where(
                        session_events.c.session_id == session_id,
                        session_events.c.kind == kind,
                        session_events.c.idempotency_key == f"{key_prefix}:{idempotency_key}",
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return {
            "kind": kind,
            "payload": dict(row["payload"]),
            "acting_seat_id": row["acting_seat_id"],
        }

    def find_movement_outcome(
        self, *, session_id: UUID, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Return the committed or interrupted movement stored for a retry key.

        A retry of the same key replays the original outcome (committed or
        interrupted) instead of appending a duplicate event.
        """
        outcome = self._find_idempotent_outcome(
            session_id=session_id, kind="combat.movement_committed",
            key_prefix="p5b-movement-commit", idempotency_key=idempotency_key,
        )
        if outcome is not None:
            return outcome
        return self._find_idempotent_outcome(
            session_id=session_id, kind="combat.movement_interrupted",
            key_prefix="p5b-movement-interrupted", idempotency_key=idempotency_key,
        )

    def append_movement_interrupted_with_event(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        entry_id: UUID,
        reason: str,
        step_index: int,
        blocker_type: str,
        blocker_id: str | None,
        expected_position_revision: int,
        expected_board_revision: int,
        anchor_x: int,
        anchor_y: int,
        used_feet: int,
        budget_feet: int,
        diagonal_steps_used: int,
        position_revision: int,
        board_revision: int,
        idempotency_key: str | None,
        visibility: str,
        subject_seat_id: UUID | None,
        execution_mode: str,
    ) -> None:
        """Append combat.movement_interrupted for a path blocked by hidden objects.

        Nothing moves and no bookkeeping changes; the event itself is the
        durable outcome. The position/board revisions are re-checked inside
        the event transaction (compare-and-set): a concurrent writer fails
        here even if the domain-level check passed a moment earlier.

        The confirm snapshot (anchor/feet/revisions as of the interruption)
        is stored in the payload so a retry replays the identical outcome
        even if the token or the board changed afterwards.
        """
        if self.event_repository is None:
            raise BoardNotFoundError("CombatBoardRepository has no event repository")

        def projection(connection: Connection, _event_id: UUID, _seq: int) -> None:
            position = (
                connection.execute(
                    select(combat_positions)
                    .where(combat_positions.c.combat_entry_id == entry_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if position is None:
                raise BoardNotFoundError(f"Combat entry {entry_id} has no board position")
            if int(position["revision"]) != expected_position_revision:
                raise BoardMovementStaleError("combat token moved; refresh and replan")
            current_board_revision = connection.execute(
                select(combat_boards.c.runtime_revision).where(
                    combat_boards.c.combat_id == combat_id
                )
            ).scalar_one_or_none()
            if current_board_revision != expected_board_revision:
                raise BoardMovementStaleError("combat board changed; refresh and replan")
            # No mutation: an interruption moves nothing and touches no
            # bookkeeping; the revision check above only guards the race.

        self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.movement_interrupted", acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id, subject_character_id=None,
            execution_mode=execution_mode, visibility=visibility,
            recipient_seat_ids=(), payload_version=1,
            payload={
                "combat_id": str(combat_id), "entry_id": str(entry_id),
                "reason": reason, "step_index": step_index,
                "blocker_type": blocker_type, "blocker_id": blocker_id,
                "anchor_x": anchor_x, "anchor_y": anchor_y,
                "used_feet": used_feet, "budget_feet": budget_feet,
                "diagonal_steps_used": diagonal_steps_used,
                "position_revision": position_revision,
                "board_revision": board_revision,
            },
            idempotency_key=(
                f"p5b-movement-interrupted:{idempotency_key}" if idempotency_key else None
            ),
            expected_actor_binding=binding, transaction_projection=projection,
        )

    def reposition_with_event(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        entry_id: UUID,
        anchor_x: int,
        anchor_y: int,
        expected_position_revision: int,
        new_board_revision: int,
        idempotency_key: str | None,
        reason: str,
        visibility: str,
        subject_seat_id: UUID | None,
        execution_mode: str,
    ) -> StoredCombatPosition:
        """DM correction: move a token without touching movement bookkeeping.

        The position revision is compare-and-set inside the event transaction;
        the board runtime revision is bumped unconditionally (reposition takes
        no expected board revision; new_board_revision is the post-bump value
        for the payload). Emits combat.position_corrected.
        """
        if self.event_repository is None:
            raise BoardNotFoundError("CombatBoardRepository has no event repository")

        def projection(connection: Connection, _event_id: UUID, _seq: int) -> None:
            position = (
                connection.execute(
                    select(combat_positions)
                    .where(combat_positions.c.combat_entry_id == entry_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if position is None:
                raise BoardNotFoundError(f"Combat entry {entry_id} has no board position")
            if int(position["revision"]) != expected_position_revision:
                raise BoardMovementStaleError("combat token moved; refresh and replan")
            connection.execute(
                update(combat_boards)
                .where(combat_boards.c.combat_id == combat_id)
                .values(runtime_revision=combat_boards.c.runtime_revision + 1)
            )
            connection.execute(
                update(combat_positions)
                .where(combat_positions.c.combat_entry_id == entry_id)
                .values(
                    anchor_x=anchor_x, anchor_y=anchor_y,
                    revision=combat_positions.c.revision + 1,
                )
            )

        self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.position_corrected", acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id, subject_character_id=None,
            execution_mode=execution_mode, visibility=visibility,
            recipient_seat_ids=(), payload_version=1,
            payload={
                "combat_id": str(combat_id), "entry_id": str(entry_id),
                "anchor_x": anchor_x, "anchor_y": anchor_y,
                "reason": reason,
                "position_revision": expected_position_revision + 1,
                "board_revision": new_board_revision,
            },
            idempotency_key=f"p5b-reposition:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        stored = self.get_position(entry_id)
        if stored is None:
            raise BoardNotFoundError(str(entry_id))
        return stored

    def find_reposition_outcome(
        self, *, session_id: UUID, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Return the combat.position_corrected stored for a retry key."""
        return self._find_idempotent_outcome(
            session_id=session_id, kind="combat.position_corrected",
            key_prefix="p5b-reposition", idempotency_key=idempotency_key,
        )

    def find_paused_movement_outcome(
        self, *, session_id: UUID, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Return the combat.movement_paused payload stored for a retry key."""
        return self._find_idempotent_outcome(
            session_id=session_id, kind="combat.movement_paused",
            key_prefix="p5e-movement-paused", idempotency_key=idempotency_key,
        )

    def note_hidden_opportunity_crossings(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        entry_id: UUID,
        crossings: tuple[dict[str, Any], ...],
        subject_seat_id: UUID | None,
        execution_mode: str,
    ) -> None:
        """Append a DM-only note that hidden reactors' reach was crossed.

        Informational only: the movement itself already committed or paused.
        ``crossings`` is a tuple of {"step_index": int, "reactor_entry_ids":
        [str]} for boundaries whose reactors are all hidden.
        """
        if self.event_repository is None or not crossings:
            return
        self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.opportunity_crossing_noted", acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id, subject_character_id=None,
            execution_mode=execution_mode, visibility="dm_only",
            recipient_seat_ids=(), payload_version=1,
            payload={
                "combat_id": str(combat_id), "entry_id": str(entry_id),
                "crossings": [
                    {
                        "step_index": int(item["step_index"]),
                        "reactor_entry_ids": [str(rid) for rid in item["reactor_entry_ids"]],
                    }
                    for item in crossings
                ],
            },
            idempotency_key=None,
            expected_actor_binding=binding,
        )

    def find_resumed_movement_outcome(
        self, *, session_id: UUID, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Return the combat.movement_resumed payload stored for a retry key."""
        return self._find_idempotent_outcome(
            session_id=session_id, kind="combat.movement_resumed",
            key_prefix="p5e-movement-resumed", idempotency_key=idempotency_key,
        )

    def find_cancelled_movement_outcome(
        self, *, session_id: UUID, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Return the combat.movement_cancelled payload stored for a retry key."""
        return self._find_idempotent_outcome(
            session_id=session_id, kind="combat.movement_cancelled",
            key_prefix="p5e-movement-cancelled", idempotency_key=idempotency_key,
        )

    def resume_movement(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        entry_id: UUID,
        outcome: str,
        anchor_x: int,
        anchor_y: int,
        expected_position_revision: int,
        expected_board_revision: int,
        expected_pending_revision: int,
        movement_used_feet: int,
        movement_diagonal_steps_used: int,
        movement_budget_feet: int,
        pending_movement_state: dict[str, Any],
        windows: tuple[Any, ...],
        idempotency_key: str | None,
        visibility: str,
        subject_seat_id: UUID | None,
        execution_mode: str,
        drag: MovementDrag | None = None,
    ) -> StoredCombatPosition:
        """Resume a paused movement: commit the rest, re-pause, or stop.

        Atomically (single event transaction): CAS the position, board, and
        pending revisions; move the token (unless stopped); write movement
        bookkeeping and the new pending state ({} clears it); write new OA
        windows for a re-pause. Appends ``combat.movement_resumed`` with the
        outcome. ``outcome`` is "resumed", "paused", or "stopped".
        """
        if self.event_repository is None:
            raise BoardNotFoundError("CombatBoardRepository has no event repository")
        from app.persistence.combat.reactions import write_reaction_window

        now = datetime.now().astimezone()

        def projection(connection: Connection, _event_id: UUID, _seq: int) -> None:
            from app.persistence.combat.tables import combat_entries
            entry_row = (
                connection.execute(
                    select(combat_entries)
                    .where(combat_entries.c.id == entry_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if entry_row is None:
                raise BoardNotFoundError(f"Combat entry {entry_id} was not found")
            pending = dict(entry_row["pending_movement_state"] or {})
            if not pending:
                raise BoardMovementStaleError("no pending movement to resume")
            if int(pending.get("revision", -1)) != expected_pending_revision:
                raise BoardMovementStaleError("pending movement changed; refresh")
            position = (
                connection.execute(
                    select(combat_positions)
                    .where(combat_positions.c.combat_entry_id == entry_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if position is None:
                raise BoardNotFoundError(f"Combat entry {entry_id} has no board position")
            if int(position["revision"]) != expected_position_revision:
                raise BoardMovementStaleError("combat token moved; refresh and replan")
            bumped_board = connection.execute(
                update(combat_boards)
                .where(
                    combat_boards.c.combat_id == combat_id,
                    combat_boards.c.runtime_revision == expected_board_revision,
                )
                .values(runtime_revision=combat_boards.c.runtime_revision + 1)
            ).rowcount
            if bumped_board != 1:
                raise BoardMovementStaleError("combat board changed; refresh and replan")
            if outcome != "stopped":
                connection.execute(
                    update(combat_positions)
                    .where(combat_positions.c.combat_entry_id == entry_id)
                    .values(
                        anchor_x=anchor_x, anchor_y=anchor_y,
                        revision=combat_positions.c.revision + 1,
                    )
                )
                # P5-E E1b: move the dragged target in the same transaction.
                if drag is not None:
                    drag_position = (
                        connection.execute(
                            select(combat_positions)
                            .where(combat_positions.c.combat_entry_id == drag.target_entry_id)
                            .with_for_update()
                        )
                        .mappings()
                        .one_or_none()
                    )
                    if drag_position is None:
                        raise BoardNotFoundError(
                            f"Drag target {drag.target_entry_id} has no board position"
                        )
                    if int(drag_position["revision"]) != drag.expected_position_revision:
                        raise BoardMovementStaleError("drag target moved; refresh and replan")
                    connection.execute(
                        update(combat_positions)
                        .where(combat_positions.c.combat_entry_id == drag.target_entry_id)
                        .values(
                            anchor_x=drag.anchor_x, anchor_y=drag.anchor_y,
                            revision=combat_positions.c.revision + 1,
                        )
                    )
            from app.persistence.combat.tables import combat_entries
            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(
                    movement_used_feet=movement_used_feet,
                    movement_diagonal_steps_used=movement_diagonal_steps_used,
                    movement_budget_feet=movement_budget_feet,
                    pending_movement_state=pending_movement_state,
                    updated_at=now,
                )
            )
            for window in windows:
                write_reaction_window(
                    connection,
                    binding=binding,
                    combat_id=combat_id,
                    entry_id=UUID(window.entry_id),
                    window=window,
                )

        self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.movement_resumed", acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id, subject_character_id=None,
            execution_mode=execution_mode, visibility=visibility,
            recipient_seat_ids=(), payload_version=1,
            payload={
                "combat_id": str(combat_id), "entry_id": str(entry_id),
                "outcome": outcome,
                "anchor_x": anchor_x, "anchor_y": anchor_y,
                "used_feet": movement_used_feet,
                "diagonal_steps_used": movement_diagonal_steps_used,
                "budget_feet": movement_budget_feet,
                "position_revision": expected_position_revision + (0 if outcome == "stopped" else 1),
                "board_revision": expected_board_revision + 1,
                "pending_revision": int(pending_movement_state.get("revision", 0)) if pending_movement_state else None,
                "pending_window_ids": list(pending_movement_state.get("pending_window_ids", [])) if pending_movement_state else [],
            },
            idempotency_key=f"p5e-movement-resumed:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        stored = self.get_position(entry_id)
        if stored is None:
            raise BoardNotFoundError(str(entry_id))
        return stored

    def cancel_pending_movement(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        entry_id: UUID,
        reason: str,
        idempotency_key: str | None,
        visibility: str,
        subject_seat_id: UUID | None,
        execution_mode: str,
    ) -> StoredCombatPosition:
        """DM-only: drop a paused movement. The mover stays where it paused.

        Atomically clears ``pending_movement_state`` and appends
        ``combat.movement_cancelled`` with the reason for audit. The token
        does not move and bookkeeping is unchanged.
        """
        if self.event_repository is None:
            raise BoardNotFoundError("CombatBoardRepository has no event repository")

        now = datetime.now().astimezone()

        def projection(connection: Connection, _event_id: UUID, _seq: int) -> None:
            from app.persistence.combat.tables import combat_entries
            entry_row = (
                connection.execute(
                    select(combat_entries)
                    .where(combat_entries.c.id == entry_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if entry_row is None:
                raise BoardNotFoundError(f"Combat entry {entry_id} was not found")
            if not dict(entry_row["pending_movement_state"] or {}):
                raise BoardMovementStaleError("no pending movement to cancel")
            from app.persistence.combat.tables import combat_entries
            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(pending_movement_state={}, updated_at=now)
            )
            connection.execute(
                update(combat_boards)
                .where(combat_boards.c.combat_id == combat_id)
                .values(runtime_revision=combat_boards.c.runtime_revision + 1)
            )

        self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.movement_cancelled", acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id, subject_character_id=None,
            execution_mode=execution_mode, visibility=visibility,
            recipient_seat_ids=(), payload_version=1,
            payload={
                "combat_id": str(combat_id), "entry_id": str(entry_id),
                "reason": reason,
            },
            idempotency_key=f"p5e-movement-cancelled:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        stored = self.get_position(entry_id)
        if stored is None:
            raise BoardNotFoundError(str(entry_id))
        return stored

    def pause_movement_with_windows(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        entry_id: UUID,
        anchor_x: int,
        anchor_y: int,
        expected_position_revision: int,
        expected_board_revision: int,
        movement_used_feet: int,
        movement_diagonal_steps_used: int,
        movement_budget_feet: int,
        pending_movement_state: dict[str, Any],
        windows: tuple[Any, ...],
        idempotency_key: str | None,
        visibility: str,
        subject_seat_id: UUID | None,
        execution_mode: str,
        drag: MovementDrag | None = None,
    ) -> StoredCombatPosition:
        """Pause a mover at an opportunity-attack boundary and open windows.

        Atomically (single event transaction): CAS the position and board
        revisions, commit the mover to the pause anchor, write its movement
        bookkeeping plus durable ``pending_movement_state``, and write one
        open OA reaction window per reactor via ``write_reaction_window``.
        Appends ``combat.movement_paused``. ``windows`` are prebuilt
        ``ReactionWindow`` objects for the eligible reactors.
        """
        if self.event_repository is None:
            raise BoardNotFoundError("CombatBoardRepository has no event repository")
        from app.persistence.combat.reactions import write_reaction_window

        now = datetime.now().astimezone()

        def projection(connection: Connection, _event_id: UUID, _seq: int) -> None:
            position = (
                connection.execute(
                    select(combat_positions)
                    .where(combat_positions.c.combat_entry_id == entry_id)
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if position is None:
                raise BoardNotFoundError(f"Combat entry {entry_id} has no board position")
            if int(position["revision"]) != expected_position_revision:
                raise BoardMovementStaleError("combat token moved; refresh and replan")
            bumped_board = connection.execute(
                update(combat_boards)
                .where(
                    combat_boards.c.combat_id == combat_id,
                    combat_boards.c.runtime_revision == expected_board_revision,
                )
                .values(runtime_revision=combat_boards.c.runtime_revision + 1)
            ).rowcount
            if bumped_board != 1:
                raise BoardMovementStaleError("combat board changed; refresh and replan")
            connection.execute(
                update(combat_positions)
                .where(combat_positions.c.combat_entry_id == entry_id)
                .values(
                    anchor_x=anchor_x, anchor_y=anchor_y,
                    revision=combat_positions.c.revision + 1,
                )
            )
            # P5-E E1b: move the dragged target in the same transaction.
            if drag is not None:
                drag_position = (
                    connection.execute(
                        select(combat_positions)
                        .where(combat_positions.c.combat_entry_id == drag.target_entry_id)
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if drag_position is None:
                    raise BoardNotFoundError(
                        f"Drag target {drag.target_entry_id} has no board position"
                    )
                if int(drag_position["revision"]) != drag.expected_position_revision:
                    raise BoardMovementStaleError("drag target moved; refresh and replan")
                connection.execute(
                    update(combat_positions)
                    .where(combat_positions.c.combat_entry_id == drag.target_entry_id)
                    .values(
                        anchor_x=drag.anchor_x, anchor_y=drag.anchor_y,
                        revision=combat_positions.c.revision + 1,
                    )
                )
            from app.persistence.combat.tables import combat_entries
            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry_id)
                .values(
                    movement_used_feet=movement_used_feet,
                    movement_diagonal_steps_used=movement_diagonal_steps_used,
                    movement_budget_feet=movement_budget_feet,
                    pending_movement_state=pending_movement_state,
                    updated_at=now,
                )
            )
            for window in windows:
                write_reaction_window(
                    connection,
                    binding=binding,
                    combat_id=combat_id,
                    entry_id=UUID(window.entry_id),
                    window=window,
                )

        self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="combat.movement_paused", acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id, subject_character_id=None,
            execution_mode=execution_mode, visibility=visibility,
            recipient_seat_ids=(), payload_version=1,
            payload={
                "combat_id": str(combat_id), "entry_id": str(entry_id),
                "anchor_x": anchor_x, "anchor_y": anchor_y,
                "used_feet": movement_used_feet,
                "diagonal_steps_used": movement_diagonal_steps_used,
                "budget_feet": movement_budget_feet,
                "position_revision": expected_position_revision + 1,
                "board_revision": expected_board_revision + 1,
                "pending_revision": int(pending_movement_state["revision"]),
                "pending_window_ids": list(pending_movement_state["pending_window_ids"]),
                "boundary_reactor_ids": list(pending_movement_state["boundary_reactor_ids"]),
            },
            idempotency_key=f"p5e-movement-paused:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        stored = self.get_position(entry_id)
        if stored is None:
            raise BoardNotFoundError(str(entry_id))
        return stored


__all__ = [
    "BoardDoorStateConflictError",
    "BoardMovementStaleError",
    "BoardNotFoundError",
    "CombatBoardRepository",
    "DOOR_STATES",
    "MovementDrag",
    "StoredBoardDoor",
    "StoredCombatBoard",
    "StoredCombatPosition",
]
