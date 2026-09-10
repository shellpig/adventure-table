from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.persistence.rooms.p3c_runtime import pending_actions
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
)


class PendingActionNotFoundPersistenceError(LookupError):
    pass


class PendingActionConflictPersistenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredPendingAction:
    id: UUID
    session_id: UUID
    acting_seat_id: UUID
    subject_seat_id: UUID
    subject_character_id: UUID | None
    execution_mode: str
    text: str | None
    intent_payload: dict[str, Any] | None
    status: str
    roll_request_id: UUID | None
    window_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime


class PendingActionRepository:
    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    @staticmethod
    def _stored(row) -> StoredPendingAction:
        return StoredPendingAction(
            id=row["id"],
            session_id=row["session_id"],
            acting_seat_id=row["acting_seat_id"],
            subject_seat_id=row["subject_seat_id"],
            subject_character_id=row["subject_character_id"],
            execution_mode=row["execution_mode"],
            text=row["text"],
            intent_payload=dict(row["intent_payload"]) if row["intent_payload"] is not None else None,
            status=row["status"],
            roll_request_id=row["roll_request_id"],
            window_id=row["window_id"],
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get(self, *, session_id: UUID, action_id: UUID) -> StoredPendingAction | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(pending_actions).where(
                    pending_actions.c.id == action_id,
                    pending_actions.c.session_id == session_id,
                )
            ).mappings().one_or_none()
        return self._stored(row) if row is not None else None

    def list_for_session(self, *, session_id: UUID) -> tuple[StoredPendingAction, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(pending_actions)
                .where(pending_actions.c.session_id == session_id)
                .order_by(pending_actions.c.created_at, pending_actions.c.id)
            ).mappings().all()
        return tuple(self._stored(row) for row in rows)

    def create(
        self,
        *,
        binding: StoredTableActorBinding,
        acting_seat_id: UUID,
        subject_seat_id: UUID,
        subject_character_id: UUID | None,
        execution_mode: str,
        text: str | None,
        intent_payload: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> tuple[StoredPendingAction, StoredTableEvent]:
        action_id = uuid4()

        def projection(connection, _event_id: UUID, _seq: int) -> None:
            connection.execute(
                insert(pending_actions).values(
                    id=action_id,
                    session_id=binding.session_id,
                    acting_seat_id=acting_seat_id,
                    subject_seat_id=subject_seat_id,
                    subject_character_id=subject_character_id,
                    execution_mode=execution_mode,
                    text=text,
                    intent_payload=intent_payload,
                    status="pending",
                    version=1,
                )
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="pending_action.created",
            acting_seat_id=acting_seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=subject_character_id,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={
                "pending_action_id": str(action_id),
                "status": "pending",
                "text": text,
                "intent_payload": intent_payload,
            },
            idempotency_key=idempotency_key,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        canonical_id = UUID(str(event.payload["pending_action_id"]))
        stored = self.get(session_id=binding.session_id, action_id=canonical_id)
        if stored is None:
            raise PendingActionNotFoundPersistenceError(str(canonical_id))
        return stored, event

    def transition(
        self,
        *,
        binding: StoredTableActorBinding,
        action_id: UUID,
        expected_version: int,
        from_status: str,
        to_status: str,
        roll_request_id: UUID | None,
        idempotency_key: str | None,
    ) -> tuple[StoredPendingAction, StoredTableEvent]:
        action = self.get(session_id=binding.session_id, action_id=action_id)
        if action is None:
            raise PendingActionNotFoundPersistenceError(str(action_id))

        def projection(connection, _event_id: UUID, _seq: int) -> None:
            current = connection.execute(
                select(pending_actions)
                .where(
                    pending_actions.c.id == action_id,
                    pending_actions.c.session_id == binding.session_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if current is None:
                raise PendingActionNotFoundPersistenceError(str(action_id))
            if int(current["version"]) != expected_version or current["status"] != from_status:
                raise PendingActionConflictPersistenceError(str(action_id))
            connection.execute(
                update(pending_actions)
                .where(pending_actions.c.id == action_id)
                .values(
                    status=to_status,
                    roll_request_id=roll_request_id,
                    version=pending_actions.c.version + 1,
                    updated_at=datetime.now().astimezone(),
                )
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="pending_action.transitioned",
            acting_seat_id=binding.seat_id,
            subject_seat_id=action.subject_seat_id,
            subject_character_id=action.subject_character_id,
            execution_mode=action.execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={
                "pending_action_id": str(action_id),
                "from_status": from_status,
                "to_status": to_status,
                "roll_request_id": str(roll_request_id) if roll_request_id else None,
                "expected_version": expected_version,
            },
            idempotency_key=idempotency_key,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        canonical_id = UUID(str(event.payload["pending_action_id"]))
        stored = self.get(session_id=binding.session_id, action_id=canonical_id)
        if stored is None:
            raise PendingActionNotFoundPersistenceError(str(canonical_id))
        return stored, event


__all__ = [
    "PendingActionConflictPersistenceError",
    "PendingActionNotFoundPersistenceError",
    "PendingActionRepository",
    "StoredPendingAction",
]
