from __future__ import annotations

from uuid import UUID

from pydantic import Field, field_validator

from app.domain.combat.concentration import CombatConcentrationService
from app.domain.combat.concentration_triggers import monster_save_modifier
from app.domain.combat.lifecycle import CombatNotFoundError, CombatService, CombatStateConflictError
from app.domain.rooms.rolls import (
    FormalRollInput,
    FormalRollSource,
    RollModifierMode,
    RollRequestType,
    RollService,
    RollVisibility,
)
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.domain.rules.abilities import ability_modifier, normalize_ability_name
from app.persistence.combat.core_rolls import (
    CombatCoreRollNotFoundError,
    CombatCoreRollRepository,
    CombatCoreRollStateConflictError,
    CoreRollComputation,
    NewSavingThrowUnit,
    StoredCombatCoreRollRequest,
    StoredDeathSaveResult,
    StoredSavingThrowResult,
)
from app.persistence.combat.lifecycle import CombatRepository, StoredCombatEntry, actor_binding
from app.persistence.combat.repository import MonsterRepository


class SavingThrowInput(StrictModel):
    target_entry_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)
    ability_ref: str = Field(min_length=1, max_length=80)
    dc: int = Field(ge=0, le=999)
    modifier_mode: RollModifierMode = RollModifierMode.NORMAL
    visibility: RollVisibility = RollVisibility.PUBLIC
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("target_entry_ids")
    @classmethod
    def target_ids_are_unique(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("target_entry_ids must be unique")
        return value


class SavingThrowRequestView(StrictModel):
    id: UUID
    roll_group_id: UUID | None
    target_entry_id: UUID
    target_seat_id: UUID | None
    target_character_id: UUID | None
    ability_ref: str
    dc: int | None
    modifier: int
    modifier_mode: RollModifierMode
    visibility: RollVisibility
    status: str


class CombatPendingRollView(StrictModel):
    """Compact pending Combat roll for get_combat_context; ``dc`` is DM-only."""

    id: UUID
    roll_group_id: UUID | None
    label: str | None
    request_type: str
    target_entry_id: UUID
    target_seat_id: UUID | None
    ability_ref: str | None
    dc: int | None
    modifier_mode: RollModifierMode
    status: str


class SavingThrowRequestResponse(StrictModel):
    roll_group_id: UUID
    requests: tuple[SavingThrowRequestView, ...]


class SavingThrowResultView(StrictModel):
    result_id: UUID
    roll_request_id: UUID
    target_entry_id: UUID
    total: int
    succeeded: bool


class DeathSaveRequestInput(StrictModel):
    entry_id: UUID
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class DeathSaveRequestView(StrictModel):
    combat_action_id: UUID
    roll_request_id: UUID
    entry_id: UUID
    status: str = "waiting_for_roll"


class DeathSaveResultView(StrictModel):
    combat_action_id: UUID
    result_id: UUID
    roll_request_id: UUID
    entry_id: UUID
    d20: int
    current_hp: int
    successes: int
    failures: int
    stable: bool
    dead: bool
    natural_20_recovery: bool


def _request_event_visibility(visibility: RollVisibility) -> str:
    if visibility is RollVisibility.PUBLIC:
        return "public"
    if visibility is RollVisibility.DM_ONLY:
        return "dm_only"
    return "seat_private"


class CombatCoreRollService:
    """Actor-neutral formal Saving Throw and Death Save application service."""

    def __init__(
        self,
        repository: CombatCoreRollRepository,
        combat_repository: CombatRepository,
        combat_service: CombatService,
        monster_repository: MonsterRepository,
        roll_service: RollService,
        table_event_service: TableEventService,
        concentration_service: CombatConcentrationService | None = None,
    ) -> None:
        self.repository = repository
        self.combat_repository = combat_repository
        self.combat_service = combat_service
        self.monster_repository = monster_repository
        self.roll_service = roll_service
        self.table_event_service = table_event_service
        self.concentration_service = concentration_service

    def _active_entry(self, actor: TableActorContext, entry_id: UUID) -> StoredCombatEntry:
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        entry = self.combat_repository.get_entry(entry_id)
        if entry is None or entry.combat_id != combat.id or entry.status != "active":
            raise CombatNotFoundError("CombatEntry is missing or inactive")
        return entry

    @staticmethod
    def _monster_save_modifier(rules: dict, ability: str) -> int:
        return monster_save_modifier(rules, ability)

    @staticmethod
    def _is_concentration_request(request: StoredCombatCoreRollRequest) -> bool:
        return (
            request.roll_group_label == "Concentration"
            and request.request_type == "saving_throw"
            and request.ability_ref in {"srd5.1:ability:constitution", "constitution"}
        )

    def _save_unit(self, actor: TableActorContext, entry: StoredCombatEntry, ability: str) -> NewSavingThrowUnit:
        if entry.subject_kind == "character":
            if entry.character_id is None:
                raise CombatStateConflictError("Character CombatEntry has no Character identity")
            seat_id = self.combat_repository.controlling_seat_for_character(
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
                character_id=entry.character_id,
            )
            modifier = self.roll_service.modifier_resolver.modifier_for(
                character_id=entry.character_id,
                request_type=RollRequestType.SAVING_THROW,
                ability_ref=ability,
                skill_ref=None,
            )
            return NewSavingThrowUnit(
                target_entry_id=entry.id,
                target_seat_id=seat_id,
                target_character_id=entry.character_id,
                modifier=modifier,
            )
        if entry.subject_kind == "monster":
            if entry.monster_instance_id is None:
                raise CombatStateConflictError("Monster CombatEntry has no Monster identity")
            monster = self.monster_repository.get_instance(entry.monster_instance_id)
            if monster is None:
                raise CombatNotFoundError("Monster Instance was not found")
            return NewSavingThrowUnit(
                target_entry_id=entry.id,
                target_seat_id=None,
                target_character_id=None,
                modifier=self._monster_save_modifier(monster.rules_snapshot, ability),
            )
        raise CombatStateConflictError(f"unsupported CombatEntry kind: {entry.subject_kind}")

    @staticmethod
    def _save_view(actor: TableActorContext, request: StoredCombatCoreRollRequest) -> SavingThrowRequestView:
        if request.ability_ref is None:
            raise CombatStateConflictError("Saving Throw RollRequest is missing ability_ref")
        return SavingThrowRequestView(
            id=request.id,
            roll_group_id=request.roll_group_id,
            target_entry_id=request.target_combat_entry_id,
            target_seat_id=request.target_seat_id,
            target_character_id=request.target_character_id,
            ability_ref=request.ability_ref,
            dc=request.dc if actor.is_current_dm else None,
            modifier=request.flat_adjustment,
            modifier_mode=RollModifierMode(request.modifier_mode),
            visibility=RollVisibility(request.visibility),
            status=request.status,
        )

    def list_pending_rolls(self, actor: TableActorContext) -> tuple[CombatPendingRollView, ...]:
        """DM sees every pending Combat roll with its DC; a Player only sees rolls that
        target a Seat they control, without the DC (monster save DCs are enemy secrets)."""
        self.table_event_service.require_actor_current(actor)
        views: list[CombatPendingRollView] = []
        for request in self.repository.list_pending_requests(session_id=actor.session_id):
            if not actor.is_current_dm and request.target_seat_id not in actor.controlled_seat_ids:
                continue
            views.append(
                CombatPendingRollView(
                    id=request.id,
                    roll_group_id=request.roll_group_id,
                    label=request.roll_group_label,
                    # Attack rolls are stored as ``other``; the linked Attack action is the discriminator.
                    request_type="attack" if request.action_kind == "attack" else request.request_type,
                    target_entry_id=request.target_combat_entry_id,
                    target_seat_id=request.target_seat_id,
                    ability_ref=request.ability_ref,
                    dc=request.dc if actor.is_current_dm else None,
                    modifier_mode=RollModifierMode(request.modifier_mode),
                    status=request.status,
                )
            )
        return tuple(views)

    def request_saving_throws(
        self,
        actor: TableActorContext,
        request: SavingThrowInput,
    ) -> SavingThrowRequestResponse:
        self.table_event_service.require_actor_current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError("Only the current Session DM can request Combat Saving Throws")
        try:
            ability = normalize_ability_name(request.ability_ref)
        except ValueError as exc:
            raise ValueError(f"invalid saving throw ability: {request.ability_ref}") from exc
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None or combat.status != "running":
            raise CombatNotFoundError("Campaign has no running Combat")
        entries = tuple(self._active_entry(actor, entry_id) for entry_id in request.target_entry_ids)
        units = tuple(self._save_unit(actor, entry, ability) for entry in entries)
        recipients = tuple(
            dict.fromkeys(unit.target_seat_id for unit in units if unit.target_seat_id is not None)
        )
        group_id, stored, _event = self.repository.request_saving_throws(
            binding=actor_binding(actor),
            combat_id=combat.id,
            units=units,
            ability_ref=ability,
            dc=request.dc,
            modifier_mode=request.modifier_mode.value,
            visibility=request.visibility.value,
            event_visibility=_request_event_visibility(request.visibility),
            recipient_seat_ids=recipients,
            idempotency_key=request.idempotency_key,
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return SavingThrowRequestResponse(
            roll_group_id=group_id,
            requests=tuple(self._save_view(actor, item) for item in stored),
        )

    def _authorize_roll(
        self,
        actor: TableActorContext,
        request: StoredCombatCoreRollRequest,
    ) -> tuple[UUID, str]:
        if request.target_seat_id is None:
            if not actor.is_current_dm:
                raise TableEventActorUnauthorizedError("Only the current Session DM can roll for Monster combatants")
            return actor.seat_id, "self"
        if request.target_seat_id in actor.controlled_seat_ids:
            return request.target_seat_id, "self"
        if actor.is_current_dm:
            return actor.seat_id, "dm_proxy"
        raise TableEventActorUnauthorizedError("Actor cannot complete this Combat RollRequest")

    def complete_saving_throw(
        self,
        actor: TableActorContext,
        input: FormalRollInput,
    ) -> SavingThrowResultView:
        self.table_event_service.require_actor_current(actor)
        request = self.repository.get_request(
            session_id=actor.session_id,
            request_id=input.roll_request_id,
        )
        if request is None or request.request_type != "saving_throw":
            raise CombatCoreRollNotFoundError(str(input.roll_request_id))

        if self._is_concentration_request(request):
            if self.concentration_service is not None:
                conc_result = self.concentration_service.complete_check(actor, input)
                return SavingThrowResultView(
                    result_id=conc_result.result_id,
                    roll_request_id=conc_result.roll_request_id,
                    target_entry_id=conc_result.target_entry_id,
                    total=conc_result.total,
                    succeeded=conc_result.succeeded,
                )

        acting_seat_id, execution_mode = self._authorize_roll(actor, request)

        def compute() -> CoreRollComputation:
            audit = self.roll_service.engine.d20(
                mode=RollModifierMode(request.modifier_mode),
                base_modifier=0,
                flat_adjustment=request.flat_adjustment,
                physical_raw_dice=input.raw_dice if input.source is FormalRollSource.PHYSICAL else None,
            )
            return CoreRollComputation(
                source=input.source.value,
                formula=audit.formula,
                raw_dice=audit.raw_dice,
                kept_dice=audit.kept_dice,
                base_modifier=audit.base_modifier,
                flat_adjustment=audit.flat_adjustment,
                total=audit.total,
            )

        stored, _event = self.repository.complete_saving_throw(
            binding=actor_binding(actor),
            request_id=request.id,
            acting_seat_id=acting_seat_id,
            execution_mode=execution_mode,
            result_factory=compute,
            idempotency_key=input.idempotency_key,
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return SavingThrowResultView(
            result_id=stored.result_id,
            roll_request_id=stored.roll_request_id,
            target_entry_id=stored.target_entry_id,
            total=stored.total,
            succeeded=stored.succeeded,
        )

    def request_death_save(
        self,
        actor: TableActorContext,
        request: DeathSaveRequestInput,
    ) -> DeathSaveRequestView:
        self.table_event_service.require_actor_current(actor)
        entry = self._active_entry(actor, request.entry_id)
        if entry.subject_kind != "character" or entry.character_id is None:
            raise CombatStateConflictError("Only Character combatants can make Death Saves")
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, entry)
        action_id, roll_request_id, _event = self.repository.request_death_save(
            binding=actor_binding(actor),
            combat_id=entry.combat_id,
            entry_id=entry.id,
            target_seat_id=subject_seat_id,
            target_character_id=entry.character_id,
            execution_mode=execution_mode,
            idempotency_key=request.idempotency_key,
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return DeathSaveRequestView(
            combat_action_id=action_id,
            roll_request_id=roll_request_id,
            entry_id=entry.id,
        )

    def complete_death_save(
        self,
        actor: TableActorContext,
        input: FormalRollInput,
    ) -> DeathSaveResultView:
        self.table_event_service.require_actor_current(actor)
        request = self.repository.get_request(
            session_id=actor.session_id,
            request_id=input.roll_request_id,
        )
        if request is None or request.request_type != "other":
            raise CombatCoreRollNotFoundError(str(input.roll_request_id))
        entry = self._active_entry(actor, request.target_combat_entry_id)
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, entry)
        acting_seat_id = subject_seat_id if execution_mode == "self" and subject_seat_id else actor.seat_id

        def compute() -> CoreRollComputation:
            audit = self.roll_service.engine.d20(
                mode=RollModifierMode.NORMAL,
                base_modifier=0,
                flat_adjustment=0,
                physical_raw_dice=input.raw_dice if input.source is FormalRollSource.PHYSICAL else None,
            )
            return CoreRollComputation(
                source=input.source.value,
                formula=audit.formula,
                raw_dice=audit.raw_dice,
                kept_dice=audit.kept_dice,
                base_modifier=0,
                flat_adjustment=0,
                total=audit.total,
            )

        stored, _event = self.repository.complete_death_save(
            binding=actor_binding(actor),
            request_id=request.id,
            acting_seat_id=acting_seat_id,
            execution_mode=execution_mode,
            result_factory=compute,
            idempotency_key=input.idempotency_key,
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return self._death_view(stored)

    @staticmethod
    def _death_view(stored: StoredDeathSaveResult) -> DeathSaveResultView:
        return DeathSaveResultView(
            combat_action_id=stored.action_id,
            result_id=stored.result_id,
            roll_request_id=stored.roll_request_id,
            entry_id=stored.target_entry_id,
            d20=stored.d20,
            current_hp=stored.current_hp,
            successes=stored.successes,
            failures=stored.failures,
            stable=stored.stable,
            dead=stored.dead,
            natural_20_recovery=stored.natural_20_recovery,
        )


__all__ = [
    "CombatCoreRollService",
    "DeathSaveRequestInput",
    "DeathSaveRequestView",
    "DeathSaveResultView",
    "SavingThrowInput",
    "SavingThrowRequestResponse",
    "SavingThrowRequestView",
    "SavingThrowResultView",
]
