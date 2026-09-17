from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.persistence.combat.tables import combat_entries, combats
from app.persistence.rooms.p3c_runtime import roll_groups, roll_requests, roll_results
from app.persistence.rooms.table_runtime import StoredTableActorBinding, StoredTableEvent, TableEventRepository, session_events


class InitiativeRequestNotFoundPersistenceError(LookupError):
    pass


class InitiativeRequestNotPendingPersistenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class NewInitiativeUnit:
    representative_entry_id: UUID
    entry_ids: tuple[UUID, ...]
    target_seat_id: UUID | None
    target_character_id: UUID | None
    request_type: str
    ability_ref: str | None
    flat_adjustment: int


@dataclass(frozen=True)
class StoredInitiativeRequest:
    id: UUID
    roll_group_id: UUID
    session_id: UUID
    target_seat_id: UUID | None
    target_character_id: UUID | None
    target_combat_entry_id: UUID
    request_type: str
    ability_ref: str | None
    modifier_mode: str
    flat_adjustment: int
    status: str


@dataclass(frozen=True)
class InitiativeComputation:
    source: str
    formula: str
    raw_dice: tuple[int, ...]
    kept_dice: tuple[int, ...]
    base_modifier: int
    flat_adjustment: int
    total: int


InitiativeComputationFactory = Callable[[], InitiativeComputation]


class CombatInitiativeRepository:
    """Formal P4-B initiative persistence using the canonical P3 Roll tables."""

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    @staticmethod
    def _request(row) -> StoredInitiativeRequest:
        return StoredInitiativeRequest(
            id=row["id"], roll_group_id=row["roll_group_id"], session_id=row["session_id"],
            target_seat_id=row["target_seat_id"], target_character_id=row["target_character_id"],
            target_combat_entry_id=row["target_combat_entry_id"], request_type=row["request_type"],
            ability_ref=row["ability_ref"], modifier_mode=row["modifier_mode"],
            flat_adjustment=int(row["flat_adjustment"]), status=row["status"],
        )

    def get_request(self, *, session_id: UUID, request_id: UUID) -> StoredInitiativeRequest | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(roll_requests).where(
                roll_requests.c.id == request_id, roll_requests.c.session_id == session_id,
                roll_requests.c.target_combat_entry_id.is_not(None),
            )).mappings().one_or_none()
        return self._request(row) if row is not None else None

    def get_result_id(self, *, session_id: UUID, request_id: UUID) -> UUID | None:
        with self.engine.connect() as connection:
            return connection.execute(select(roll_results.c.id).where(
                roll_results.c.session_id == session_id,
                roll_results.c.roll_request_id == request_id,
            )).scalar_one_or_none()

    def create_requests(self, *, binding: StoredTableActorBinding, combat_id: UUID,
                        units: tuple[NewInitiativeUnit, ...], modifier_mode: str,
                        idempotency_key: str | None):
        if not units:
            raise ValueError("initiative request requires at least one unit")
        group_id = uuid4()
        request_ids = tuple(uuid4() for _ in units)

        def projection(connection, _event_id: UUID, _seq: int) -> None:
            combat = connection.execute(select(combats).where(
                combats.c.id == combat_id, combats.c.campaign_id == binding.campaign_id,
                combats.c.status.in_(("initiative_pending", "running")),
            ).with_for_update()).mappings().one_or_none()
            if combat is None:
                raise InitiativeRequestNotFoundPersistenceError(str(combat_id))
            connection.execute(insert(roll_groups).values(
                id=group_id, session_id=binding.session_id, requested_by_seat_id=binding.seat_id,
                label="Initiative", visibility="public", version=1,
            ))
            for request_id, unit in zip(request_ids, units, strict=True):
                rows = connection.execute(select(combat_entries).where(
                    combat_entries.c.combat_id == combat_id, combat_entries.c.id.in_(unit.entry_ids),
                    combat_entries.c.status == "active",
                ).with_for_update()).mappings().all()
                if len(rows) != len(unit.entry_ids):
                    raise InitiativeRequestNotFoundPersistenceError("initiative CombatEntry target is missing or inactive")
                if any(row["initiative_roll_request_id"] is not None for row in rows):
                    raise InitiativeRequestNotPendingPersistenceError("initiative was already requested for this CombatEntry")
                connection.execute(insert(roll_requests).values(
                    id=request_id, session_id=binding.session_id, roll_group_id=group_id,
                    target_seat_id=unit.target_seat_id, target_character_id=unit.target_character_id,
                    target_combat_entry_id=unit.representative_entry_id, request_type=unit.request_type,
                    ability_ref=unit.ability_ref, skill_ref=None, dc=None, modifier_mode=modifier_mode,
                    flat_adjustment=unit.flat_adjustment, visibility="public", status="pending",
                    requested_by_seat_id=binding.seat_id, version=1,
                ))
                connection.execute(update(combat_entries).where(
                    combat_entries.c.id.in_(unit.entry_ids)
                ).values(initiative_roll_request_id=request_id, updated_at=datetime.now().astimezone()))

        recipients = tuple(unit.target_seat_id for unit in units if unit.target_seat_id is not None)
        event = self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="roll.requested", acting_seat_id=binding.seat_id,
            subject_seat_id=units[0].target_seat_id if len(units) == 1 else None,
            subject_character_id=units[0].target_character_id if len(units) == 1 else None,
            execution_mode="self", visibility="public", recipient_seat_ids=recipients,
            payload_version=1, payload={
                "roll_group_id": str(group_id), "roll_request_ids": [str(value) for value in request_ids],
                "request_type": "initiative", "modifier_mode": modifier_mode, "visibility": "public",
                "label": "Initiative", "combat_id": str(combat_id),
                "combat_entry_ids": [[str(entry_id) for entry_id in unit.entry_ids] for unit in units],
            },
            idempotency_key=f"p4b-initiative-request:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        canonical_ids = tuple(UUID(str(value)) for value in event.payload["roll_request_ids"])
        stored = tuple(request for request_id in canonical_ids if (
            request := self.get_request(session_id=binding.session_id, request_id=request_id)
        ) is not None)
        return UUID(str(event.payload["roll_group_id"])), stored, event

    def complete_request(self, *, binding: StoredTableActorBinding, request_id: UUID,
                         acting_seat_id: UUID, execution_mode: str,
                         result_factory: InitiativeComputationFactory,
                         idempotency_key: str | None):
        request = self.get_request(session_id=binding.session_id, request_id=request_id)
        if request is None:
            raise InitiativeRequestNotFoundPersistenceError(str(request_id))
        existing_id = self.get_result_id(session_id=binding.session_id, request_id=request_id)
        if existing_id is not None:
            with self.engine.connect() as connection:
                result = connection.execute(select(roll_results).where(roll_results.c.id == existing_id)).mappings().one()
                entry_ids = tuple(connection.execute(select(combat_entries.c.id).where(
                    combat_entries.c.initiative_roll_request_id == request_id
                )).scalars().all())
            return existing_id, int(result["total"]), entry_ids, None

        result_id = uuid4()
        def projection(connection, event_id: UUID, _seq: int) -> None:
            locked = connection.execute(select(roll_requests).where(
                roll_requests.c.id == request_id, roll_requests.c.session_id == binding.session_id,
            ).with_for_update()).mappings().one_or_none()
            if locked is None:
                raise InitiativeRequestNotFoundPersistenceError(str(request_id))
            if locked["status"] != "pending":
                raise InitiativeRequestNotPendingPersistenceError(str(request_id))
            entry_rows = connection.execute(select(combat_entries).where(
                combat_entries.c.initiative_roll_request_id == request_id,
                combat_entries.c.status == "active",
            ).with_for_update()).mappings().all()
            if not entry_rows:
                raise InitiativeRequestNotFoundPersistenceError("initiative request has no active CombatEntry")
            computation = result_factory()
            connection.execute(insert(roll_results).values(
                id=result_id, roll_request_id=request_id, session_id=binding.session_id,
                acting_seat_id=acting_seat_id, subject_seat_id=locked["target_seat_id"],
                subject_character_id=locked["target_character_id"],
                subject_combat_entry_id=locked["target_combat_entry_id"], execution_mode=execution_mode,
                source=computation.source, formula=computation.formula, raw_dice=list(computation.raw_dice),
                kept_dice=list(computation.kept_dice), base_modifier=computation.base_modifier,
                flat_adjustment=computation.flat_adjustment, total=computation.total, visibility="public",
            ))
            now = datetime.now().astimezone()
            connection.execute(update(roll_requests).where(roll_requests.c.id == request_id).values(
                status="resolved", resolved_at=now, version=roll_requests.c.version + 1,
            ))
            connection.execute(update(combat_entries).where(
                combat_entries.c.initiative_roll_request_id == request_id
            ).values(initiative_roll_result_id=result_id, initiative_total=computation.total, updated_at=now))
            connection.execute(update(session_events).where(session_events.c.id == event_id).values(payload={
                "roll_request_id": str(request_id), "roll_result_id": str(result_id), "source": computation.source,
                "formula": computation.formula, "raw_dice": list(computation.raw_dice),
                "kept_dice": list(computation.kept_dice), "base_modifier": computation.base_modifier,
                "flat_adjustment": computation.flat_adjustment, "total": computation.total,
                "visibility": "public", "combat_id": str(entry_rows[0]["combat_id"]),
                "combat_entry_ids": [str(row["id"]) for row in entry_rows],
            }))

        event = self.event_repository.append(
            room_id=binding.room_id, campaign_id=binding.campaign_id, session_id=binding.session_id,
            kind="roll.resolved", acting_seat_id=acting_seat_id, subject_seat_id=request.target_seat_id,
            subject_character_id=request.target_character_id, execution_mode=execution_mode,
            visibility="public", recipient_seat_ids=(request.target_seat_id,) if request.target_seat_id else (),
            payload_version=1, payload={"roll_request_id": str(request_id), "visibility": "public"},
            idempotency_key=f"p4b-initiative-result:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding, transaction_projection=projection,
        )
        return (
            UUID(str(event.payload["roll_result_id"])), int(event.payload["total"]),
            tuple(UUID(str(value)) for value in event.payload["combat_entry_ids"]), event,
        )


__all__ = [
    "CombatInitiativeRepository", "InitiativeComputation", "InitiativeRequestNotFoundPersistenceError",
    "InitiativeRequestNotPendingPersistenceError", "NewInitiativeUnit", "StoredInitiativeRequest",
]
