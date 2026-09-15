from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.domain.combat.lifecycle import CombatNotFoundError, CombatService
from app.domain.combat.resolution import DamageRollPart, DamageType
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.combat.lifecycle import CombatRepository, StoredCombatEntry, actor_binding
from app.persistence.combat.resolution import (
    CombatResolutionRepository,
    StoredSemanticResolution,
)


class SemanticDamageInput(StrictModel):
    target_entry_id: UUID
    amount: int = Field(ge=0, le=1_000_000)
    damage_type: DamageType = DamageType.UNTYPED
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class SemanticHealingInput(StrictModel):
    target_entry_id: UUID
    amount: int = Field(ge=0, le=1_000_000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class CombatResolutionService:
    """Human/AI shared application boundary for manual combat HP mutations."""

    def __init__(
        self,
        repository: CombatResolutionRepository,
        combat_repository: CombatRepository,
        combat_service: CombatService,
        table_event_service: TableEventService,
    ) -> None:
        self.repository = repository
        self.combat_repository = combat_repository
        self.combat_service = combat_service
        self.table_event_service = table_event_service

    def _active_target(self, actor: TableActorContext, entry_id: UUID) -> StoredCombatEntry:
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        entry = self.combat_repository.get_entry(entry_id)
        if entry is None or entry.combat_id != combat.id or entry.status != "active":
            raise CombatNotFoundError("Combat target is missing or inactive")
        return entry

    def _authorize_manual_target(
        self,
        actor: TableActorContext,
        target: StoredCombatEntry,
    ) -> tuple[UUID | None, str]:
        if target.subject_kind == "monster":
            if not actor.is_current_dm:
                raise TableEventActorUnauthorizedError(
                    "Only the current Session DM can directly mutate Monster HP"
                )
            return None, "self"
        if target.subject_kind != "character" or target.character_id is None:
            raise CombatNotFoundError("Combat target has no supported subject identity")

        subject_seat_id = self.combat_repository.controlling_seat_for_character(
            campaign_id=actor.campaign_id,
            session_id=actor.session_id,
            character_id=target.character_id,
        )
        if actor.is_current_dm:
            return subject_seat_id, "dm_proxy" if subject_seat_id else "self"
        if subject_seat_id is None or subject_seat_id not in actor.controlled_seat_ids:
            raise TableEventActorUnauthorizedError(
                "Player can only apply semantic HP changes to their controlled Character"
            )
        return subject_seat_id, "self"

    def apply_damage(
        self,
        actor: TableActorContext,
        request: SemanticDamageInput,
    ) -> StoredSemanticResolution:
        self.table_event_service.require_actor_current(actor)
        target = self._active_target(actor, request.target_entry_id)
        subject_seat_id, execution_mode = self._authorize_manual_target(actor, target)
        result = self.repository.apply_damage(
            binding=actor_binding(actor),
            combat_id=target.combat_id,
            target_entry_id=target.id,
            damage_parts=(
                DamageRollPart(
                    damage_type=request.damage_type,
                    dice=(),
                    flat_modifier=request.amount,
                ),
            ),
            critical=False,
            source_entry_id=None,
            subject_seat_id=subject_seat_id,
            execution_mode=execution_mode,
            idempotency_key=request.idempotency_key,
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return result

    def apply_healing(
        self,
        actor: TableActorContext,
        request: SemanticHealingInput,
    ) -> StoredSemanticResolution:
        self.table_event_service.require_actor_current(actor)
        target = self._active_target(actor, request.target_entry_id)
        subject_seat_id, execution_mode = self._authorize_manual_target(actor, target)
        result = self.repository.apply_healing(
            binding=actor_binding(actor),
            combat_id=target.combat_id,
            target_entry_id=target.id,
            amount=request.amount,
            source_entry_id=None,
            subject_seat_id=subject_seat_id,
            execution_mode=execution_mode,
            idempotency_key=request.idempotency_key,
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return result


__all__ = [
    "CombatResolutionService",
    "SemanticDamageInput",
    "SemanticHealingInput",
]
