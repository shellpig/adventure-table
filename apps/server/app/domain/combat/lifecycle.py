from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import TableActorContext, TableEventActorUnauthorizedError, TableEventService
from app.persistence.characters import CharacterRepository
from app.persistence.combat.lifecycle import (
    ActiveCombatExistsPersistenceError, CombatRepository, CombatStateConflictPersistenceError,
    NewCombatEntry, StoredCombat, StoredCombatEntry, actor_binding,
)
from app.persistence.combat.repository import MonsterRepository


class CombatLifecycleError(RuntimeError): pass
class CombatNotFoundError(LookupError): pass
class ActiveCombatExistsError(CombatLifecycleError): pass
class CombatStateConflictError(CombatLifecycleError): pass


class CombatActionKind(StrEnum):
    DASH = "dash"
    DISENGAGE = "disengage"
    DODGE = "dodge"
    SEARCH = "search"
    READY = "ready"
    FREEFORM = "freeform"
    ATTACK_BUDGET = "attack_budget"


class CombatEconomyCost(StrEnum):
    ACTION = "action"
    BONUS_ACTION = "bonus_action"
    REACTION = "reaction"
    NONE = "none"


class StartCombatInput(StrictModel):
    include_active_party: bool = True
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class AddCharacterInput(StrictModel):
    character_id: UUID
    surprised: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class AddMonsterInput(StrictModel):
    monster_instance_id: UUID
    surprised: bool = False
    initiative_group_key: str | None = Field(default=None, max_length=120)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class ResolveInitiativeOrderInput(StrictModel):
    ordered_entry_ids: tuple[UUID, ...] = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)
    @model_validator(mode="after")
    def unique_entries(self):
        if len(self.ordered_entry_ids) != len(set(self.ordered_entry_ids)):
            raise ValueError("ordered_entry_ids must be unique")
        return self


class CombatActionInput(StrictModel):
    entry_id: UUID
    action_kind: CombatActionKind
    economy_cost: CombatEconomyCost = CombatEconomyCost.ACTION
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class ReactionWindowInput(StrictModel):
    entry_id: UUID
    open: bool
    reason: str | None = Field(default=None, max_length=240)
    source_entry_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class CombatEntryView(StrictModel):
    id: UUID
    subject_kind: str
    character_id: UUID | None
    monster_instance_id: UUID | None
    display_name: str
    status: str
    initiative_group_key: str | None
    initiative_roll_request_id: UUID | None
    initiative_roll_result_id: UUID | None
    initiative_total: int | None
    turn_order: int | None
    surprised: bool
    action_available: bool
    bonus_action_available: bool
    reaction_available: bool
    attacks_allowed: int
    attacks_used: int
    ready_state: dict[str, Any]
    pending_reaction_state: dict[str, Any]


class CombatView(StrictModel):
    id: UUID
    campaign_id: UUID
    mode: str
    status: str
    round_number: int | None
    current_turn_entry_id: UUID | None
    revision: int
    entries: tuple[CombatEntryView, ...]


class CombatActionView(StrictModel):
    id: UUID
    combat_id: UUID
    entry_id: UUID
    session_id: UUID
    acting_seat_id: UUID
    subject_seat_id: UUID | None
    execution_mode: str
    action_kind: str
    economy_cost: str
    payload: dict[str, Any]


def _extra_attack_budget(character) -> int:
    progression = Counter(str(ref).rsplit(":", 1)[-1].replace("_", "-").casefold() for ref in character.build.class_progression)
    fighter = progression.get("fighter", 0)
    if fighter >= 20: return 4
    if fighter >= 11: return 3
    if fighter >= 5: return 2
    for class_name in ("barbarian", "monk", "paladin", "ranger"):
        if progression.get(class_name, 0) >= 5: return 2
    if any("extra-attack" in str(ref).replace("_", "-").casefold() for ref in character.build.feature_refs):
        return 2
    return 1


class CombatService:
    """Actor-neutral P4-B application service shared by Human and AI adapters."""
    def __init__(self, repository: CombatRepository, table_event_service: TableEventService,
                 character_repository: CharacterRepository, monster_repository: MonsterRepository) -> None:
        self.repository = repository
        self.table_event_service = table_event_service
        self.character_repository = character_repository
        self.monster_repository = monster_repository

    def _current(self, actor: TableActorContext) -> None:
        self.table_event_service.require_actor_current(actor)

    def _require_dm(self, actor: TableActorContext) -> None:
        self._current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError("Only the current Session DM can perform this Combat operation")

    @staticmethod
    def _entry_view(entry: StoredCombatEntry) -> CombatEntryView:
        return CombatEntryView(
            id=entry.id, subject_kind=entry.subject_kind, character_id=entry.character_id,
            monster_instance_id=entry.monster_instance_id, display_name=entry.display_name,
            status=entry.status, initiative_group_key=entry.initiative_group_key,
            initiative_roll_request_id=entry.initiative_roll_request_id,
            initiative_roll_result_id=entry.initiative_roll_result_id,
            initiative_total=entry.initiative_total, turn_order=entry.turn_order,
            surprised=entry.surprised, action_available=entry.action_available,
            bonus_action_available=entry.bonus_action_available, reaction_available=entry.reaction_available,
            attacks_allowed=entry.attacks_allowed, attacks_used=entry.attacks_used,
            ready_state=dict(entry.ready_state), pending_reaction_state=dict(entry.pending_reaction_state),
        )

    def _view(self, combat: StoredCombat) -> CombatView:
        return CombatView(
            id=combat.id, campaign_id=combat.campaign_id, mode=combat.mode, status=combat.status,
            round_number=combat.round_number, current_turn_entry_id=combat.current_turn_entry_id,
            revision=combat.revision,
            entries=tuple(self._entry_view(entry) for entry in self.repository.list_entries(combat.id)),
        )

    def get_active_combat(self, actor: TableActorContext) -> CombatView | None:
        self._current(actor)
        combat = self.repository.get_active(actor.campaign_id)
        return self._view(combat) if combat is not None else None

    def start_quick_combat(self, actor: TableActorContext, request: StartCombatInput) -> CombatView:
        self._require_dm(actor)
        if self.repository.get_active(actor.campaign_id) is not None:
            raise ActiveCombatExistsError("Campaign already has an active Combat")
        entries: list[NewCombatEntry] = []
        if request.include_active_party:
            for subject in self.repository.session_characters(campaign_id=actor.campaign_id, session_id=actor.session_id):
                character = self.character_repository.load_character(subject.character_id)
                entries.append(NewCombatEntry(
                    subject_kind="character", character_id=subject.character_id,
                    display_name=subject.character_name, attacks_allowed=_extra_attack_budget(character),
                ))
        try:
            combat, _entries, _event = self.repository.create_quick_combat(
                binding=actor_binding(actor), entries=tuple(entries), idempotency_key=request.idempotency_key
            )
        except ActiveCombatExistsPersistenceError as exc:
            raise ActiveCombatExistsError("Campaign already has an active Combat") from exc
        return self._view(combat)

    def add_character(self, actor: TableActorContext, request: AddCharacterInput) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        if self.repository.controlling_seat_for_character(
            campaign_id=actor.campaign_id, session_id=actor.session_id, character_id=request.character_id
        ) is None:
            raise CombatStateConflictError("Character must be an active participant in the current Session before mid-Combat entry")
        character = self.character_repository.load_character(request.character_id)
        try:
            self.repository.add_entry(
                binding=actor_binding(actor), combat_id=combat.id,
                entry=NewCombatEntry(subject_kind="character", character_id=request.character_id,
                    display_name=character.name, attacks_allowed=_extra_attack_budget(character), surprised=request.surprised),
                idempotency_key=request.idempotency_key,
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        return self._view(self.repository.get(combat.id) or combat)

    def add_monster(self, actor: TableActorContext, request: AddMonsterInput) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        monster = self.monster_repository.get_instance(request.monster_instance_id)
        if monster is None or monster.campaign_id != actor.campaign_id:
            raise CombatNotFoundError("Monster Instance was not found in this Campaign")
        try:
            self.repository.add_entry(
                binding=actor_binding(actor), combat_id=combat.id,
                entry=NewCombatEntry(subject_kind="monster", monster_instance_id=monster.id,
                    display_name=monster.name, surprised=request.surprised, initiative_group_key=request.initiative_group_key),
                idempotency_key=request.idempotency_key,
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        return self._view(self.repository.get(combat.id) or combat)

    def resolve_initiative_order(self, actor: TableActorContext, request: ResolveInitiativeOrderInput) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        try:
            stored, _event = self.repository.resolve_initiative_order(
                binding=actor_binding(actor), combat_id=combat.id,
                ordered_entry_ids=request.ordered_entry_ids, idempotency_key=request.idempotency_key,
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        return self._view(stored)

    def advance_turn(self, actor: TableActorContext, *, idempotency_key: str | None = None) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        try:
            stored, _event = self.repository.advance_turn(
                binding=actor_binding(actor), combat_id=combat.id, idempotency_key=idempotency_key
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        return self._view(stored)

    def _authorize_entry(self, actor: TableActorContext, entry: StoredCombatEntry) -> tuple[UUID | None, str]:
        if entry.subject_kind == "monster":
            if not actor.is_current_dm:
                raise TableEventActorUnauthorizedError("Only the current Session DM controls Monster combatants")
            return None, "self"
        if entry.character_id is None:
            raise CombatStateConflictError("Character Combat entry has no Character identity")
        subject_seat_id = self.repository.controlling_seat_for_character(
            campaign_id=actor.campaign_id, session_id=actor.session_id, character_id=entry.character_id
        )
        if subject_seat_id is None:
            if actor.is_current_dm:
                raise CombatStateConflictError("Character is absent from this Session; DM must skip or withdraw it instead of silently proxying")
            raise TableEventActorUnauthorizedError("Character Combat entry is not controlled in this Session")
        if subject_seat_id in actor.controlled_seat_ids: return subject_seat_id, "self"
        if actor.is_current_dm: return subject_seat_id, "dm_proxy"
        raise TableEventActorUnauthorizedError("Actor does not control this Character Combat entry")

    def use_action(self, actor: TableActorContext, request: CombatActionInput) -> CombatActionView:
        self._current(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        entry = self.repository.get_entry(request.entry_id)
        if entry is None or entry.combat_id != combat.id: raise CombatNotFoundError("Combat entry was not found")
        subject_seat_id, execution_mode = self._authorize_entry(actor, entry)
        try:
            stored, _event = self.repository.consume_action(
                binding=actor_binding(actor), combat_id=combat.id, entry_id=entry.id,
                subject_seat_id=subject_seat_id, execution_mode=execution_mode,
                action_kind=request.action_kind.value, economy_cost=request.economy_cost.value,
                payload=dict(request.payload), idempotency_key=request.idempotency_key,
                attack_use=request.action_kind is CombatActionKind.ATTACK_BUDGET,
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        return CombatActionView(
            id=stored.id, combat_id=stored.combat_id, entry_id=stored.entry_id,
            session_id=stored.session_id, acting_seat_id=stored.acting_seat_id,
            subject_seat_id=stored.subject_seat_id, execution_mode=stored.execution_mode,
            action_kind=stored.action_kind, economy_cost=stored.economy_cost, payload=dict(stored.payload),
        )

    def set_reaction_window(self, actor: TableActorContext, request: ReactionWindowInput) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        state: dict[str, Any] = {"open": request.open}
        if request.reason: state["reason"] = request.reason
        if request.source_entry_id: state["source_entry_id"] = str(request.source_entry_id)
        self.repository.set_reaction_window(
            binding=actor_binding(actor), combat_id=combat.id, entry_id=request.entry_id,
            state=state if request.open else {}, idempotency_key=request.idempotency_key,
        )
        return self._view(self.repository.get(combat.id) or combat)

    def withdraw_entry(self, actor: TableActorContext, entry_id: UUID, *, idempotency_key: str | None = None) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        self.repository.withdraw_entry(
            binding=actor_binding(actor), combat_id=combat.id, entry_id=entry_id, idempotency_key=idempotency_key
        )
        return self._view(self.repository.get(combat.id) or combat)

    def end_combat(self, actor: TableActorContext, *, idempotency_key: str | None = None) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        stored, _event = self.repository.end_combat(
            binding=actor_binding(actor), combat_id=combat.id, idempotency_key=idempotency_key
        )
        return self._view(stored)


__all__ = [
    "ActiveCombatExistsError", "AddCharacterInput", "AddMonsterInput", "CombatActionInput", "CombatActionKind",
    "CombatActionView", "CombatEconomyCost", "CombatEntryView", "CombatLifecycleError", "CombatNotFoundError",
    "CombatService", "CombatStateConflictError", "CombatView", "ReactionWindowInput",
    "ResolveInitiativeOrderInput", "StartCombatInput", "_extra_attack_budget",
]
