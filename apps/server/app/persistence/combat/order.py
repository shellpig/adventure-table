from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from app.persistence.combat.lifecycle import (
    CombatNotFoundPersistenceError,
    CombatStateConflictPersistenceError,
    StoredCombat,
)
from app.persistence.combat.tables import combat_entries, combats
from app.persistence.rooms.table_runtime import StoredTableActorBinding, TableEventRepository


class CombatOrderRepository:
    """Mid-combat initiative ordering without resetting canonical turn economy."""

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    @staticmethod
    def _combat(row) -> StoredCombat:
        return StoredCombat(
            id=row["id"],
            campaign_id=row["campaign_id"],
            started_session_id=row["started_session_id"],
            ended_session_id=row["ended_session_id"],
            mode=row["mode"],
            status=row["status"],
            round_number=row["round_number"],
            current_turn_entry_id=row["current_turn_entry_id"],
            revision=int(row["revision"]),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            updated_at=row["updated_at"],
        )

    def get(self, combat_id: UUID) -> StoredCombat | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(combats).where(combats.c.id == combat_id)
            ).mappings().one_or_none()
        return self._combat(row) if row is not None else None

    def reorder_running(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        ordered_entry_ids: tuple[UUID, ...],
        idempotency_key: str | None,
    ) -> tuple[StoredCombat, object]:
        def projection(connection, _event_id: UUID, _seq: int) -> None:
            combat = connection.execute(
                select(combats)
                .where(
                    combats.c.id == combat_id,
                    combats.c.campaign_id == binding.campaign_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None:
                raise CombatNotFoundPersistenceError(str(combat_id))
            if combat["status"] != "running" or combat["current_turn_entry_id"] is None:
                raise CombatStateConflictPersistenceError(
                    "initiative can only be reordered while Combat is running"
                )

            rows = connection.execute(
                select(combat_entries)
                .where(
                    combat_entries.c.combat_id == combat_id,
                    combat_entries.c.status == "active",
                )
                .with_for_update()
            ).mappings().all()
            expected = {row["id"] for row in rows}
            if (
                not expected
                or expected != set(ordered_entry_ids)
                or len(expected) != len(ordered_entry_ids)
            ):
                raise CombatStateConflictPersistenceError(
                    "initiative order must contain every active Combat entry exactly once"
                )
            if any(row["initiative_total"] is None for row in rows):
                raise CombatStateConflictPersistenceError(
                    "all active entries require initiative before reordering"
                )
            if combat["current_turn_entry_id"] not in expected:
                raise CombatStateConflictPersistenceError(
                    "current turn entry is not active"
                )

            now = datetime.now().astimezone()
            for index, entry_id in enumerate(ordered_entry_ids):
                connection.execute(
                    update(combat_entries)
                    .where(combat_entries.c.id == entry_id)
                    .values(turn_order=index, updated_at=now)
                )
            connection.execute(
                update(combats)
                .where(combats.c.id == combat_id)
                .values(
                    revision=combats.c.revision + 1,
                    updated_at=now,
                )
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.initiative_reordered",
            acting_seat_id=binding.seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode="self",
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={
                "combat_id": str(combat_id),
                "ordered_entry_ids": [str(value) for value in ordered_entry_ids],
            },
            idempotency_key=(
                f"p4b-initiative-reorder:{idempotency_key}"
                if idempotency_key
                else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get(UUID(str(event.payload["combat_id"])))
        if stored is None:
            raise CombatNotFoundPersistenceError(str(combat_id))
        return stored, event


__all__ = ["CombatOrderRepository"]
