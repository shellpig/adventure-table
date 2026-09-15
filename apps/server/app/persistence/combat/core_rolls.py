from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.domain.character.schemas import CharacterState
from app.domain.combat.resolution import DeathSaveState, resolve_death_save
from app.persistence.characters import character_states
from app.persistence.combat.resolution import UNCONSCIOUS_REF, _death_state, _death_values
from app.persistence.combat.tables import combat_actions, combat_entries, combats
from app.persistence.rooms.p3c_runtime import roll_groups, roll_requests, roll_results
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    session_events,
)


class CombatCoreRollNotFoundError(LookupError):
    pass


class CombatCoreRollStateConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class NewSavingThrowUnit:
    target_entry_id: UUID
    target_seat_id: UUID | None
    target_character_id: UUID | None
    modifier: int


@dataclass(frozen=True)
class StoredCombatCoreRollRequest:
    id: UUID
    roll_group_id: UUID | None
    session_id: UUID
    target_seat_id: UUID | None
    target_character_id: UUID | None
    target_combat_entry_id: UUID
    request_type: str
    ability_ref: str | None
    dc: int | None
    modifier_mode: str
    flat_adjustment: int
    visibility: str
    status: str


@dataclass(frozen=True)
class CoreRollComputation:
    source: str
    formula: str
    raw_dice: tuple[int, ...]
    kept_dice: tuple[int, ...]
    base_modifier: int
    flat_adjustment: int
    total: int


CoreRollFactory = Callable[[], CoreRollComputation]


@dataclass(frozen=True)
class StoredSavingThrowResult:
    result_id: UUID
    roll_request_id: UUID
    target_entry_id: UUID
    total: int
    succeeded: bool


@dataclass(frozen=True)
class StoredDeathSaveResult:
    action_id: UUID
    result_id: UUID
    roll_request_id: UUID
    target_entry_id: UUID
    d20: int
    current_hp: int
    successes: int
    failures: int
    stable: bool
    dead: bool
    natural_20_recovery: bool


def _condition_ref(item: object) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        value = item.get("condition_ref") or item.get("key") or item.get("name")
        return value if isinstance(value, str) else None
    return None


def _without_condition(items: list[object], ref: str) -> list[object]:
    return [item for item in items if _condition_ref(item) != ref]


class CombatCoreRollRepository:
    """P4-C formal Saving Throw and Death Save persistence on canonical Roll tables."""

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    @staticmethod
    def _request(row) -> StoredCombatCoreRollRequest:
        return StoredCombatCoreRollRequest(
            id=row["id"],
            roll_group_id=row["roll_group_id"],
            session_id=row["session_id"],
            target_seat_id=row["target_seat_id"],
            target_character_id=row["target_character_id"],
            target_combat_entry_id=row["target_combat_entry_id"],
            request_type=row["request_type"],
            ability_ref=row["ability_ref"],
            dc=row["dc"],
            modifier_mode=row["modifier_mode"],
            flat_adjustment=int(row["flat_adjustment"]),
            visibility=row["visibility"],
            status=row["status"],
        )

    def get_request(self, *, session_id: UUID, request_id: UUID) -> StoredCombatCoreRollRequest | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(roll_requests).where(
                    roll_requests.c.id == request_id,
                    roll_requests.c.session_id == session_id,
                    roll_requests.c.target_combat_entry_id.is_not(None),
                )
            ).mappings().one_or_none()
        return self._request(row) if row is not None else None

    def _result_row(self, *, session_id: UUID, request_id: UUID):
        with self.engine.connect() as connection:
            return connection.execute(
                select(roll_results).where(
                    roll_results.c.session_id == session_id,
                    roll_results.c.roll_request_id == request_id,
                )
            ).mappings().one_or_none()

    def request_saving_throws(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        units: tuple[NewSavingThrowUnit, ...],
        ability_ref: str,
        dc: int,
        modifier_mode: str,
        visibility: str,
        event_visibility: str,
        recipient_seat_ids: tuple[UUID, ...],
        idempotency_key: str | None,
    ) -> tuple[UUID, tuple[StoredCombatCoreRollRequest, ...], StoredTableEvent]:
        if not units:
            raise ValueError("saving throw request requires at least one target")
        group_id = uuid4()
        request_ids = tuple(uuid4() for _ in units)

        def projection(connection, _event_id: UUID, _seq: int) -> None:
            combat = connection.execute(
                select(combats)
                .where(
                    combats.c.id == combat_id,
                    combats.c.campaign_id == binding.campaign_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None or combat["status"] != "running":
                raise CombatCoreRollStateConflictError("Saving Throws require a running Combat")
            connection.execute(
                insert(roll_groups).values(
                    id=group_id,
                    session_id=binding.session_id,
                    requested_by_seat_id=binding.seat_id,
                    label="Saving Throw",
                    visibility=visibility,
                    version=1,
                )
            )
            for request_id, unit in zip(request_ids, units, strict=True):
                target = connection.execute(
                    select(combat_entries)
                    .where(
                        combat_entries.c.id == unit.target_entry_id,
                        combat_entries.c.combat_id == combat_id,
                        combat_entries.c.status == "active",
                    )
                    .with_for_update()
                ).mappings().one_or_none()
                if target is None:
                    raise CombatCoreRollNotFoundError(str(unit.target_entry_id))
                connection.execute(
                    insert(roll_requests).values(
                        id=request_id,
                        session_id=binding.session_id,
                        roll_group_id=group_id,
                        target_seat_id=unit.target_seat_id,
                        target_character_id=unit.target_character_id,
                        target_combat_entry_id=unit.target_entry_id,
                        request_type="saving_throw",
                        ability_ref=ability_ref,
                        skill_ref=None,
                        dc=dc,
                        modifier_mode=modifier_mode,
                        flat_adjustment=unit.modifier,
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
            kind="combat.saves_requested",
            acting_seat_id=binding.seat_id,
            subject_seat_id=units[0].target_seat_id if len(units) == 1 else None,
            subject_character_id=units[0].target_character_id if len(units) == 1 else None,
            execution_mode="self",
            visibility=event_visibility,
            recipient_seat_ids=recipient_seat_ids,
            payload_version=1,
            payload={
                "combat_id": str(combat_id),
                "roll_group_id": str(group_id),
                "roll_request_ids": [str(value) for value in request_ids],
                "target_entry_ids": [str(unit.target_entry_id) for unit in units],
                "request_type": "saving_throw",
                "ability_ref": ability_ref,
                "modifier_mode": modifier_mode,
                "visibility": visibility,
            },
            idempotency_key=f"p4c-save-request:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        canonical_ids = tuple(UUID(str(value)) for value in event.payload["roll_request_ids"])
        stored = tuple(
            request
            for request_id in canonical_ids
            if (request := self.get_request(session_id=binding.session_id, request_id=request_id)) is not None
        )
        return UUID(str(event.payload["roll_group_id"])), stored, event

    def complete_saving_throw(
        self,
        *,
        binding: StoredTableActorBinding,
        request_id: UUID,
        acting_seat_id: UUID,
        execution_mode: str,
        result_factory: CoreRollFactory,
        idempotency_key: str | None,
    ) -> tuple[StoredSavingThrowResult, StoredTableEvent | None]:
        request = self.get_request(session_id=binding.session_id, request_id=request_id)
        if request is None or request.request_type != "saving_throw" or request.dc is None:
            raise CombatCoreRollNotFoundError(str(request_id))
        existing = self._result_row(session_id=binding.session_id, request_id=request_id)
        if existing is not None:
            return (
                StoredSavingThrowResult(
                    result_id=existing["id"],
                    roll_request_id=request_id,
                    target_entry_id=request.target_combat_entry_id,
                    total=int(existing["total"]),
                    succeeded=int(existing["total"]) >= int(request.dc),
                ),
                None,
            )
        result_id = uuid4()

        def projection(connection, event_id: UUID, _seq: int) -> None:
            locked = connection.execute(
                select(roll_requests)
                .where(
                    roll_requests.c.id == request_id,
                    roll_requests.c.session_id == binding.session_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if locked is None or locked["request_type"] != "saving_throw":
                raise CombatCoreRollNotFoundError(str(request_id))
            if locked["status"] != "pending":
                raise CombatCoreRollStateConflictError("Saving Throw RollRequest is already resolved")
            target = connection.execute(
                select(combat_entries)
                .where(
                    combat_entries.c.id == locked["target_combat_entry_id"],
                    combat_entries.c.status == "active",
                )
                .with_for_update()
            ).mappings().one_or_none()
            if target is None:
                raise CombatCoreRollNotFoundError("Saving Throw target is missing or inactive")
            computation = result_factory()
            now = datetime.now().astimezone()
            connection.execute(
                insert(roll_results).values(
                    id=result_id,
                    roll_request_id=request_id,
                    session_id=binding.session_id,
                    acting_seat_id=acting_seat_id,
                    subject_seat_id=locked["target_seat_id"],
                    subject_character_id=locked["target_character_id"],
                    subject_combat_entry_id=locked["target_combat_entry_id"],
                    execution_mode=execution_mode,
                    source=computation.source,
                    formula=computation.formula,
                    raw_dice=list(computation.raw_dice),
                    kept_dice=list(computation.kept_dice),
                    base_modifier=computation.base_modifier,
                    flat_adjustment=computation.flat_adjustment,
                    total=computation.total,
                    visibility=locked["visibility"],
                )
            )
            connection.execute(
                update(roll_requests)
                .where(roll_requests.c.id == request_id)
                .values(status="resolved", resolved_at=now, version=roll_requests.c.version + 1)
            )
            succeeded = computation.total >= int(locked["dc"])
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(
                    subject_character_id=locked["target_character_id"],
                    payload={
                        "combat_id": str(target["combat_id"]),
                        "roll_request_id": str(request_id),
                        "roll_result_id": str(result_id),
                        "target_entry_id": str(target["id"]),
                        "request_type": "saving_throw",
                        "ability_ref": locked["ability_ref"],
                        "formula": computation.formula,
                        "raw_dice": list(computation.raw_dice),
                        "kept_dice": list(computation.kept_dice),
                        "total": computation.total,
                        "succeeded": succeeded,
                        "visibility": locked["visibility"],
                    },
                )
            )

        event_visibility = "public" if request.visibility == "public" else (
            "actor_and_dm" if request.visibility == "roller_and_dm" else "dm_only"
        )
        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.save_resolved",
            acting_seat_id=acting_seat_id,
            subject_seat_id=request.target_seat_id,
            subject_character_id=request.target_character_id,
            execution_mode=execution_mode,
            visibility=event_visibility,
            recipient_seat_ids=(request.target_seat_id,) if request.target_seat_id else (),
            payload_version=1,
            payload={"roll_request_id": str(request_id), "request_type": "saving_throw"},
            idempotency_key=f"p4c-save-result:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        return (
            StoredSavingThrowResult(
                result_id=UUID(str(event.payload["roll_result_id"])),
                roll_request_id=request_id,
                target_entry_id=UUID(str(event.payload["target_entry_id"])),
                total=int(event.payload["total"]),
                succeeded=bool(event.payload["succeeded"]),
            ),
            event,
        )

    def request_death_save(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        entry_id: UUID,
        target_seat_id: UUID | None,
        target_character_id: UUID,
        execution_mode: str,
        idempotency_key: str | None,
    ) -> tuple[UUID, UUID, StoredTableEvent]:
        action_id = uuid4()
        group_id = uuid4()
        request_id = uuid4()

        def projection(connection, _event_id: UUID, _seq: int) -> None:
            combat = connection.execute(
                select(combats)
                .where(
                    combats.c.id == combat_id,
                    combats.c.campaign_id == binding.campaign_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            entry = connection.execute(
                select(combat_entries)
                .where(
                    combat_entries.c.id == entry_id,
                    combat_entries.c.combat_id == combat_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None or entry is None:
                raise CombatCoreRollNotFoundError(str(entry_id))
            if combat["status"] != "running" or entry["status"] != "active":
                raise CombatCoreRollStateConflictError("Death Save requires an active running Combat")
            if combat["current_turn_entry_id"] != entry_id:
                raise CombatCoreRollStateConflictError("Death Save can only be requested on that combatant's turn")
            if entry["subject_kind"] != "character" or entry["character_id"] != target_character_id:
                raise CombatCoreRollStateConflictError("Only Character CombatEntries make Death Saves")
            state_row = connection.execute(
                select(character_states.c.state_payload)
                .where(character_states.c.character_id == target_character_id)
                .with_for_update()
            ).mappings().one_or_none()
            if state_row is None:
                raise CombatCoreRollNotFoundError(str(target_character_id))
            state = CharacterState.model_validate(state_row["state_payload"])
            death = _death_state(entry)
            if state.current_hp != 0 or death.stable or death.dead:
                raise CombatCoreRollStateConflictError("Combatant is not eligible to make a Death Save")

            connection.execute(
                insert(roll_groups).values(
                    id=group_id,
                    session_id=binding.session_id,
                    requested_by_seat_id=binding.seat_id,
                    label="Death Save",
                    visibility="public",
                    version=1,
                )
            )
            connection.execute(
                insert(roll_requests).values(
                    id=request_id,
                    session_id=binding.session_id,
                    roll_group_id=group_id,
                    target_seat_id=target_seat_id,
                    target_character_id=target_character_id,
                    target_combat_entry_id=entry_id,
                    request_type="other",
                    ability_ref=None,
                    skill_ref=None,
                    dc=None,
                    modifier_mode="normal",
                    flat_adjustment=0,
                    visibility="public",
                    status="pending",
                    requested_by_seat_id=binding.seat_id,
                    version=1,
                )
            )
            connection.execute(
                insert(combat_actions).values(
                    id=action_id,
                    combat_id=combat_id,
                    entry_id=entry_id,
                    target_entry_id=entry_id,
                    session_id=binding.session_id,
                    acting_seat_id=binding.seat_id,
                    subject_seat_id=target_seat_id,
                    execution_mode=execution_mode,
                    action_kind="death_save",
                    economy_cost="none",
                    payload={"kind": "death_save"},
                    resolution_status="waiting_for_roll",
                    roll_request_id=request_id,
                    idempotency_key=idempotency_key,
                )
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="roll.requested",
            acting_seat_id=binding.seat_id,
            subject_seat_id=target_seat_id,
            subject_character_id=target_character_id,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(target_seat_id,) if target_seat_id else (),
            payload_version=1,
            payload={
                "combat_id": str(combat_id),
                "combat_action_id": str(action_id),
                "roll_group_id": str(group_id),
                "roll_request_ids": [str(request_id)],
                "target_entry_id": str(entry_id),
                "request_type": "death_save",
            },
            idempotency_key=f"p4c-death-save-request:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        return (
            UUID(str(event.payload["combat_action_id"])),
            UUID(str(event.payload["roll_request_ids"][0])),
            event,
        )

    def complete_death_save(
        self,
        *,
        binding: StoredTableActorBinding,
        request_id: UUID,
        acting_seat_id: UUID,
        execution_mode: str,
        result_factory: CoreRollFactory,
        idempotency_key: str | None,
    ) -> tuple[StoredDeathSaveResult, StoredTableEvent | None]:
        with self.engine.connect() as connection:
            action = connection.execute(
                select(combat_actions).where(
                    combat_actions.c.session_id == binding.session_id,
                    combat_actions.c.roll_request_id == request_id,
                    combat_actions.c.action_kind == "death_save",
                )
            ).mappings().one_or_none()
        if action is None:
            raise CombatCoreRollNotFoundError(str(request_id))
        if action["resolution_status"] == "resolved" and action["roll_result_id"] is not None:
            result = dict(action["resolution_result"] or {})
            return (
                StoredDeathSaveResult(
                    action_id=action["id"],
                    result_id=action["roll_result_id"],
                    roll_request_id=request_id,
                    target_entry_id=action["entry_id"],
                    d20=int(result["d20"]),
                    current_hp=int(result["current_hp"]),
                    successes=int(result["successes"]),
                    failures=int(result["failures"]),
                    stable=bool(result["stable"]),
                    dead=bool(result["dead"]),
                    natural_20_recovery=bool(result["natural_20_recovery"]),
                ),
                None,
            )
        result_id = uuid4()

        def projection(connection, event_id: UUID, _seq: int) -> None:
            locked_action = connection.execute(
                select(combat_actions)
                .where(combat_actions.c.id == action["id"])
                .with_for_update()
            ).mappings().one_or_none()
            request = connection.execute(
                select(roll_requests)
                .where(
                    roll_requests.c.id == request_id,
                    roll_requests.c.session_id == binding.session_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if locked_action is None or request is None:
                raise CombatCoreRollNotFoundError(str(request_id))
            if locked_action["resolution_status"] != "waiting_for_roll" or request["status"] != "pending":
                raise CombatCoreRollStateConflictError("Death Save is already resolved")
            combat = connection.execute(
                select(combats)
                .where(combats.c.id == locked_action["combat_id"])
                .with_for_update()
            ).mappings().one_or_none()
            entry = connection.execute(
                select(combat_entries)
                .where(combat_entries.c.id == locked_action["entry_id"])
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None or entry is None or combat["status"] != "running":
                raise CombatCoreRollStateConflictError("Death Save Combat is no longer active")
            if combat["current_turn_entry_id"] != entry["id"]:
                raise CombatCoreRollStateConflictError("Death Save target is no longer on its turn")
            if entry["character_id"] is None:
                raise CombatCoreRollStateConflictError("Death Save target has no Character")
            state_row = connection.execute(
                select(character_states.c.state_payload)
                .where(character_states.c.character_id == entry["character_id"])
                .with_for_update()
            ).mappings().one_or_none()
            if state_row is None:
                raise CombatCoreRollNotFoundError(str(entry["character_id"]))
            state = CharacterState.model_validate(state_row["state_payload"])
            death = _death_state(entry)
            if state.current_hp != 0 or death.stable or death.dead:
                raise CombatCoreRollStateConflictError("Combatant is no longer eligible for a Death Save")

            computation = result_factory()
            d20 = int(computation.kept_dice[0])
            outcome = resolve_death_save(d20=d20, state=death)
            now = datetime.now().astimezone()
            connection.execute(
                insert(roll_results).values(
                    id=result_id,
                    roll_request_id=request_id,
                    session_id=binding.session_id,
                    acting_seat_id=acting_seat_id,
                    subject_seat_id=request["target_seat_id"],
                    subject_character_id=request["target_character_id"],
                    subject_combat_entry_id=request["target_combat_entry_id"],
                    execution_mode=execution_mode,
                    source=computation.source,
                    formula=computation.formula,
                    raw_dice=list(computation.raw_dice),
                    kept_dice=list(computation.kept_dice),
                    base_modifier=computation.base_modifier,
                    flat_adjustment=computation.flat_adjustment,
                    total=computation.total,
                    visibility="public",
                )
            )
            connection.execute(
                update(roll_requests)
                .where(roll_requests.c.id == request_id)
                .values(status="resolved", resolved_at=now, version=roll_requests.c.version + 1)
            )
            state_payload = state.model_dump(mode="json")
            state_payload["current_hp"] = outcome.hp_after
            if outcome.natural_20_recovery:
                state_payload["conditions"] = _without_condition(
                    list(state_payload.get("conditions", [])),
                    UNCONSCIOUS_REF,
                )
            CharacterState.model_validate(state_payload)
            connection.execute(
                update(character_states)
                .where(character_states.c.character_id == entry["character_id"])
                .values(
                    state_payload=state_payload,
                    state_revision=character_states.c.state_revision + 1,
                    updated_at=now,
                )
            )
            connection.execute(
                update(combat_entries)
                .where(combat_entries.c.id == entry["id"])
                .values(**_death_values(outcome.death_saves), updated_at=now)
            )
            result_payload = {
                "d20": d20,
                "current_hp": outcome.hp_after,
                "successes": outcome.death_saves.successes,
                "failures": outcome.death_saves.failures,
                "stable": outcome.death_saves.stable,
                "dead": outcome.death_saves.dead,
                "natural_20_recovery": outcome.natural_20_recovery,
            }
            connection.execute(
                update(combat_actions)
                .where(combat_actions.c.id == locked_action["id"])
                .values(
                    resolution_status="resolved",
                    roll_result_id=result_id,
                    resolution_result=result_payload,
                )
            )
            connection.execute(
                update(combats)
                .where(combats.c.id == combat["id"])
                .values(revision=combats.c.revision + 1, updated_at=now)
            )
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(
                    subject_character_id=entry["character_id"],
                    payload={
                        "combat_id": str(combat["id"]),
                        "combat_action_id": str(locked_action["id"]),
                        "roll_request_id": str(request_id),
                        "roll_result_id": str(result_id),
                        "target_entry_id": str(entry["id"]),
                        **result_payload,
                    },
                )
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.death_save_resolved",
            acting_seat_id=acting_seat_id,
            subject_seat_id=action["subject_seat_id"],
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(action["subject_seat_id"],) if action["subject_seat_id"] else (),
            payload_version=1,
            payload={"roll_request_id": str(request_id)},
            idempotency_key=f"p4c-death-save-result:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        payload = dict(event.payload)
        return (
            StoredDeathSaveResult(
                action_id=UUID(str(payload["combat_action_id"])),
                result_id=UUID(str(payload["roll_result_id"])),
                roll_request_id=request_id,
                target_entry_id=UUID(str(payload["target_entry_id"])),
                d20=int(payload["d20"]),
                current_hp=int(payload["current_hp"]),
                successes=int(payload["successes"]),
                failures=int(payload["failures"]),
                stable=bool(payload["stable"]),
                dead=bool(payload["dead"]),
                natural_20_recovery=bool(payload["natural_20_recovery"]),
            ),
            event,
        )


__all__ = [
    "CombatCoreRollNotFoundError",
    "CombatCoreRollRepository",
    "CombatCoreRollStateConflictError",
    "CoreRollComputation",
    "NewSavingThrowUnit",
    "StoredCombatCoreRollRequest",
    "StoredDeathSaveResult",
    "StoredSavingThrowResult",
]
