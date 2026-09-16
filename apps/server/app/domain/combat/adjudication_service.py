from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.domain.combat.lifecycle import (
    CombatNotFoundError,
    CombatService,
    CombatStateConflictError,
)
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.combat.adjudication import (
    CombatAdjudicationRepository,
    CombatAdjudicationStateConflictError,
)
from app.persistence.combat.lifecycle import (
    CombatRepository,
    StoredCombatAction,
    StoredCombatEntry,
    actor_binding,
)


class CombatAdjudicationView(StrictModel):
    action_id: UUID
    kind: Literal["range", "reach", "affected_targets", "opportunity_attack", "special"]
    status: Literal["pending", "resolved", "cancelled"]
    subject_entry_id: UUID
    subject_seat_id: UUID | None
    proposed_target_entry_ids: tuple[UUID, ...]
    question: str | None = None
    decision: dict[str, Any] | None = None
    note: str | None = None
    dm_hints: dict[str, Any] | None = None
    created_at: datetime


class OpportunityAttackRequestInput(StrictModel):
    mover_entry_id: UUID
    reactor_entry_id: UUID
    question: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class SpecialAdjudicationRequestInput(StrictModel):
    subject_entry_id: UUID
    target_entry_ids: tuple[UUID, ...] = ()
    question: str = Field(min_length=1, max_length=500)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class AdjudicationDecisionInput(StrictModel):
    trigger: bool | None = None
    ruling: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


def row_to_adjudication_view(action: StoredCombatAction, *, is_dm: bool) -> CombatAdjudicationView:
    payload = action.payload
    adjudication = payload.get("adjudication") or {}
    action_kind = action.action_kind
    resolution_status = action.resolution_status

    if resolution_status == "dm_adjudication_required":
        status: Literal["pending", "resolved", "cancelled"] = "pending"
    elif resolution_status == "cancelled":
        status = "cancelled"
    else:
        status = "resolved"

    subject_entry_id = action.entry_id
    subject_seat_id = action.subject_seat_id
    target_entry_id = action.target_entry_id

    question: str | None = None
    note: str | None = None
    decision: dict[str, Any] | None = None
    dm_hints: dict[str, Any] | None = None
    proposed_target_entry_ids: tuple[UUID, ...] = ()

    if action_kind == "attack":
        kind: Literal["range", "reach", "affected_targets", "opportunity_attack", "special"] = "range"
        if target_entry_id is not None:
            proposed_target_entry_ids = (target_entry_id,)
        note = adjudication.get("note")
        if adjudication.get("in_range") is not None or "roll_mode" in adjudication:
            decision = {"in_range": adjudication.get("in_range")}
            if "roll_mode" in adjudication:
                decision["roll_mode"] = adjudication["roll_mode"]
            if note is not None:
                decision["note"] = note
        if is_dm:
            dm_hints = {
                "target_ac": payload.get("target_ac"),
                "resolved_attack": payload.get("resolved_attack"),
            }

    elif action_kind in ("grapple", "shove"):
        kind = "reach"
        if target_entry_id is not None:
            proposed_target_entry_ids = (target_entry_id,)
        if adjudication.get("in_reach") is not None:
            decision = {"in_reach": adjudication.get("in_reach")}
        if is_dm:
            dm_hints = {
                "attacker_size": payload.get("attacker_size"),
                "target_size": payload.get("target_size"),
                "attacker_has_free_hand": payload.get("attacker_has_free_hand"),
                "attacker_skill": payload.get("attacker_skill"),
                "defender_skill": payload.get("defender_skill"),
            }

    elif action_kind == "spell_aoe":
        kind = "affected_targets"
        proposed = adjudication.get("proposed_target_ids") or payload.get("proposed_target_ids") or ()
        proposed_target_entry_ids = tuple(
            t if isinstance(t, UUID) else UUID(str(t)) for t in proposed
        )
        if adjudication.get("confirmed_target_ids"):
            decision = {"confirmed_target_ids": list(adjudication["confirmed_target_ids"])}

    elif action_kind == "opportunity_attack":
        kind = "opportunity_attack"
        if target_entry_id is not None:
            proposed_target_entry_ids = (target_entry_id,)
        question = payload.get("question")
        if adjudication.get("trigger") is not None:
            decision = {"trigger": adjudication["trigger"]}
            if "ruling" in adjudication:
                decision["ruling"] = adjudication["ruling"]
        note = adjudication.get("ruling") or adjudication.get("note")

    elif action_kind == "special_adjudication":
        kind = "special"
        proposed = payload.get("proposed_target_entry_ids") or ()
        proposed_target_entry_ids = tuple(
            t if isinstance(t, UUID) else UUID(str(t)) for t in proposed
        )
        question = payload.get("question")
        if adjudication.get("ruling") is not None:
            decision = {"ruling": adjudication["ruling"]}
        note = adjudication.get("ruling") or adjudication.get("note")

    else:
        raise CombatAdjudicationStateConflictError(
            f"Unsupported adjudication action kind: {action_kind}"
        )

    return CombatAdjudicationView(
        action_id=action.id,
        kind=kind,
        status=status,
        subject_entry_id=subject_entry_id,
        subject_seat_id=subject_seat_id,
        proposed_target_entry_ids=proposed_target_entry_ids,
        question=question,
        decision=decision,
        note=note,
        dm_hints=dm_hints if is_dm else None,
        created_at=action.created_at,
    )


class CombatAdjudicationService:
    """Unified Combat Adjudication service shared by REST and MCP."""

    def __init__(
        self,
        repository: CombatAdjudicationRepository,
        combat_repository: CombatRepository,
        combat_service: CombatService,
        table_event_service: TableEventService,
    ) -> None:
        self.repository = repository
        self.combat_repository = combat_repository
        self.combat_service = combat_service
        self.table_event_service = table_event_service

    def list_pending(self, actor: TableActorContext) -> tuple[CombatAdjudicationView, ...]:
        self.table_event_service.require_actor_current(actor)
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            return ()
        rows = self.repository.list_pending(combat_id=combat.id)
        views: list[CombatAdjudicationView] = []
        for row in rows:
            if not actor.is_current_dm:
                if row.subject_seat_id != actor.seat_id:
                    continue
            views.append(row_to_adjudication_view(row, is_dm=actor.is_current_dm))
        return tuple(views)

    def _authorize_opportunity_attack(
        self,
        actor: TableActorContext,
        reactor: StoredCombatEntry,
        mover: StoredCombatEntry,
    ) -> tuple[UUID | None, str]:
        if actor.is_current_dm:
            return self.combat_service._authorize_entry(actor, reactor)

        reactor_seat_id: UUID | None = None
        if reactor.character_id is not None:
            reactor_seat_id = self.combat_repository.controlling_seat_for_character(
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
                character_id=reactor.character_id,
            )

        mover_seat_id: UUID | None = None
        if mover.character_id is not None:
            mover_seat_id = self.combat_repository.controlling_seat_for_character(
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
                character_id=mover.character_id,
            )

        reactor_controlled = (
            reactor_seat_id is not None and reactor_seat_id in actor.controlled_seat_ids
        )
        mover_controlled = (
            mover_seat_id is not None and mover_seat_id in actor.controlled_seat_ids
        )

        if not reactor_controlled and not mover_controlled:
            raise TableEventActorUnauthorizedError(
                "Player must control either the reactor or the mover entry"
            )

        return reactor_seat_id, "self"

    def request_opportunity_attack(
        self,
        actor: TableActorContext,
        request: OpportunityAttackRequestInput,
    ) -> CombatAdjudicationView:
        self.table_event_service.require_actor_current(actor)
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatStateConflictError("Campaign has no active Combat")
        reactor = self.combat_repository.get_entry(request.reactor_entry_id)
        mover = self.combat_repository.get_entry(request.mover_entry_id)
        if reactor is None or reactor.combat_id != combat.id or reactor.status != "active":
            raise CombatNotFoundError("Reactor combat entry is missing or inactive")
        if mover is None or mover.combat_id != combat.id or mover.status != "active":
            raise CombatNotFoundError("Mover combat entry is missing or inactive")
        if reactor.id == mover.id:
            raise CombatStateConflictError("Reactor and mover must be different combat entries")

        subject_seat_id, execution_mode = self._authorize_opportunity_attack(
            actor, reactor, mover
        )

        try:
            row, _event = self.repository.request_opportunity_attack_adjudication(
                binding=actor_binding(actor),
                combat_id=combat.id,
                reactor_entry_id=reactor.id,
                mover_entry_id=mover.id,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                question=request.question,
                idempotency_key=request.idempotency_key,
            )
        except CombatAdjudicationStateConflictError as exc:
            raise CombatStateConflictError(str(exc)) from exc

        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return row_to_adjudication_view(row, is_dm=actor.is_current_dm)

    def request_special(
        self,
        actor: TableActorContext,
        request: SpecialAdjudicationRequestInput,
    ) -> CombatAdjudicationView:
        self.table_event_service.require_actor_current(actor)
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatStateConflictError("Campaign has no active Combat")
        subject = self.combat_repository.get_entry(request.subject_entry_id)
        if subject is None or subject.combat_id != combat.id or subject.status != "active":
            raise CombatNotFoundError("Subject combat entry is missing or inactive")

        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, subject)

        try:
            row, _event = self.repository.request_special_adjudication(
                binding=actor_binding(actor),
                combat_id=combat.id,
                subject_entry_id=subject.id,
                target_entry_ids=request.target_entry_ids,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                question=request.question,
                idempotency_key=request.idempotency_key,
            )
        except CombatAdjudicationStateConflictError as exc:
            raise CombatStateConflictError(str(exc)) from exc

        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return row_to_adjudication_view(row, is_dm=actor.is_current_dm)

    def resolve_adjudication(
        self,
        actor: TableActorContext,
        action_id: UUID,
        request: AdjudicationDecisionInput,
    ) -> CombatAdjudicationView:
        self.table_event_service.require_actor_current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError(
                "Only the current Session DM can resolve combat adjudications"
            )
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatStateConflictError("Campaign has no active Combat")

        row, _event = self.repository.resolve_adjudication(
            binding=actor_binding(actor),
            action_id=action_id,
            trigger=request.trigger,
            ruling=request.ruling,
            idempotency_key=request.idempotency_key,
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return row_to_adjudication_view(row, is_dm=True)


__all__ = [
    "AdjudicationDecisionInput",
    "CombatAdjudicationService",
    "CombatAdjudicationView",
    "OpportunityAttackRequestInput",
    "SpecialAdjudicationRequestInput",
    "row_to_adjudication_view",
]
