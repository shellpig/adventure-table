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


class BoardNotFoundError(Exception):
    pass


class BoardDoorStateConflictError(Exception):
    pass


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


__all__ = [
    "BoardDoorStateConflictError",
    "BoardNotFoundError",
    "CombatBoardRepository",
    "DOOR_STATES",
    "StoredBoardDoor",
    "StoredCombatBoard",
    "StoredCombatPosition",
]
