from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from pydantic import Field

from app.domain.combat.lifecycle import (
    CombatNotFoundError, CombatService, CombatStateConflictError, ResolveInitiativeOrderInput,
)
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource, RollModifierMode, RollRequestType, RollService
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import TableActorContext, TableEventActorUnauthorizedError, TableEventService
from app.domain.rules.abilities import ability_modifier
from app.persistence.combat.lifecycle import CombatRepository, StoredCombatEntry, actor_binding
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.initiative import (
    CombatInitiativeRepository, InitiativeComputation, InitiativeRequestNotFoundPersistenceError,
    InitiativeRequestNotPendingPersistenceError, NewInitiativeUnit,
)


class InitiativeInputError(ValueError):
    pass


class InitiativeRequestView(StrictModel):
    id: UUID
    roll_group_id: UUID
    target_seat_id: UUID | None
    target_character_id: UUID | None
    target_combat_entry_id: UUID
    request_type: str
    ability_ref: str | None
    modifier_mode: str
    flat_adjustment: int
    status: str
    grouped_entry_ids: tuple[UUID, ...]


class InitiativeRequestResponse(StrictModel):
    roll_group_id: UUID
    requests: tuple[InitiativeRequestView, ...]


class InitiativeRollResponse(StrictModel):
    result_id: UUID
    roll_request_id: UUID
    total: int
    combat_entry_ids: tuple[UUID, ...]


class RequestInitiativeInput(StrictModel):
    entry_ids: tuple[UUID, ...] = ()
    modifier_mode: RollModifierMode = RollModifierMode.NORMAL
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class FinalizeInitiativeInput(StrictModel):
    ordered_entry_ids: tuple[UUID, ...] = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class CombatInitiativeService:
    """P4-B initiative orchestration on top of the existing P3 formal Roll substrate."""

    def __init__(self, repository: CombatInitiativeRepository, combat_repository: CombatRepository,
                 combat_service: CombatService, monster_repository: MonsterRepository,
                 roll_service: RollService, table_event_service: TableEventService) -> None:
        self.repository = repository
        self.combat_repository = combat_repository
        self.combat_service = combat_service
        self.monster_repository = monster_repository
        self.roll_service = roll_service
        self.table_event_service = table_event_service

    def _require_dm(self, actor: TableActorContext) -> None:
        self.table_event_service.require_actor_current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError("Only the current Session DM can request/finalize Combat initiative")

    def _active_entries(self, actor: TableActorContext, requested_ids: tuple[UUID, ...]) -> tuple[StoredCombatEntry, ...]:
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        entries = tuple(entry for entry in self.combat_repository.list_entries(combat.id) if entry.status == "active")
        if requested_ids:
            if len(requested_ids) != len(set(requested_ids)):
                raise InitiativeInputError("entry_ids must be unique")
            by_id = {entry.id: entry for entry in entries}
            if any(entry_id not in by_id for entry_id in requested_ids):
                raise CombatNotFoundError("One or more initiative CombatEntry targets were not found")
            entries = tuple(by_id[entry_id] for entry_id in requested_ids)
        unresolved = tuple(entry for entry in entries if entry.initiative_roll_request_id is None and entry.initiative_total is None)
        if not unresolved:
            raise CombatStateConflictError("All selected CombatEntries already have initiative")
        return unresolved

    def _character_unit(self, actor: TableActorContext, entry: StoredCombatEntry) -> NewInitiativeUnit:
        if entry.character_id is None:
            raise CombatStateConflictError("Character CombatEntry has no Character identity")
        seat_id = self.combat_repository.controlling_seat_for_character(
            campaign_id=actor.campaign_id, session_id=actor.session_id, character_id=entry.character_id,
        )
        if seat_id is None:
            raise CombatStateConflictError("Character must be an active participant in the current Session before initiative can be requested")
        return NewInitiativeUnit(
            representative_entry_id=entry.id, entry_ids=(entry.id,), target_seat_id=seat_id,
            target_character_id=entry.character_id, request_type=RollRequestType.ABILITY.value,
            ability_ref="dexterity", flat_adjustment=0,
        )

    def _monster_unit(self, entry_group: tuple[StoredCombatEntry, ...]) -> NewInitiativeUnit:
        representative = entry_group[0]
        if representative.monster_instance_id is None:
            raise CombatStateConflictError("Monster CombatEntry has no Monster Instance identity")
        monster = self.monster_repository.get_instance(representative.monster_instance_id)
        if monster is None:
            raise CombatNotFoundError("Monster Instance was not found")
        scores = monster.rules_snapshot.get("ability_scores", {})
        dexterity = scores.get("dexterity", 10) if isinstance(scores, dict) else 10
        if not isinstance(dexterity, int):
            dexterity = 10
        return NewInitiativeUnit(
            representative_entry_id=representative.id, entry_ids=tuple(entry.id for entry in entry_group),
            target_seat_id=None, target_character_id=None, request_type=RollRequestType.OTHER.value,
            ability_ref=None, flat_adjustment=ability_modifier(dexterity),
        )

    def request_initiative(self, actor: TableActorContext, request: RequestInitiativeInput) -> InitiativeRequestResponse:
        self._require_dm(actor)
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        entries = self._active_entries(actor, request.entry_ids)
        units: list[NewInitiativeUnit] = []
        monster_groups: dict[str, list[StoredCombatEntry]] = defaultdict(list)
        individual_monsters: list[StoredCombatEntry] = []
        for entry in entries:
            if entry.subject_kind == "character":
                units.append(self._character_unit(actor, entry))
            elif entry.subject_kind == "monster":
                if entry.initiative_group_key:
                    monster_groups[entry.initiative_group_key].append(entry)
                else:
                    individual_monsters.append(entry)
            else:
                raise CombatStateConflictError(f"unsupported CombatEntry kind: {entry.subject_kind}")
        for entry in individual_monsters:
            units.append(self._monster_unit((entry,)))
        for key in sorted(monster_groups):
            units.append(self._monster_unit(tuple(monster_groups[key])))
        group_id, stored, _event = self.repository.create_requests(
            binding=actor_binding(actor), combat_id=combat.id, units=tuple(units),
            modifier_mode=request.modifier_mode.value, idempotency_key=request.idempotency_key,
        )
        views = tuple(InitiativeRequestView(
            id=item.id, roll_group_id=group_id, target_seat_id=item.target_seat_id,
            target_character_id=item.target_character_id, target_combat_entry_id=item.target_combat_entry_id,
            request_type=item.request_type, ability_ref=item.ability_ref, modifier_mode=item.modifier_mode,
            flat_adjustment=item.flat_adjustment, status=item.status,
            grouped_entry_ids=tuple(entry.id for entry in self.combat_repository.entries_for_initiative_request(combat.id, item.id)),
        ) for item in stored)
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return InitiativeRequestResponse(roll_group_id=group_id, requests=views)

    def _authorize_roll(self, actor: TableActorContext, request) -> tuple[UUID, str]:
        if request.target_seat_id is None:
            if not actor.is_current_dm:
                raise TableEventActorUnauthorizedError("Only the current Session DM can roll Monster initiative")
            return actor.seat_id, "self"
        if request.target_seat_id in actor.controlled_seat_ids:
            return request.target_seat_id, "self"
        if actor.is_current_dm:
            return actor.seat_id, "dm_proxy"
        raise TableEventActorUnauthorizedError("Actor cannot complete this initiative RollRequest")

    def complete_initiative(self, actor: TableActorContext, input: FormalRollInput) -> InitiativeRollResponse:
        self.table_event_service.require_actor_current(actor)
        request = self.repository.get_request(session_id=actor.session_id, request_id=input.roll_request_id)
        if request is None:
            raise CombatNotFoundError("Initiative RollRequest was not found in this Session")
        acting_seat_id, execution_mode = self._authorize_roll(actor, request)
        base_modifier = 0
        if request.target_character_id is not None:
            base_modifier = self.roll_service.modifier_resolver.modifier_for(
                character_id=request.target_character_id, request_type=RollRequestType.ABILITY,
                ability_ref="dexterity", skill_ref=None,
            )
        def compute_result() -> InitiativeComputation:
            audit = self.roll_service.engine.d20(
                mode=RollModifierMode(request.modifier_mode), base_modifier=base_modifier,
                flat_adjustment=request.flat_adjustment,
                physical_raw_dice=input.raw_dice if input.source is FormalRollSource.PHYSICAL else None,
            )
            return InitiativeComputation(
                source=input.source.value, formula=audit.formula, raw_dice=audit.raw_dice,
                kept_dice=audit.kept_dice, base_modifier=audit.base_modifier,
                flat_adjustment=audit.flat_adjustment, total=audit.total,
            )
        try:
            result_id, total, entry_ids, _event = self.repository.complete_request(
                binding=actor_binding(actor), request_id=request.id, acting_seat_id=acting_seat_id,
                execution_mode=execution_mode, result_factory=compute_result, idempotency_key=input.idempotency_key,
            )
        except InitiativeRequestNotFoundPersistenceError as exc:
            raise CombatNotFoundError(str(request.id)) from exc
        except InitiativeRequestNotPendingPersistenceError as exc:
            raise CombatStateConflictError("Initiative RollRequest is already resolved") from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return InitiativeRollResponse(
            result_id=result_id, roll_request_id=request.id, total=total, combat_entry_ids=entry_ids,
        )

    def suggested_order(self, actor: TableActorContext) -> tuple[UUID, ...]:
        self.table_event_service.require_actor_current(actor)
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        entries = tuple(entry for entry in self.combat_repository.list_entries(combat.id) if entry.status == "active")
        if not entries or any(entry.initiative_total is None for entry in entries):
            raise CombatStateConflictError("Every active CombatEntry must resolve initiative first")
        return tuple(entry.id for entry in sorted(
            entries, key=lambda item: (-int(item.initiative_total or 0), item.initiative_group_key or "", str(item.id))
        ))

    def tied_totals(self, actor: TableActorContext) -> dict[int, tuple[UUID, ...]]:
        self.table_event_service.require_actor_current(actor)
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        groups: dict[int, list[StoredCombatEntry]] = defaultdict(list)
        for entry in self.combat_repository.list_entries(combat.id):
            if entry.status == "active" and entry.initiative_total is not None:
                groups[int(entry.initiative_total)].append(entry)
        result: dict[int, tuple[UUID, ...]] = {}
        for total, entries in groups.items():
            request_ids = {entry.initiative_roll_request_id for entry in entries}
            if len(entries) > 1 and len(request_ids) > 1:
                result[total] = tuple(entry.id for entry in entries)
        return result

    def finalize_initiative(self, actor: TableActorContext, request: FinalizeInitiativeInput):
        self._require_dm(actor)
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        if combat.status != "initiative_pending":
            raise CombatStateConflictError("Initial initiative can only be finalized before Round 1")
        return self.combat_service.resolve_initiative_order(
            actor, ResolveInitiativeOrderInput(
                ordered_entry_ids=request.ordered_entry_ids, idempotency_key=request.idempotency_key,
            ),
        )


__all__ = [
    "CombatInitiativeService", "FinalizeInitiativeInput", "InitiativeInputError",
    "InitiativeRequestResponse", "InitiativeRequestView", "InitiativeRollResponse", "RequestInitiativeInput",
]
