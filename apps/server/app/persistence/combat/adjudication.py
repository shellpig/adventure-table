from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.domain.combat.resolution import ResolvedAttack, RollMode
from app.persistence.combat.attacks import _attack_payload
from app.persistence.combat.tables import combat_actions, combat_entries, combats
from app.persistence.rooms.p3c_runtime import roll_groups, roll_requests
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    session_events,
)


class CombatAdjudicationNotFoundError(LookupError):
    pass


class CombatAdjudicationStateConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredAttackAdjudication:
    action_id: UUID
    combat_id: UUID
    attacker_entry_id: UUID
    target_entry_id: UUID
    source_ref: str
    name: str
    status: str
    roll_request_id: UUID | None
    in_range: bool | None
    resolution_result: dict[str, Any] | None


def _stored(row) -> StoredAttackAdjudication:
    payload = dict(row["payload"] or {})
    attack = dict(payload.get("resolved_attack") or {})
    target_entry_id = row["target_entry_id"]
    if target_entry_id is None or not attack:
        raise CombatAdjudicationNotFoundError(str(row["id"]))
    adjudication = dict(payload.get("adjudication") or {})
    return StoredAttackAdjudication(
        action_id=row["id"],
        combat_id=row["combat_id"],
        attacker_entry_id=row["entry_id"],
        target_entry_id=target_entry_id,
        source_ref=str(attack["source_ref"]),
        name=str(attack["name"]),
        status=str(row["resolution_status"]),
        roll_request_id=row["roll_request_id"],
        in_range=adjudication.get("in_range"),
        resolution_result=dict(row["resolution_result"] or {}) or None,
    )


class CombatAdjudicationRepository:
    """Durable Quick-Combat geometry adjudication without guessing distance."""

    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    def get(self, *, session_id: UUID, action_id: UUID) -> StoredAttackAdjudication | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(combat_actions).where(
                    combat_actions.c.id == action_id,
                    combat_actions.c.session_id == session_id,
                    combat_actions.c.action_kind == "attack",
                )
            ).mappings().one_or_none()
        return _stored(row) if row is not None else None

    @staticmethod
    def _validate_attack_turn(combat, attacker) -> None:
        if combat["status"] != "running" or attacker["status"] != "active":
            raise CombatAdjudicationStateConflictError("Attack requires an active combatant in a running Combat")
        if combat["current_turn_entry_id"] != attacker["id"]:
            raise CombatAdjudicationStateConflictError("Attack can only be declared on the attacker's current turn")
        if attacker["surprised"]:
            raise CombatAdjudicationStateConflictError("Surprised combatant cannot Attack on its first turn")

    @staticmethod
    def _consume_attack_budget(connection, attacker) -> None:
        values: dict[str, Any] = {"updated_at": datetime.now().astimezone()}
        used = int(attacker["attacks_used"])
        allowed = int(attacker["attacks_allowed"])
        if used >= allowed:
            raise CombatAdjudicationStateConflictError("Attack budget is exhausted")
        if used == 0:
            if not attacker["action_available"]:
                raise CombatAdjudicationStateConflictError("Action is already spent")
            values["action_available"] = False
        values["attacks_used"] = used + 1
        connection.execute(
            update(combat_entries).where(combat_entries.c.id == attacker["id"]).values(**values)
        )

    def request_attack_adjudication(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        attacker_entry_id: UUID,
        target_entry_id: UUID,
        subject_seat_id: UUID | None,
        execution_mode: str,
        attack: ResolvedAttack,
        target_ac: int,
        modifier_mode: RollMode,
        idempotency_key: str | None,
    ) -> tuple[StoredAttackAdjudication, StoredTableEvent]:
        action_id = uuid4()
        payload = {
            "resolved_attack": _attack_payload(attack),
            "modifier_mode": modifier_mode.value,
            "target_ac": target_ac,
            "adjudication": {"kind": "range", "in_range": None},
        }

        def projection(connection, event_id: UUID, _seq: int) -> None:
            combat = connection.execute(
                select(combats)
                .where(combats.c.id == combat_id, combats.c.campaign_id == binding.campaign_id)
                .with_for_update()
            ).mappings().one_or_none()
            attacker = connection.execute(
                select(combat_entries)
                .where(
                    combat_entries.c.id == attacker_entry_id,
                    combat_entries.c.combat_id == combat_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            target = connection.execute(
                select(combat_entries)
                .where(
                    combat_entries.c.id == target_entry_id,
                    combat_entries.c.combat_id == combat_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None or attacker is None or target is None or target["status"] != "active":
                raise CombatAdjudicationNotFoundError(str(combat_id))
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
                    action_kind="attack",
                    economy_cost="action",
                    payload=payload,
                    resolution_status="dm_adjudication_required",
                    idempotency_key=idempotency_key,
                )
            )
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(subject_character_id=attacker["character_id"])
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.adjudication_requested",
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
                "kind": "range",
                "status": "dm_adjudication_required",
            },
            idempotency_key=f"p4c-attack-adjudication:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get(session_id=binding.session_id, action_id=UUID(str(event.payload["combat_action_id"])))
        if stored is None:
            raise CombatAdjudicationNotFoundError(str(action_id))
        return stored, event

    def adjudicate_attack_range(
        self,
        *,
        binding: StoredTableActorBinding,
        action_id: UUID,
        in_range: bool,
        idempotency_key: str | None,
    ) -> tuple[StoredAttackAdjudication, StoredTableEvent]:
        roll_group_id = uuid4()
        roll_request_id = uuid4()

        def projection(connection, event_id: UUID, _seq: int) -> None:
            action = connection.execute(
                select(combat_actions)
                .where(
                    combat_actions.c.id == action_id,
                    combat_actions.c.session_id == binding.session_id,
                    combat_actions.c.action_kind == "attack",
                )
                .with_for_update()
            ).mappings().one_or_none()
            if action is None:
                raise CombatAdjudicationNotFoundError(str(action_id))
            if action["resolution_status"] != "dm_adjudication_required":
                raise CombatAdjudicationStateConflictError("Attack no longer requires DM adjudication")
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
                raise CombatAdjudicationNotFoundError(str(action_id))
            self._validate_attack_turn(combat, attacker)
            payload = dict(action["payload"] or {})
            adjudication = dict(payload.get("adjudication") or {})
            adjudication["in_range"] = in_range
            payload["adjudication"] = adjudication
            now = datetime.now().astimezone()
            if not in_range:
                result = {"status": "invalid", "reason": "out_of_range"}
                connection.execute(
                    update(combat_actions)
                    .where(combat_actions.c.id == action_id)
                    .values(
                        payload=payload,
                        resolution_status="resolved",
                        resolution_result=result,
                    )
                )
                event_payload = {
                    "combat_id": str(action["combat_id"]),
                    "combat_action_id": str(action_id),
                    "attacker_entry_id": str(action["entry_id"]),
                    "target_entry_id": str(action["target_entry_id"]),
                    "in_range": False,
                    "status": "resolved",
                    "resolution_result": result,
                }
            else:
                self._consume_attack_budget(connection, attacker)
                attack = dict(payload["resolved_attack"])
                connection.execute(
                    insert(roll_groups).values(
                        id=roll_group_id,
                        session_id=binding.session_id,
                        requested_by_seat_id=binding.seat_id,
                        label=str(attack["name"]),
                        visibility="public",
                        version=1,
                    )
                )
                connection.execute(
                    insert(roll_requests).values(
                        id=roll_request_id,
                        session_id=binding.session_id,
                        roll_group_id=roll_group_id,
                        target_seat_id=action["subject_seat_id"],
                        target_character_id=attacker["character_id"],
                        target_combat_entry_id=attacker["id"],
                        request_type="other",
                        ability_ref=None,
                        skill_ref=None,
                        dc=None,
                        modifier_mode=payload["modifier_mode"],
                        flat_adjustment=int(attack["attack_bonus"]),
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
                        roll_request_id=roll_request_id,
                    )
                )
                connection.execute(
                    update(combats)
                    .where(combats.c.id == action["combat_id"])
                    .values(revision=combats.c.revision + 1, updated_at=now)
                )
                event_payload = {
                    "combat_id": str(action["combat_id"]),
                    "combat_action_id": str(action_id),
                    "attacker_entry_id": str(action["entry_id"]),
                    "target_entry_id": str(action["target_entry_id"]),
                    "in_range": True,
                    "status": "waiting_for_roll",
                    "roll_group_id": str(roll_group_id),
                    "roll_request_id": str(roll_request_id),
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
            kind="combat.adjudication_resolved",
            acting_seat_id=binding.seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode="self",
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={"combat_action_id": str(action_id), "in_range": in_range},
            idempotency_key=f"p4c-attack-adjudication-result:{idempotency_key}" if idempotency_key else None,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get(session_id=binding.session_id, action_id=UUID(str(event.payload["combat_action_id"])))
        if stored is None:
            raise CombatAdjudicationNotFoundError(str(action_id))
        return stored, event


__all__ = [
    "CombatAdjudicationNotFoundError",
    "CombatAdjudicationRepository",
    "CombatAdjudicationStateConflictError",
    "StoredAttackAdjudication",
]
