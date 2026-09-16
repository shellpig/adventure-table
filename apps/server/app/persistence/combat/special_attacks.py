from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from app.domain.character.schemas import CharacterState
from app.domain.combat.resolution import (
    SizeCategory,
    SpecialAttackKind,
    resolve_grapple_or_shove,
)
from app.persistence.characters import character_states
from app.persistence.combat.resolution import PRONE_REF, _add_condition
from app.persistence.combat.tables import combat_actions, combat_entries, combats, monster_instances
from app.persistence.rooms.p3c_runtime import roll_groups, roll_requests, roll_results
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    session_events,
)


GRAPPLED_REF = "srd5.1:condition:grappled"


class SpecialAttackNotFoundError(LookupError):
    pass


class SpecialAttackStateConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpecialAttackRollUnit:
    role: str
    target_entry_id: UUID
    target_seat_id: UUID | None
    target_character_id: UUID | None
    skill_ref: str
    modifier: int
    modifier_mode: str


@dataclass(frozen=True)
class SpecialAttackRollComputation:
    source: str
    formula: str
    raw_dice: tuple[int, ...]
    kept_dice: tuple[int, ...]
    base_modifier: int
    flat_adjustment: int
    total: int


SpecialAttackRollFactory = Callable[[], SpecialAttackRollComputation]


@dataclass(frozen=True)
class StoredSpecialAttackAction:
    action_id: UUID
    combat_id: UUID
    attacker_entry_id: UUID
    target_entry_id: UUID
    kind: SpecialAttackKind
    status: str
    in_reach: bool | None
    attacker_roll_request_id: UUID | None
    defender_roll_request_id: UUID | None
    attacker_skill: str
    defender_skill: str
    resolution_result: dict[str, Any] | None


def _stored(row: Any) -> StoredSpecialAttackAction:
    payload = dict(row["payload"] or {})
    target_entry_id = row["target_entry_id"]
    if target_entry_id is None:
        raise SpecialAttackNotFoundError(str(row["id"]))
    roll_ids = dict(payload.get("roll_request_ids") or {})
    adjudication = dict(payload.get("adjudication") or {})
    return StoredSpecialAttackAction(
        action_id=row["id"],
        combat_id=row["combat_id"],
        attacker_entry_id=row["entry_id"],
        target_entry_id=target_entry_id,
        kind=SpecialAttackKind(str(payload["kind"])),
        status=str(row["resolution_status"]),
        in_reach=adjudication.get("in_reach"),
        attacker_roll_request_id=(UUID(str(roll_ids["attacker"])) if roll_ids.get("attacker") else None),
        defender_roll_request_id=(UUID(str(roll_ids["defender"])) if roll_ids.get("defender") else None),
        attacker_skill=str(payload.get("attacker_skill") or "srd5.1:skill:athletics"),
        defender_skill=str(payload.get("defender_skill") or "srd5.1:skill:athletics"),
        resolution_result=dict(row["resolution_result"] or {}) or None,
    )


class SpecialAttackRepository:
    """Durable 2014 Grapple/Shove flow with DM geometry and formal opposed checks."""

    _KINDS = tuple(item.value for item in SpecialAttackKind)

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    def get(self, *, session_id: UUID, action_id: UUID) -> StoredSpecialAttackAction | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(combat_actions).where(
                    combat_actions.c.id == action_id,
                    combat_actions.c.session_id == session_id,
                    combat_actions.c.action_kind.in_(self._KINDS),
                )
            ).mappings().one_or_none()
        return _stored(row) if row is not None else None

    def find_by_roll_request(
        self,
        *,
        session_id: UUID,
        request_id: UUID,
    ) -> StoredSpecialAttackAction | None:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(combat_actions).where(
                    combat_actions.c.session_id == session_id,
                    combat_actions.c.action_kind.in_(self._KINDS),
                )
            ).mappings().all()
        needle = str(request_id)
        for row in rows:
            payload = dict(row["payload"] or {})
            ids = dict(payload.get("roll_request_ids") or {})
            if needle in {str(ids.get("attacker")), str(ids.get("defender"))}:
                return _stored(row)
        return None

    @staticmethod
    def _validate_attack_turn(combat: Any, attacker: Any) -> None:
        if combat["status"] != "running" or attacker["status"] != "active":
            raise SpecialAttackStateConflictError("Special Attack requires an active combatant in a running Combat")
        if combat["current_turn_entry_id"] != attacker["id"]:
            raise SpecialAttackStateConflictError("Special Attack can only be declared on the attacker's current turn")
        if attacker["surprised"]:
            raise SpecialAttackStateConflictError("Surprised combatant cannot use a Special Attack on its first turn")
        used = int(attacker["attacks_used"])
        allowed = int(attacker["attacks_allowed"])
        if used >= allowed:
            raise SpecialAttackStateConflictError("Attack budget is exhausted")
        if used == 0 and not attacker["action_available"]:
            raise SpecialAttackStateConflictError("Action is already spent")

    @staticmethod
    def _consume_attack_budget(connection: Any, attacker: Any) -> None:
        used = int(attacker["attacks_used"])
        allowed = int(attacker["attacks_allowed"])
        if used >= allowed:
            raise SpecialAttackStateConflictError("Attack budget is exhausted")
        values: dict[str, Any] = {
            "attacks_used": used + 1,
            "updated_at": datetime.now().astimezone(),
        }
        if used == 0:
            if not attacker["action_available"]:
                raise SpecialAttackStateConflictError("Action is already spent")
            values["action_available"] = False
        connection.execute(
            update(combat_entries).where(combat_entries.c.id == attacker["id"]).values(**values)
        )

    @staticmethod
    def _lock_action_context(connection: Any, *, binding: StoredTableActorBinding, action_id: UUID):
        action = connection.execute(
            select(combat_actions)
            .where(
                combat_actions.c.id == action_id,
                combat_actions.c.session_id == binding.session_id,
                combat_actions.c.action_kind.in_(tuple(item.value for item in SpecialAttackKind)),
            )
            .with_for_update()
        ).mappings().one_or_none()
        if action is None:
            raise SpecialAttackNotFoundError(str(action_id))
        combat = connection.execute(
            select(combats)
            .where(combats.c.id == action["combat_id"], combats.c.campaign_id == binding.campaign_id)
            .with_for_update()
        ).mappings().one_or_none()
        attacker = connection.execute(
            select(combat_entries)
            .where(combat_entries.c.id == action["entry_id"])
            .with_for_update()
        ).mappings().one_or_none()
        target = connection.execute(
            select(combat_entries)
            .where(combat_entries.c.id == action["target_entry_id"])
            .with_for_update()
        ).mappings().one_or_none()
        if combat is None or attacker is None or target is None or target["status"] != "active":
            raise SpecialAttackNotFoundError(str(action_id))
        return action, combat, attacker, target

    def request(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        attacker_entry_id: UUID,
        target_entry_id: UUID,
        subject_seat_id: UUID | None,
        execution_mode: str,
        kind: SpecialAttackKind,
        attacker_size: SizeCategory,
        target_size: SizeCategory,
        attacker_has_free_hand: bool,
        attacker_unit: SpecialAttackRollUnit,
        defender_unit: SpecialAttackRollUnit,
        idempotency_key: str | None,
    ) -> tuple[StoredSpecialAttackAction, StoredTableEvent]:
        action_id = uuid4()
        payload = {
            "kind": kind.value,
            "attacker_size": int(attacker_size),
            "target_size": int(target_size),
            "attacker_has_free_hand": attacker_has_free_hand,
            "attacker_skill": attacker_unit.skill_ref,
            "defender_skill": defender_unit.skill_ref,
            "attacker_modifier": attacker_unit.modifier,
            "defender_modifier": defender_unit.modifier,
            "attacker_modifier_mode": attacker_unit.modifier_mode,
            "defender_modifier_mode": defender_unit.modifier_mode,
            "attacker_target_seat_id": str(attacker_unit.target_seat_id) if attacker_unit.target_seat_id else None,
            "attacker_target_character_id": str(attacker_unit.target_character_id) if attacker_unit.target_character_id else None,
            "defender_target_seat_id": str(defender_unit.target_seat_id) if defender_unit.target_seat_id else None,
            "defender_target_character_id": str(defender_unit.target_character_id) if defender_unit.target_character_id else None,
            "adjudication": {"kind": "reach", "in_reach": None},
            "roll_request_ids": {},
        }

        def projection(connection: Any, event_id: UUID, _seq: int) -> None:
            combat = connection.execute(
                select(combats)
                .where(combats.c.id == combat_id, combats.c.campaign_id == binding.campaign_id)
                .with_for_update()
            ).mappings().one_or_none()
            attacker = connection.execute(
                select(combat_entries)
                .where(combat_entries.c.id == attacker_entry_id, combat_entries.c.combat_id == combat_id)
                .with_for_update()
            ).mappings().one_or_none()
            target = connection.execute(
                select(combat_entries)
                .where(combat_entries.c.id == target_entry_id, combat_entries.c.combat_id == combat_id)
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None or attacker is None or target is None or target["status"] != "active":
                raise SpecialAttackNotFoundError(str(combat_id))
            self._validate_attack_turn(combat, attacker)
            connection.execute(
                insert(combat_actions).values(
                    id=action_id,
                    combat_id=combat_id,
                    entry_id=attacker_entry_id,
                    target_entry_id=target_entry_id,
                    session_id=binding.session_id,
                    acting_seat_id=binding.seat_id,
                    subject_seat_id=subject_seat_id,
                    execution_mode=execution_mode,
                    action_kind=kind.value,
                    economy_cost="action",
                    payload=payload,
                    resolution_status="dm_adjudication_required",
                    idempotency_key=idempotency_key,
                )
            )
            event_payload = {
                "combat_id": str(combat_id),
                "combat_action_id": str(action_id),
                "attacker_entry_id": str(attacker_entry_id),
                "target_entry_id": str(target_entry_id),
                "target_is_hostile": bool(target["is_hostile"]),
                "kind": kind.value,
                "status": "dm_adjudication_required",
            }
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(subject_character_id=attacker["character_id"], payload=event_payload)
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.special_attack_adjudication_requested",
            acting_seat_id=binding.seat_id,
            subject_seat_id=subject_seat_id,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={
                "combat_id": str(combat_id),
                "combat_action_id": str(action_id),
                "attacker_entry_id": str(attacker_entry_id),
                "target_entry_id": str(target_entry_id),
                "kind": kind.value,
                "status": "dm_adjudication_required",
            },
            idempotency_key=f"p4c-special-request:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get(
            session_id=binding.session_id,
            action_id=UUID(str(event.payload["combat_action_id"])),
        )
        if stored is None:
            raise SpecialAttackNotFoundError(str(action_id))
        return stored, event

    def adjudicate_reach(
        self,
        *,
        binding: StoredTableActorBinding,
        action_id: UUID,
        in_reach: bool,
        idempotency_key: str | None,
    ) -> tuple[StoredSpecialAttackAction, StoredTableEvent]:
        group_id = uuid4()
        attacker_request_id = uuid4()
        defender_request_id = uuid4()

        def projection(connection: Any, event_id: UUID, _seq: int) -> None:
            action, combat, attacker, target = self._lock_action_context(
                connection,
                binding=binding,
                action_id=action_id,
            )
            if action["resolution_status"] != "dm_adjudication_required":
                raise SpecialAttackStateConflictError("Special Attack no longer requires DM adjudication")
            self._validate_attack_turn(combat, attacker)
            payload = dict(action["payload"] or {})
            adjudication = dict(payload.get("adjudication") or {})
            adjudication["in_reach"] = in_reach
            payload["adjudication"] = adjudication
            if not in_reach:
                result = {"status": "invalid", "reason": "out_of_reach", "kind": payload["kind"]}
                connection.execute(
                    update(combat_actions)
                    .where(combat_actions.c.id == action_id)
                    .values(payload=payload, resolution_status="resolved", resolution_result=result)
                )
                event_payload = {
                    "combat_id": str(action["combat_id"]),
                    "combat_action_id": str(action_id),
                    "attacker_entry_id": str(attacker["id"]),
                    "target_entry_id": str(target["id"]),
                    "target_is_hostile": bool(target["is_hostile"]),
                    "kind": payload["kind"],
                    "in_reach": False,
                    "status": "resolved",
                    "resolution_result": result,
                }
            else:
                self._consume_attack_budget(connection, attacker)
                roll_ids = {
                    "attacker": str(attacker_request_id),
                    "defender": str(defender_request_id),
                }
                payload["roll_request_ids"] = roll_ids
                connection.execute(
                    insert(roll_groups).values(
                        id=group_id,
                        session_id=binding.session_id,
                        requested_by_seat_id=binding.seat_id,
                        label=str(payload["kind"]).replace("_", " ").title(),
                        visibility="public",
                        version=1,
                    )
                )
                for role, request_id, entry, seat_key, char_key, skill_key, modifier_key, mode_key in (
                    (
                        "attacker",
                        attacker_request_id,
                        attacker,
                        "attacker_target_seat_id",
                        "attacker_target_character_id",
                        "attacker_skill",
                        "attacker_modifier",
                        "attacker_modifier_mode",
                    ),
                    (
                        "defender",
                        defender_request_id,
                        target,
                        "defender_target_seat_id",
                        "defender_target_character_id",
                        "defender_skill",
                        "defender_modifier",
                        "defender_modifier_mode",
                    ),
                ):
                    seat_id = UUID(payload[seat_key]) if payload.get(seat_key) else None
                    character_id = UUID(payload[char_key]) if payload.get(char_key) else None
                    connection.execute(
                        insert(roll_requests).values(
                            id=request_id,
                            session_id=binding.session_id,
                            roll_group_id=group_id,
                            target_seat_id=seat_id,
                            target_character_id=character_id,
                            target_combat_entry_id=entry["id"],
                            request_type="skill",
                            ability_ref=None,
                            skill_ref=str(payload[skill_key]),
                            dc=None,
                            modifier_mode=str(payload[mode_key]),
                            flat_adjustment=int(payload[modifier_key]),
                            visibility="public",
                            status="pending",
                            requested_by_seat_id=binding.seat_id,
                            version=1,
                        )
                    )
                connection.execute(
                    update(combat_actions)
                    .where(combat_actions.c.id == action_id)
                    .values(
                        payload=payload,
                        resolution_status="waiting_for_roll",
                        roll_request_id=attacker_request_id,
                    )
                )
                connection.execute(
                    update(combats)
                    .where(combats.c.id == action["combat_id"])
                    .values(revision=combats.c.revision + 1, updated_at=datetime.now().astimezone())
                )
                event_payload = {
                    "combat_id": str(action["combat_id"]),
                    "combat_action_id": str(action_id),
                    "attacker_entry_id": str(attacker["id"]),
                    "target_entry_id": str(target["id"]),
                    "target_is_hostile": bool(target["is_hostile"]),
                    "kind": payload["kind"],
                    "in_reach": True,
                    "status": "waiting_for_roll",
                    "roll_group_id": str(group_id),
                    "roll_request_ids": roll_ids,
                }
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(subject_character_id=attacker["character_id"], payload=event_payload)
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.special_attack_adjudicated",
            acting_seat_id=binding.seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode="self",
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={"combat_action_id": str(action_id), "in_reach": in_reach},
            idempotency_key=f"p4c-special-adjudication:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get(
            session_id=binding.session_id,
            action_id=UUID(str(event.payload["combat_action_id"])),
        )
        if stored is None:
            raise SpecialAttackNotFoundError(str(action_id))
        return stored, event

    @staticmethod
    def _apply_condition(connection: Any, target: Any, *, condition_ref: str, note: str) -> None:
        now = datetime.now().astimezone()
        if target["subject_kind"] == "character":
            character_id = target["character_id"]
            if character_id is None:
                raise SpecialAttackStateConflictError("Character target has no Character identity")
            row = connection.execute(
                select(character_states.c.state_payload, character_states.c.state_revision)
                .where(character_states.c.character_id == character_id)
                .with_for_update()
            ).mappings().one_or_none()
            if row is None:
                raise SpecialAttackNotFoundError(str(character_id))
            state = CharacterState.model_validate(row["state_payload"])
            payload = state.model_dump(mode="json")
            conditions = list(payload.get("conditions", []))
            _add_condition(conditions, condition_ref, note)
            payload["conditions"] = conditions
            CharacterState.model_validate(payload)
            state_update = connection.execute(
                update(character_states)
                .where(
                    character_states.c.character_id == character_id,
                    character_states.c.state_revision == int(row["state_revision"]),
                )
                .values(
                    state_payload=payload,
                    state_revision=int(row["state_revision"]) + 1,
                    updated_at=func.now(),
                )
            )
            if state_update.rowcount != 1:
                raise SpecialAttackStateConflictError(
                    "Character State changed while applying Special Attack condition"
                )
            return
        if target["subject_kind"] == "monster":
            monster_id = target["monster_instance_id"]
            if monster_id is None:
                raise SpecialAttackStateConflictError("Monster target has no Monster identity")
            row = connection.execute(
                select(monster_instances.c.conditions)
                .where(monster_instances.c.id == monster_id)
                .with_for_update()
            ).mappings().one_or_none()
            if row is None:
                raise SpecialAttackNotFoundError(str(monster_id))
            conditions = list(row["conditions"] or [])
            _add_condition(conditions, condition_ref, note)
            connection.execute(
                update(monster_instances)
                .where(monster_instances.c.id == monster_id)
                .values(conditions=conditions, updated_at=now)
            )
            return
        raise SpecialAttackStateConflictError("unsupported Special Attack target kind")

    def complete_roll(
        self,
        *,
        binding: StoredTableActorBinding,
        request_id: UUID,
        acting_seat_id: UUID,
        execution_mode: str,
        result_factory: SpecialAttackRollFactory,
        idempotency_key: str | None,
    ) -> tuple[StoredSpecialAttackAction, StoredTableEvent]:
        action = self.find_by_roll_request(session_id=binding.session_id, request_id=request_id)
        if action is None:
            raise SpecialAttackNotFoundError(str(request_id))
        result_id = uuid4()

        def projection(connection: Any, event_id: UUID, _seq: int) -> None:
            locked_action, combat, attacker, target = self._lock_action_context(
                connection,
                binding=binding,
                action_id=action.action_id,
            )
            if locked_action["resolution_status"] != "waiting_for_roll":
                raise SpecialAttackStateConflictError("Special Attack is not waiting for opposed checks")
            payload = dict(locked_action["payload"] or {})
            roll_ids = dict(payload.get("roll_request_ids") or {})
            valid_ids = {str(roll_ids.get("attacker")), str(roll_ids.get("defender"))}
            if str(request_id) not in valid_ids:
                raise SpecialAttackNotFoundError(str(request_id))
            request = connection.execute(
                select(roll_requests)
                .where(roll_requests.c.id == request_id, roll_requests.c.session_id == binding.session_id)
                .with_for_update()
            ).mappings().one_or_none()
            if request is None or request["status"] != "pending":
                raise SpecialAttackStateConflictError("Special Attack RollRequest is already resolved")
            computation = result_factory()
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
            ids = [UUID(str(roll_ids["attacker"])), UUID(str(roll_ids["defender"]))]
            rows = connection.execute(
                select(roll_results.c.roll_request_id, roll_results.c.total).where(
                    roll_results.c.roll_request_id.in_(ids)
                )
            ).mappings().all()
            totals = {str(row["roll_request_id"]): int(row["total"]) for row in rows}
            totals[str(request_id)] = computation.total
            final_result: dict[str, Any] | None = None
            status = "waiting_for_roll"
            if all(str(value) in totals for value in ids):
                outcome = resolve_grapple_or_shove(
                    kind=SpecialAttackKind(str(payload["kind"])),
                    attacker_size=SizeCategory(int(payload["attacker_size"])),
                    target_size=SizeCategory(int(payload["target_size"])),
                    attacker_check_total=totals[str(ids[0])],
                    target_check_total=totals[str(ids[1])],
                    attacker_has_free_hand=bool(payload["attacker_has_free_hand"]),
                    reach_confirmed=True,
                )
                final_result = {
                    "kind": outcome.kind.value,
                    "status": outcome.status,
                    "reason": outcome.reason,
                    "attacker_total": totals[str(ids[0])],
                    "target_total": totals[str(ids[1])],
                    "attacker_skill": payload["attacker_skill"],
                    "defender_skill": payload["defender_skill"],
                    "condition_to_apply": outcome.condition_to_apply,
                    "push_distance_ft": outcome.push_distance_ft,
                }
                if outcome.status == "success" and outcome.condition_to_apply == "grappled":
                    self._apply_condition(
                        connection,
                        target,
                        condition_ref=GRAPPLED_REF,
                        note=f"P4-C Grappled by combat entry {attacker['id']}",
                    )
                elif outcome.status == "success" and outcome.condition_to_apply == "prone":
                    self._apply_condition(
                        connection,
                        target,
                        condition_ref=PRONE_REF,
                        note=f"P4-C Shoved prone by combat entry {attacker['id']}",
                    )
                connection.execute(
                    update(combat_actions)
                    .where(combat_actions.c.id == locked_action["id"])
                    .values(
                        resolution_status="resolved",
                        roll_result_id=result_id,
                        resolution_result=final_result,
                    )
                )
                connection.execute(
                    update(combats)
                    .where(combats.c.id == combat["id"])
                    .values(revision=combats.c.revision + 1, updated_at=now)
                )
                status = "resolved"
            event_payload = {
                "combat_id": str(combat["id"]),
                "combat_action_id": str(locked_action["id"]),
                "roll_request_id": str(request_id),
                "roll_result_id": str(result_id),
                "target_entry_id": str(request["target_combat_entry_id"]),
                "target_is_hostile": bool(target["is_hostile"]),
                "total": computation.total,
                "status": status,
                "resolution_result": final_result,
            }
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(subject_character_id=request["target_character_id"], payload=event_payload)
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.special_attack_roll_resolved",
            acting_seat_id=acting_seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode=execution_mode,
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={
                "combat_action_id": str(action.action_id),
                "roll_request_id": str(request_id),
            },
            idempotency_key=f"p4c-special-roll:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get(
            session_id=binding.session_id,
            action_id=UUID(str(event.payload["combat_action_id"])),
        )
        if stored is None:
            raise SpecialAttackNotFoundError(str(action.action_id))
        return stored, event


__all__ = [
    "GRAPPLED_REF",
    "SpecialAttackNotFoundError",
    "SpecialAttackRepository",
    "SpecialAttackRollComputation",
    "SpecialAttackRollUnit",
    "SpecialAttackStateConflictError",
    "StoredSpecialAttackAction",
]
