from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from app.domain.combat.lifecycle import (
    CombatNotFoundError,
    CombatService,
    CombatStateConflictError,
    CombatView,
)
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.combat.lifecycle import (
    CombatNotFoundPersistenceError,
    CombatStateConflictPersistenceError,
    actor_binding,
)
from app.persistence.combat.order import CombatOrderRepository


class ReorderInitiativeInput(StrictModel):
    ordered_entry_ids: tuple[UUID, ...] = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_unique_entries(self) -> ReorderInitiativeInput:
        if len(self.ordered_entry_ids) != len(set(self.ordered_entry_ids)):
            raise ValueError("ordered_entry_ids must be unique")
        return self


class CombatOrderService:
    def __init__(
        self,
        repository: CombatOrderRepository,
        combat_service: CombatService,
        table_event_service: TableEventService,
    ) -> None:
        self.repository = repository
        self.combat_service = combat_service
        self.table_event_service = table_event_service

    def _validate_order_preserves_totals(
        self,
        combat_id: UUID,
        ordered_entry_ids: tuple[UUID, ...],
    ) -> None:
        entries = tuple(
            entry
            for entry in self.combat_service.repository.list_entries(combat_id)
            if entry.status == "active"
        )
        by_id = {entry.id: entry for entry in entries}
        if set(ordered_entry_ids) != set(by_id) or len(ordered_entry_ids) != len(by_id):
            raise CombatStateConflictError(
                "initiative order must contain every active Combat entry exactly once"
            )
        if any(entry.initiative_total is None for entry in entries):
            raise CombatStateConflictError(
                "all active entries require initiative before reordering"
            )
        totals = [int(by_id[entry_id].initiative_total or 0) for entry_id in ordered_entry_ids]
        if any(left < right for left, right in zip(totals, totals[1:])):
            raise CombatStateConflictError(
                "initiative order may only change ordering among tied totals"
            )

    def reorder_running(
        self,
        actor: TableActorContext,
        request: ReorderInitiativeInput,
    ) -> CombatView:
        self.table_event_service.require_actor_current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError(
                "Only the current Session DM can reorder Combat initiative"
            )
        combat = self.combat_service.repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        self._validate_order_preserves_totals(combat.id, request.ordered_entry_ids)
        try:
            self.repository.reorder_running(
                binding=actor_binding(actor),
                combat_id=combat.id,
                ordered_entry_ids=request.ordered_entry_ids,
                idempotency_key=request.idempotency_key,
            )
        except CombatNotFoundPersistenceError as exc:
            raise CombatNotFoundError(str(combat.id)) from exc
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        refreshed = self.combat_service.get_active_combat(actor)
        if refreshed is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        return refreshed


__all__ = ["CombatOrderService", "ReorderInitiativeInput"]
