from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.domain.combat.reaction_service import open_opportunity_attack_window
from app.domain.combat.resolution import ResolvedAttack, RollMode
from app.persistence.combat.attacks import _attack_payload
from app.persistence.combat.lifecycle import StoredCombatAction, combat_action_from_row
from app.persistence.combat.reactions import write_reaction_window
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
    modifier_mode: str
    attack_bonus: int
    target_ac: int
    status: str
    roll_request_id: UUID | None
    in_range: bool | None
    resolution_result: dict[str, Any] | None
    content_ref: str | None = None
    presentation_field: str | None = None


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
        modifier_mode=str(payload["modifier_mode"]),
        attack_bonus=int(attack["attack_bonus"]),
        target_ac=int(payload["target_ac"]),
        status=str(row["resolution_status"]),
        roll_request_id=row["roll_request_id"],
        in_range=adjudication.get("in_range"),
        resolution_result=dict(row["resolution_result"] or {}) or None,
        content_ref=attack.get("content_ref"),
        presentation_field=attack.get("presentation_field"),
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

    def get_action(self, *, session_id: UUID, action_id: UUID) -> StoredCombatAction | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(combat_actions).where(
                    combat_actions.c.id == action_id,
                    combat_actions.c.session_id == session_id,
                )
            ).mappings().one_or_none()
        return combat_action_from_row(row) if row is not None else None

    def list_pending(self, *, combat_id: UUID) -> tuple[StoredCombatAction, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(combat_actions)
                .where(
                    combat_actions.c.combat_id == combat_id,
                    combat_actions.c.resolution_status == "dm_adjudication_required",
                )
                .order_by(combat_actions.c.created_at.asc())
            ).mappings().all()
        return tuple(combat_action_from_row(r) for r in rows)

    @staticmethod
    def _validate_attack_turn(combat, attacker) -> None:
        if combat["status"] != "running" or attacker["status"] != "active":
            raise CombatAdjudicationStateConflictError(
                "Attack requires an active combatant in a running Combat"
            )
        if combat["current_turn_entry_id"] != attacker["id"]:
            raise CombatAdjudicationStateConflictError(
                "Attack can only be declared on the attacker's current turn"
            )
        if attacker["surprised"]:
            raise CombatAdjudicationStateConflictError(
                "Surprised combatant cannot Attack on its first turn"
            )

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
            update(combat_entries)
            .where(combat_entries.c.id == attacker["id"])
            .values(**values)
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
                .where(
                    combats.c.id == combat_id,
                    combats.c.campaign_id == binding.campaign_id,
                )
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
            if (
                combat is None
                or attacker is None
                or target is None
                or target["status"] != "active"
            ):
                raise CombatAdjudicationNotFoundError(str(combat_id))
            self._validate_attack_turn(combat, attacker)
            now = datetime.now().astimezone()
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
                update(combats)
                .where(combats.c.id == combat_id)
                .values(revision=combats.c.revision + 1, updated_at=now)
            )
            event_payload = {
                "combat_id": str(combat_id),
                "combat_action_id": str(action_id),
                "attacker_entry_id": str(attacker_entry_id),
                "target_entry_id": str(target_entry_id),
                "target_is_hostile": bool(target["is_hostile"]),
                "kind": "range",
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
            idempotency_key=(
                f"p4c-attack-adjudication:{idempotency_key}"
                if idempotency_key
                else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get(
            session_id=binding.session_id,
            action_id=UUID(str(event.payload["combat_action_id"])),
        )
        if stored is None:
            raise CombatAdjudicationNotFoundError(str(action_id))
        return stored, event

    def adjudicate_attack_range(
        self,
        *,
        binding: StoredTableActorBinding,
        action_id: UUID,
        in_range: bool,
        roll_mode: RollMode | None = None,
        note: str | None = None,
        idempotency_key: str | None,
    ) -> tuple[StoredAttackAdjudication, StoredTableEvent]:
        roll_group_id = uuid4()
        roll_request_id = uuid4()
        decision = {
            "in_range": in_range,
            "roll_mode": roll_mode.value if roll_mode is not None else None,
            "note": note,
        }

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
                raise CombatAdjudicationStateConflictError(
                    "Attack no longer requires DM adjudication"
                )
            combat = connection.execute(
                select(combats)
                .where(
                    combats.c.id == action["combat_id"],
                    combats.c.campaign_id == binding.campaign_id,
                )
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
            if (
                combat is None
                or attacker is None
                or target is None
                or target["status"] != "active"
            ):
                raise CombatAdjudicationNotFoundError(str(action_id))
            self._validate_attack_turn(combat, attacker)
            payload = dict(action["payload"] or {})
            adjudication = dict(payload.get("adjudication") or {})
            adjudication["in_range"] = in_range
            if roll_mode is not None:
                adjudication["roll_mode"] = roll_mode.value
            if note is not None:
                adjudication["note"] = note
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
                    "target_is_hostile": bool(target["is_hostile"]),
                    "in_range": False,
                    "status": "resolved",
                    "resolution_result": result,
                    "decision": decision,
                }
            else:
                self._consume_attack_budget(connection, attacker)
                attack = dict(payload["resolved_attack"])
                effective_modifier_mode = (
                    roll_mode.value if roll_mode is not None else payload["modifier_mode"]
                )
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
                        modifier_mode=effective_modifier_mode,
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
                event_payload = {
                    "combat_id": str(action["combat_id"]),
                    "combat_action_id": str(action_id),
                    "attacker_entry_id": str(action["entry_id"]),
                    "target_entry_id": str(action["target_entry_id"]),
                    "target_is_hostile": bool(target["is_hostile"]),
                    "in_range": True,
                    "status": "waiting_for_roll",
                    "roll_group_id": str(roll_group_id),
                    "roll_request_id": str(roll_request_id),
                    "decision": decision,
                }
            # Both the pending->resolved and pending->waiting transition are
            # canonical combat-state mutations and advance the combat revision.
            connection.execute(
                update(combats)
                .where(combats.c.id == action["combat_id"])
                .values(revision=combats.c.revision + 1, updated_at=now)
            )
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(
                    subject_character_id=attacker["character_id"],
                    payload=event_payload,
                )
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
            payload={
                "combat_action_id": str(action_id),
                "in_range": in_range,
                "decision": decision,
            },
            idempotency_key=(
                f"p4c-attack-adjudication-result:{idempotency_key}"
                if idempotency_key
                else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get(
            session_id=binding.session_id,
            action_id=UUID(str(event.payload["combat_action_id"])),
        )
        if stored is None:
            raise CombatAdjudicationNotFoundError(str(action_id))
        return stored, event

    @staticmethod
    def _insert_pending_adjudication(
        connection,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        action_id: UUID,
        entry_id: UUID,
        target_entry_id: UUID | None,
        subject_seat_id: UUID | None,
        execution_mode: str,
        action_kind: str,
        payload: dict[str, Any],
        event_id: UUID,
        event_payload: dict[str, Any],
        idempotency_key: str | None,
        extra_entry_ids: tuple[UUID, ...] = (),
    ) -> None:
        combat = connection.execute(
            select(combats)
            .where(
                combats.c.id == combat_id,
                combats.c.campaign_id == binding.campaign_id,
            )
            .with_for_update()
        ).mappings().one_or_none()
        subject = connection.execute(
            select(combat_entries)
            .where(
                combat_entries.c.id == entry_id,
                combat_entries.c.combat_id == combat_id,
            )
            .with_for_update()
        ).mappings().one_or_none()
        target = None
        if target_entry_id is not None:
            target = connection.execute(
                select(combat_entries)
                .where(
                    combat_entries.c.id == target_entry_id,
                    combat_entries.c.combat_id == combat_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
        for extra_id in extra_entry_ids:
            extra = connection.execute(
                select(combat_entries)
                .where(
                    combat_entries.c.id == extra_id,
                    combat_entries.c.combat_id == combat_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if extra is None or extra["status"] != "active":
                raise CombatAdjudicationStateConflictError("Active combat entry required")
        if combat is None or subject is None or (target_entry_id is not None and target is None):
            raise CombatAdjudicationNotFoundError(str(combat_id))
        if (
            combat["status"] != "running"
            or subject["status"] != "active"
            or (target is not None and target["status"] != "active")
        ):
            raise CombatAdjudicationStateConflictError(
                "Adjudication requires active combatant(s) in a running Combat"
            )
        now = datetime.now().astimezone()
        connection.execute(
            insert(combat_actions).values(
                id=action_id,
                combat_id=combat_id,
                entry_id=entry_id,
                target_entry_id=target_entry_id,
                session_id=binding.session_id,
                acting_seat_id=binding.seat_id,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                action_kind=action_kind,
                economy_cost="none",
                payload=payload,
                resolution_status="dm_adjudication_required",
                idempotency_key=idempotency_key,
            )
        )
        connection.execute(
            update(combats)
            .where(combats.c.id == combat_id)
            .values(revision=combats.c.revision + 1, updated_at=now)
        )
        proj_payload = dict(event_payload)
        if target is not None and action_kind == "opportunity_attack":
            proj_payload["target_is_hostile"] = bool(target["is_hostile"])
        connection.execute(
            update(session_events)
            .where(session_events.c.id == event_id)
            .values(subject_character_id=subject["character_id"], payload=proj_payload)
        )

    def request_opportunity_attack_adjudication(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        reactor_entry_id: UUID,
        mover_entry_id: UUID,
        subject_seat_id: UUID | None,
        execution_mode: str,
        question: str | None,
        idempotency_key: str | None,
    ) -> tuple[StoredCombatAction, StoredTableEvent]:
        action_id = uuid4()
        payload = {
            "adjudication": {"kind": "opportunity_attack", "trigger": None},
            "question": question,
        }
        event_payload = {
            "combat_id": str(combat_id),
            "combat_action_id": str(action_id),
            "attacker_entry_id": str(reactor_entry_id),
            "target_entry_id": str(mover_entry_id),
            "kind": "opportunity_attack",
            "status": "dm_adjudication_required",
            "question": question,
        }

        def projection(connection, event_id: UUID, _seq: int) -> None:
            self._insert_pending_adjudication(
                connection,
                binding=binding,
                combat_id=combat_id,
                action_id=action_id,
                entry_id=reactor_entry_id,
                target_entry_id=mover_entry_id,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                action_kind="opportunity_attack",
                payload=payload,
                event_id=event_id,
                event_payload=event_payload,
                idempotency_key=idempotency_key,
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
            payload=event_payload,
            idempotency_key=(
                f"p4e-oa-adjudication:{idempotency_key}"
                if idempotency_key
                else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get_action(
            session_id=binding.session_id,
            action_id=UUID(str(event.payload["combat_action_id"])),
        )
        if stored is None:
            raise CombatAdjudicationNotFoundError(str(action_id))
        return stored, event

    def request_special_adjudication(
        self,
        *,
        binding: StoredTableActorBinding,
        combat_id: UUID,
        subject_entry_id: UUID,
        target_entry_ids: tuple[UUID, ...],
        subject_seat_id: UUID | None,
        execution_mode: str,
        question: str,
        idempotency_key: str | None,
    ) -> tuple[StoredCombatAction, StoredTableEvent]:
        action_id = uuid4()
        first_target = target_entry_ids[0] if target_entry_ids else None
        payload = {
            "adjudication": {"kind": "special"},
            "question": question,
            "proposed_target_entry_ids": [str(t) for t in target_entry_ids],
        }
        event_payload = {
            "combat_id": str(combat_id),
            "combat_action_id": str(action_id),
            "attacker_entry_id": str(subject_entry_id),
            "target_entry_id": str(first_target) if first_target else None,
            "kind": "special",
            "status": "dm_adjudication_required",
            "question": question,
            "proposed_target_entry_ids": [str(t) for t in target_entry_ids],
        }

        def projection(connection, event_id: UUID, _seq: int) -> None:
            self._insert_pending_adjudication(
                connection,
                binding=binding,
                combat_id=combat_id,
                action_id=action_id,
                entry_id=subject_entry_id,
                target_entry_id=first_target,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                action_kind="special_adjudication",
                payload=payload,
                event_id=event_id,
                event_payload=event_payload,
                idempotency_key=idempotency_key,
                extra_entry_ids=tuple(target_entry_ids[1:]),
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
            payload=event_payload,
            idempotency_key=(
                f"p4e-special-adjudication:{idempotency_key}"
                if idempotency_key
                else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get_action(
            session_id=binding.session_id,
            action_id=UUID(str(event.payload["combat_action_id"])),
        )
        if stored is None:
            raise CombatAdjudicationNotFoundError(str(action_id))
        return stored, event

    def resolve_adjudication(
        self,
        *,
        binding: StoredTableActorBinding,
        action_id: UUID,
        trigger: bool | None,
        ruling: str | None,
        idempotency_key: str | None,
    ) -> tuple[StoredCombatAction, StoredTableEvent]:
        existing = self.get_action(session_id=binding.session_id, action_id=action_id)
        if existing is None:
            raise CombatAdjudicationNotFoundError(str(action_id))
        if existing.resolution_status != "dm_adjudication_required":
            raise CombatAdjudicationStateConflictError("Adjudication is not pending")
        action_kind = existing.action_kind
        if action_kind == "attack":
            raise CombatAdjudicationStateConflictError(
                "Range adjudication must be resolved via POST /attacks/adjudicate"
            )
        if action_kind in ("grapple", "shove"):
            raise CombatAdjudicationStateConflictError(
                "Reach adjudication must be resolved via dedicated special-attack route"
            )
        if action_kind == "spell_aoe":
            raise CombatAdjudicationStateConflictError(
                "AoE adjudication must be resolved via POST /combat/spells/aoe/resolve"
            )
        if action_kind == "opportunity_attack":
            if trigger is None:
                raise ValueError("opportunity_attack adjudication requires trigger boolean")
        elif action_kind == "special_adjudication":
            if not ruling or not ruling.strip():
                raise ValueError("ruling is required for special adjudication")
        else:
            raise CombatAdjudicationStateConflictError(
                f"Unsupported action kind: {action_kind}"
            )

        def projection(connection, event_id: UUID, _seq: int) -> None:
            action = connection.execute(
                select(combat_actions)
                .where(
                    combat_actions.c.id == action_id,
                    combat_actions.c.session_id == binding.session_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if action is None:
                raise CombatAdjudicationNotFoundError(str(action_id))
            if action["resolution_status"] != "dm_adjudication_required":
                raise CombatAdjudicationStateConflictError("Adjudication is not pending")

            combat = connection.execute(
                select(combats)
                .where(
                    combats.c.id == action["combat_id"],
                    combats.c.campaign_id == binding.campaign_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if combat is None or combat["status"] != "running":
                raise CombatAdjudicationStateConflictError(
                    "Combat is missing or not running"
                )

            now = datetime.now().astimezone()
            payload = dict(action["payload"] or {})
            adjudication = dict(payload.get("adjudication") or {})

            if action_kind == "opportunity_attack":
                opened_window_id: str | None = None
                if trigger is True:
                    window_id = f"reaction-{uuid4()}"
                    window = open_opportunity_attack_window(
                        window_id=window_id,
                        entry_id=str(action["entry_id"]),
                        source_entry_id=str(action["target_entry_id"]),
                        target_entry_id=str(action["target_entry_id"]),
                        dm_adjudicated=True,
                        session_ref=str(binding.session_id),
                    )
                    write_reaction_window(
                        connection,
                        binding=binding,
                        combat_id=action["combat_id"],
                        entry_id=action["entry_id"],
                        window=window,
                    )
                    opened_window_id = window_id

                adjudication["trigger"] = trigger
                if ruling is not None:
                    adjudication["ruling"] = ruling
                decision = {"trigger": trigger}
                if ruling is not None:
                    decision["ruling"] = ruling
                res_result: dict[str, Any] = {"trigger": trigger, "ruling": ruling}
                if opened_window_id is not None:
                    res_result["reaction_window_id"] = opened_window_id

                event_payload: dict[str, Any] = {
                    "combat_id": str(action["combat_id"]),
                    "combat_action_id": str(action_id),
                    "kind": "opportunity_attack",
                    "status": "resolved",
                    "decision": decision,
                    "note": ruling,
                }
                if opened_window_id is not None:
                    event_payload["reaction_window_id"] = opened_window_id

            elif action_kind == "special_adjudication":
                adjudication["ruling"] = ruling
                decision = {"ruling": ruling}
                res_result = {"ruling": ruling}
                event_payload = {
                    "combat_id": str(action["combat_id"]),
                    "combat_action_id": str(action_id),
                    "kind": "special",
                    "status": "resolved",
                    "decision": decision,
                    "note": ruling,
                    "question": payload.get("question"),
                }

            payload["adjudication"] = adjudication
            connection.execute(
                update(combat_actions)
                .where(combat_actions.c.id == action_id)
                .values(
                    payload=payload,
                    resolution_status="resolved",
                    resolution_result=res_result,
                )
            )
            connection.execute(
                update(combats)
                .where(combats.c.id == action["combat_id"])
                .values(revision=combats.c.revision + 1, updated_at=now)
            )
            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(payload=event_payload)
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
            payload={
                "combat_action_id": str(action_id),
                "trigger": trigger,
                "ruling": ruling,
            },
            idempotency_key=(
                f"p4e-adjudication-resolve:{idempotency_key}"
                if idempotency_key
                else None
            ),
            expected_actor_binding=binding,
            transaction_projection=projection,
        )
        stored = self.get_action(
            session_id=binding.session_id,
            action_id=UUID(str(event.payload["combat_action_id"])),
        )
        if stored is None:
            raise CombatAdjudicationNotFoundError(str(action_id))
        return stored, event


__all__ = [
    "CombatAdjudicationNotFoundError",
    "CombatAdjudicationRepository",
    "CombatAdjudicationStateConflictError",
    "StoredAttackAdjudication",
]
