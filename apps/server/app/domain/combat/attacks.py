from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from app.domain.combat.attack_definitions import (
    AttackDefinitionNotFoundError,
    AttackDefinitionResolver,
)
from app.domain.combat.lifecycle import (
    CombatNotFoundError,
    CombatService,
    CombatStateConflictError,
)
from app.domain.combat.resolution import DamageRollPart, RollMode
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource, RollModifierMode, RollService
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.combat.adjudication import (
    CombatAdjudicationRepository,
    CombatAdjudicationStateConflictError,
    StoredAttackAdjudication,
)
from app.persistence.combat.attacks import (
    AttackRequestNotFoundPersistenceError,
    AttackRequestNotPendingPersistenceError,
    AttackRollComputation,
    AttackStateConflictPersistenceError,
    CombatAttackRepository,
    StoredAttackRequest,
    StoredAttackResolution,
)
from app.persistence.combat.lifecycle import CombatRepository, StoredCombatEntry, actor_binding


class AttackRequestInput(StrictModel):
    attacker_entry_id: UUID
    target_entry_id: UUID
    source_ref: str = Field(min_length=1, max_length=320)
    modifier_mode: RollModifierMode = RollModifierMode.NORMAL
    # Quick Combat does not own geometry. Only the current DM may authoritatively
    # set True here; Player/AI Player input remains a durable adjudication request.
    range_confirmed: bool | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class AttackAdjudicationInput(StrictModel):
    action_id: UUID
    in_range: bool
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class AttackDefinitionView(StrictModel):
    source_ref: str
    name: str
    attack_bonus: int
    attack_kind: str
    damage_parts: tuple[dict[str, Any], ...]
    modifier_sources: tuple[dict[str, Any], ...]
    notes: tuple[str, ...]


class AttackRequestView(StrictModel):
    action_id: UUID
    combat_id: UUID
    attacker_entry_id: UUID
    target_entry_id: UUID
    roll_request_id: UUID
    source_ref: str
    name: str
    modifier_mode: str
    attack_bonus: int
    target_ac: int
    status: str


class AttackAdjudicationView(StrictModel):
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


class AttackResolutionView(StrictModel):
    action_id: UUID
    roll_request_id: UUID
    roll_result_id: UUID
    attacker_entry_id: UUID
    target_entry_id: UUID
    hit: bool
    critical: bool
    attack_total: int
    target_ac: int
    damage_total: int
    before_hp: int | None
    after_hp: int | None
    resolution_result: dict[str, Any]


class CombatAttackService:
    """Actor-neutral P4-C attack service shared by Human and AI adapters."""

    def __init__(
        self,
        repository: CombatAttackRepository,
        adjudication_repository: CombatAdjudicationRepository,
        combat_repository: CombatRepository,
        combat_service: CombatService,
        definition_resolver: AttackDefinitionResolver,
        roll_service: RollService,
        table_event_service: TableEventService,
    ) -> None:
        self.repository = repository
        self.adjudication_repository = adjudication_repository
        self.combat_repository = combat_repository
        self.combat_service = combat_service
        self.definition_resolver = definition_resolver
        self.roll_service = roll_service
        self.table_event_service = table_event_service

    @staticmethod
    def _definition_view(attack) -> AttackDefinitionView:
        return AttackDefinitionView(
            source_ref=attack.source_ref,
            name=attack.name,
            attack_bonus=attack.attack_bonus,
            attack_kind=attack.attack_kind.value,
            damage_parts=tuple(
                {
                    "damage_type": part.damage_type.value,
                    "dice_count": part.dice_count,
                    "die_size": part.die_size,
                    "flat_modifier": part.flat_modifier,
                }
                for part in attack.damage_parts
            ),
            modifier_sources=tuple(
                {"source": item.source, "value": item.value}
                for item in attack.modifier_sources
            ),
            notes=attack.notes,
        )

    @staticmethod
    def _request_view(request: StoredAttackRequest) -> AttackRequestView:
        return AttackRequestView(
            action_id=request.action_id,
            combat_id=request.combat_id,
            attacker_entry_id=request.attacker_entry_id,
            target_entry_id=request.target_entry_id,
            roll_request_id=request.roll_request_id,
            source_ref=request.source_ref,
            name=request.name,
            modifier_mode=request.modifier_mode.value,
            attack_bonus=request.attack_bonus,
            target_ac=request.target_ac,
            status=request.status,
        )

    @staticmethod
    def _adjudication_view(item: StoredAttackAdjudication) -> AttackAdjudicationView:
        return AttackAdjudicationView(
            action_id=item.action_id,
            combat_id=item.combat_id,
            attacker_entry_id=item.attacker_entry_id,
            target_entry_id=item.target_entry_id,
            source_ref=item.source_ref,
            name=item.name,
            status=item.status,
            roll_request_id=item.roll_request_id,
            in_range=item.in_range,
            resolution_result=dict(item.resolution_result) if item.resolution_result else None,
        )

    @staticmethod
    def _resolution_view(result: StoredAttackResolution) -> AttackResolutionView:
        return AttackResolutionView(
            action_id=result.action_id,
            roll_request_id=result.roll_request_id,
            roll_result_id=result.roll_result_id,
            attacker_entry_id=result.attacker_entry_id,
            target_entry_id=result.target_entry_id,
            hit=result.hit,
            critical=result.critical,
            attack_total=result.attack_total,
            target_ac=result.target_ac,
            damage_total=result.damage_total,
            before_hp=result.before_hp,
            after_hp=result.after_hp,
            resolution_result=dict(result.resolution_result),
        )

    def _active_entry(self, actor: TableActorContext, entry_id: UUID) -> StoredCombatEntry:
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        entry = self.combat_repository.get_entry(entry_id)
        if entry is None or entry.combat_id != combat.id or entry.status != "active":
            raise CombatNotFoundError("Combat entry is missing or inactive")
        return entry

    def available_attacks(
        self,
        actor: TableActorContext,
        entry_id: UUID,
    ) -> tuple[AttackDefinitionView, ...]:
        self.table_event_service.require_actor_current(actor)
        entry = self._active_entry(actor, entry_id)
        self.combat_service._authorize_entry(actor, entry)
        return tuple(self._definition_view(item) for item in self.definition_resolver.attacks_for(entry))

    def request_attack(
        self,
        actor: TableActorContext,
        request: AttackRequestInput,
    ) -> AttackRequestView | AttackAdjudicationView:
        self.table_event_service.require_actor_current(actor)
        attacker = self._active_entry(actor, request.attacker_entry_id)
        target = self._active_entry(actor, request.target_entry_id)
        if attacker.combat_id != target.combat_id:
            raise CombatStateConflictError("Attacker and target must belong to the same Combat")
        if attacker.id == target.id:
            raise CombatStateConflictError("Attack target must be a different CombatEntry")
        if request.range_confirmed is False:
            raise CombatStateConflictError("Out-of-range Attack is invalid and consumes no action economy")
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, attacker)
        try:
            attack = self.definition_resolver.resolve(attacker, request.source_ref)
            target_ac = self.definition_resolver.armor_class_for(target)
            # Geometry is authoritative only when supplied by the current DM.
            # Player/AI Player assertions never skip the pending adjudication.
            range_is_authoritative = actor.is_current_dm and request.range_confirmed is True
            if not range_is_authoritative:
                stored_adjudication, _event = self.adjudication_repository.request_attack_adjudication(
                    binding=actor_binding(actor),
                    combat_id=attacker.combat_id,
                    attacker_entry_id=attacker.id,
                    target_entry_id=target.id,
                    subject_seat_id=subject_seat_id,
                    execution_mode=execution_mode,
                    attack=attack,
                    target_ac=target_ac,
                    modifier_mode=RollMode(request.modifier_mode.value),
                    idempotency_key=request.idempotency_key,
                )
                result: AttackRequestView | AttackAdjudicationView = self._adjudication_view(stored_adjudication)
            else:
                stored, _event = self.repository.declare_attack(
                    binding=actor_binding(actor),
                    combat_id=attacker.combat_id,
                    attacker_entry_id=attacker.id,
                    target_entry_id=target.id,
                    subject_seat_id=subject_seat_id,
                    execution_mode=execution_mode,
                    attack=attack,
                    target_ac=target_ac,
                    modifier_mode=RollMode(request.modifier_mode.value),
                    idempotency_key=request.idempotency_key,
                )
                result = self._request_view(stored)
        except (AttackStateConflictPersistenceError, CombatAdjudicationStateConflictError) as exc:
            raise CombatStateConflictError(str(exc)) from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return result

    def adjudicate_attack(
        self,
        actor: TableActorContext,
        request: AttackAdjudicationInput,
    ) -> AttackRequestView | AttackAdjudicationView:
        self.table_event_service.require_actor_current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError(
                "Only the current Session DM can adjudicate Quick Combat geometry"
            )
        try:
            stored, _event = self.adjudication_repository.adjudicate_attack_range(
                binding=actor_binding(actor),
                action_id=request.action_id,
                in_range=request.in_range,
                idempotency_key=request.idempotency_key,
            )
        except CombatAdjudicationStateConflictError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        if stored.roll_request_id is None:
            return self._adjudication_view(stored)
        attack_request = self.repository.get_request(
            session_id=actor.session_id,
            roll_request_id=stored.roll_request_id,
        )
        if attack_request is None:
            raise AttackRequestNotFoundPersistenceError(str(stored.roll_request_id))
        return self._request_view(attack_request)

    def complete_attack(
        self,
        actor: TableActorContext,
        request: FormalRollInput,
    ) -> AttackResolutionView:
        self.table_event_service.require_actor_current(actor)
        stored_request = self.repository.get_request(
            session_id=actor.session_id,
            roll_request_id=request.roll_request_id,
        )
        if stored_request is None:
            raise AttackRequestNotFoundPersistenceError(str(request.roll_request_id))
        attacker = self._active_entry(actor, stored_request.attacker_entry_id)
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, attacker)
        if stored_request.subject_seat_id != subject_seat_id and not actor.is_current_dm:
            raise CombatStateConflictError("Attack RollRequest is no longer controlled by this actor")
        acting_seat_id = (
            subject_seat_id
            if execution_mode == "self" and subject_seat_id is not None
            else actor.seat_id
        )

        def roll_factory() -> AttackRollComputation:
            audit = self.roll_service.engine.d20(
                mode=RollModifierMode(stored_request.modifier_mode.value),
                base_modifier=0,
                flat_adjustment=stored_request.attack_bonus,
                physical_raw_dice=(
                    request.raw_dice if request.source is FormalRollSource.PHYSICAL else None
                ),
            )
            return AttackRollComputation(
                source=request.source.value,
                formula=audit.formula,
                raw_dice=audit.raw_dice,
                kept_dice=audit.kept_dice,
                base_modifier=audit.base_modifier,
                flat_adjustment=audit.flat_adjustment,
                total=audit.total,
            )

        def damage_factory(attack, critical: bool) -> tuple[DamageRollPart, ...]:
            parts: list[DamageRollPart] = []
            for formula in attack.damage_parts:
                dice = tuple(
                    self.roll_service.engine.rng.randint(1, formula.die_size)
                    for _ in range(formula.dice_count)
                )
                critical_dice = (
                    tuple(
                        self.roll_service.engine.rng.randint(1, formula.die_size)
                        for _ in range(formula.dice_count)
                    )
                    if critical
                    else ()
                )
                parts.append(
                    DamageRollPart(
                        damage_type=formula.damage_type,
                        dice=dice,
                        flat_modifier=formula.flat_modifier,
                        critical_dice=critical_dice,
                    )
                )
            return tuple(parts)

        try:
            result, _event = self.repository.complete_attack(
                binding=actor_binding(actor),
                roll_request_id=request.roll_request_id,
                acting_seat_id=acting_seat_id,
                execution_mode=execution_mode,
                roll_factory=roll_factory,
                damage_factory=damage_factory,
                idempotency_key=request.idempotency_key,
            )
        except AttackStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        except AttackRequestNotPendingPersistenceError:
            current = self.repository.get_resolution(action_id=stored_request.action_id)
            if current is None:
                raise
            result = current
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return self._resolution_view(result)


__all__ = [
    "AttackAdjudicationInput",
    "AttackAdjudicationView",
    "AttackDefinitionNotFoundError",
    "AttackDefinitionView",
    "AttackRequestInput",
    "AttackRequestView",
    "AttackResolutionView",
    "CombatAttackService",
]
