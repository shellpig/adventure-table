from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.persistence.rooms.p3c_runtime import roll_groups, roll_requests, roll_results
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
)


class RollRequestNotFoundPersistenceError(LookupError):
    pass


class RollRequestNotPendingPersistenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredRollRequest:
    id: UUID
    session_id: UUID
    roll_group_id: UUID | None
    target_seat_id: UUID
    target_character_id: UUID | None
    request_type: str
    ability_ref: str | None
    skill_ref: str | None
    dc: int | None
    modifier_mode: str
    flat_adjustment: int
    visibility: str
    status: str
    requested_by_seat_id: UUID
    created_at: datetime
    resolved_at: datetime | None
    version: int


@dataclass(frozen=True)
class StoredRollResult:
    id: UUID
    roll_request_id: UUID | None
    session_id: UUID
    acting_seat_id: UUID
    subject_seat_id: UUID
    subject_character_id: UUID | None
    execution_mode: str
    source: str
    formula: str
    raw_dice: tuple[int, ...]
    kept_dice: tuple[int, ...]
    base_modifier: int
    flat_adjustment: int
    total: int
    visibility: str
    created_at: datetime


@dataclass(frozen=True)
class NewRollRequest:
    id: UUID
    target_seat_id: UUID
    target_character_id: UUID | None


class RollRepository:
    """P3-C canonical roll persistence built on the P3-A event transaction."""

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    @staticmethod
    def _request(row) -> StoredRollRequest:
        return StoredRollRequest(
            id=row["id"],
            session_id=row["session_id"],
            roll_group_id=row["roll_group_id"],
            target_seat_id=row["target_seat_id"],
            target_character_id=row["target_character_id"],
            request_type=row["request_type"],
            ability_ref=row["ability_ref"],
            skill_ref=row["skill_ref"],
            dc=row["dc"],
            modifier_mode=row["modifier_mode"],
            flat_adjustment=int(row["flat_adjustment"]),
            visibility=row["visibility"],
            status=row["status"],
            requested_by_seat_id=row["requested_by_seat_id"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            version=int(row["version"]),
        )

    @staticmethod
    def _result(row) -> StoredRollResult:
        return StoredRollResult(
            id=row["id"],
            roll_request_id=row["roll_request_id"],
            session_id=row["session_id"],
            acting_seat_id=row["acting_seat_id"],
            subject_seat_id=row["subject_seat_id"],
            subject_character_id=row["subject_character_id"],
            execution_mode=row["execution_mode"],
            source=row["source"],
            formula=row["formula"],
            raw_dice=tuple(int(value) for value in row["raw_dice"]),
            kept_dice=tuple(int(value) for value in row["kept_dice"]),
            base_modifier=int(row["base_modifier"]),
            flat_adjustment=int(row["flat_adjustment"]),
            total=int(row["total"]),
            visibility=row["visibility"],
            created_at=row["created_at"],
        )

    def get_request(self, *, session_id: UUID, request_id: UUID) -> StoredRollRequest | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(roll_requests).where(
                    roll_requests.c.id == request_id,
                    roll_requests.c.session_id == session_id,
                )
            ).mappings().one_or_none()
        return self._request(row) if row is not None else None

    def get_result_for_request(
        self, *, session_id: UUID, request_id: UUID
    ) -> StoredRollResult | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(roll_results).where(
                    roll_results.c.session_id == session_id,
                    roll_results.c.roll_request_id == request_id,
                )
            ).mappings().one_or_none()
        return self._result(row) if row is not None else None

    def list_requests(self, *, session_id: UUID) -> tuple[StoredRollRequest, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(roll_requests)
                .where(roll_requests.c.session_id == session_id)
                .order_by(roll_requests.c.created_at, roll_requests.c.id)
            ).mappings().all()
        return tuple(self._request(row) for row in rows)

    def create_request_group(
        self,
        *,
        binding: StoredTableActorBinding,
        requests: tuple[NewRollRequest, ...],
        request_type: str,
        ability_ref: str | None,
        skill_ref: str | None,
        dc: int | None,
        modifier_mode: str,
        flat_adjustment: int,
        visibility: str,
        label: str | None,
        event_visibility: str,
        idempotency_key: str | None,
    ) -> tuple[UUID, tuple[StoredRollRequest, ...], StoredTableEvent]:
        group_id = uuid4()

        def projection(connection, _event_id: UUID, _seq: int) -> None:
            connection.execute(
                insert(roll_groups).values(
                    id=group_id,
                    session_id=binding.session_id,
                    requested_by_seat_id=binding.seat_id,
                    label=label,
                    visibility=visibility,
                    version=1,
                )
            )
            for request in requests:
                connection.execute(
                    insert(roll_requests).values(
                        id=request.id,
                        session_id=binding.session_id,
                        roll_group_id=group_id,
                        target_seat_id=request.target_seat_id,
                        target_character_id=request.target_character_id,
                        request_type=request_type,
                        ability_ref=ability_ref,
                        skill_ref=skill_ref,
                        dc=dc,
                        modifier_mode=modifier_mode,
                        flat_adjustment=flat_adjustment,
                        visibility=visibility,
                        status="pending",
                        requested_by_seat_id=binding.seat_id,
                        version=1,
                    )
                )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="roll.requested",
            acting_seat_id=binding.seat_id,
            subject_seat_id=requests[0].target_seat_id if len(requests) == 1 else None,
            subject_character_id=requests[0].target_character_id if len(requests) == 1 else None,
            execution_mode="self",
            visibility=event_visibility,
            recipient_seat_ids=tuple(request.target_seat_id for request in requests),
            payload_version=1,
            payload={
                "roll_group_id": str(group_id),
                "roll_request_ids": [str(request.id) for request in requests],
                "request_type": request_type,
                "ability_ref": ability_ref,
                "skill_ref": skill_ref,
                "modifier_mode": modifier_mode,
                "flat_adjustment": flat_adjustment,
                "visibility": visibility,
                # DC is intentionally omitted: it is a secret-bearing field and
                # is projected from roll_requests only for the current DM.
            },
            idempotency_key=idempotency_key,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )

        # An idempotent replay returns the original event without invoking the
        # projection. Resolve its canonical ids from the event payload.
        canonical_group_id = UUID(str(event.payload["roll_group_id"]))
        request_ids = tuple(UUID(str(value)) for value in event.payload["roll_request_ids"])
        stored = tuple(
            request
            for request_id in request_ids
            if (request := self.get_request(session_id=binding.session_id, request_id=request_id))
            is not None
        )
        return canonical_group_id, stored, event

    def complete_request(
        self,
        *,
        binding: StoredTableActorBinding,
        request_id: UUID,
        acting_seat_id: UUID,
        execution_mode: str,
        source: str,
        formula: str,
        raw_dice: tuple[int, ...],
        kept_dice: tuple[int, ...],
        base_modifier: int,
        flat_adjustment: int,
        total: int,
        visibility: str,
        event_visibility: str,
        idempotency_key: str | None,
    ) -> tuple[StoredRollResult, StoredTableEvent]:
        result_id = uuid4()

        def projection(connection, _event_id: UUID, _seq: int) -> None:
            request = connection.execute(
                select(roll_requests)
                .where(
                    roll_requests.c.id == request_id,
                    roll_requests.c.session_id == binding.session_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if request is None:
                raise RollRequestNotFoundPersistenceError(str(request_id))
            if request["status"] != "pending":
                raise RollRequestNotPendingPersistenceError(str(request_id))
            connection.execute(
                insert(roll_results).values(
                    id=result_id,
                    roll_request_id=request_id,
                    session_id=binding.session_id,
                    acting_seat_id=acting_seat_id,
                    subject_seat_id=request["target_seat_id"],
                    subject_character_id=request["target_character_id"],
                    execution_mode=execution_mode,
                    source=source,
                    formula=formula,
                    raw_dice=list(raw_dice),
                    kept_dice=list(kept_dice),
                    base_modifier=base_modifier,
                    flat_adjustment=flat_adjustment,
                    total=total,
                    visibility=visibility,
                )
            )
            connection.execute(
                update(roll_requests)
                .where(roll_requests.c.id == request_id)
                .values(status="resolved", resolved_at=datetime.now().astimezone(), version=roll_requests.c.version + 1)
            )

        request = self.get_request(session_id=binding.session_id, request_id=request_id)
        if request is None:
            raise RollRequestNotFoundPersistenceError(str(request_id))
        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="roll.resolved",
            acting_seat_id=acting_seat_id,
            subject_seat_id=request.target_seat_id,
            subject_character_id=request.target_character_id,
            execution_mode=execution_mode,
            visibility=event_visibility,
            recipient_seat_ids=(request.target_seat_id,),
            payload_version=1,
            payload={
                "roll_request_id": str(request_id),
                "source": source,
                "formula": formula,
                "raw_dice": list(raw_dice),
                "kept_dice": list(kept_dice),
                "base_modifier": base_modifier,
                "flat_adjustment": flat_adjustment,
                "total": total,
                "visibility": visibility,
            },
            idempotency_key=idempotency_key,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        canonical_request_id = UUID(str(event.payload["roll_request_id"]))
        result = self.get_result_for_request(
            session_id=binding.session_id,
            request_id=canonical_request_id,
        )
        if result is None:
            raise RollRequestNotPendingPersistenceError(str(request_id))
        return result, event

    def record_quick_roll(
        self,
        *,
        binding: StoredTableActorBinding,
        acting_seat_id: UUID,
        subject_seat_id: UUID,
        subject_character_id: UUID | None,
        formula: str,
        raw_dice: tuple[int, ...],
        kept_dice: tuple[int, ...],
        base_modifier: int,
        flat_adjustment: int,
        total: int,
        visibility: str,
        event_visibility: str,
        idempotency_key: str | None,
    ) -> tuple[StoredRollResult, StoredTableEvent]:
        result_id = uuid4()

        def projection(connection, _event_id: UUID, _seq: int) -> None:
            connection.execute(
                insert(roll_results).values(
                    id=result_id,
                    roll_request_id=None,
                    session_id=binding.session_id,
                    acting_seat_id=acting_seat_id,
                    subject_seat_id=subject_seat_id,
                    subject_character_id=subject_character_id,
                    execution_mode="self",
                    source="quick",
                    formula=formula,
                    raw_dice=list(raw_dice),
                    kept_dice=list(kept_dice),
                    base_modifier=base_modifier,
                    flat_adjustment=flat_adjustment,
                    total=total,
                    visibility=visibility,
                )
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="roll.quick",
            acting_seat_id=acting_seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=subject_character_id,
            execution_mode="self",
            visibility=event_visibility,
            recipient_seat_ids=(subject_seat_id,),
            payload_version=1,
            payload={
                "roll_result_id": str(result_id),
                "source": "quick",
                "formula": formula,
                "raw_dice": list(raw_dice),
                "kept_dice": list(kept_dice),
                "base_modifier": base_modifier,
                "flat_adjustment": flat_adjustment,
                "total": total,
                "visibility": visibility,
            },
            idempotency_key=idempotency_key,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        canonical_result_id = UUID(str(event.payload["roll_result_id"]))
        with self.engine.connect() as connection:
            row = connection.execute(
                select(roll_results).where(roll_results.c.id == canonical_result_id)
            ).mappings().one()
        return self._result(row), event


__all__ = [
    "NewRollRequest",
    "RollRepository",
    "RollRequestNotFoundPersistenceError",
    "RollRequestNotPendingPersistenceError",
    "StoredRollRequest",
    "StoredRollResult",
]
