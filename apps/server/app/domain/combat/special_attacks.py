from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from app.content.registry import ContentRegistry
from app.domain.combat.lifecycle import CombatNotFoundError, CombatService, CombatStateConflictError
from app.domain.combat.resolution import (
    SizeCategory,
    SpecialAttackKind,
    resolve_grapple_or_shove,
)
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource, RollModifierMode, RollRequestType, RollService
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.domain.rules.abilities import ability_modifier
from app.persistence.characters import CharacterRepository
from app.persistence.combat.core_rolls import CombatCoreRollRepository
from app.persistence.combat.lifecycle import CombatRepository, StoredCombatEntry, actor_binding
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.special_attacks import (
    GRAPPLED_REF,
    SpecialAttackNotFoundError,
    SpecialAttackRepository,
    SpecialAttackRollComputation,
    SpecialAttackRollUnit,
    SpecialAttackStateConflictError,
    StoredSpecialAttackAction,
)


ATHLETICS_REF = "srd5.1:skill:athletics"
ACROBATICS_REF = "srd5.1:skill:acrobatics"


class SpecialAttackRequestInput(StrictModel):
    attacker_entry_id: UUID
    target_entry_id: UUID
    kind: SpecialAttackKind
    attacker_modifier_mode: RollModifierMode = RollModifierMode.NORMAL
    defender_modifier_mode: RollModifierMode = RollModifierMode.NORMAL
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class SpecialAttackAdjudicationInput(StrictModel):
    action_id: UUID
    in_reach: bool
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class SpecialAttackView(StrictModel):
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


def _view(item: StoredSpecialAttackAction) -> SpecialAttackView:
    return SpecialAttackView(
        action_id=item.action_id,
        combat_id=item.combat_id,
        attacker_entry_id=item.attacker_entry_id,
        target_entry_id=item.target_entry_id,
        kind=item.kind,
        status=item.status,
        in_reach=item.in_reach,
        attacker_roll_request_id=item.attacker_roll_request_id,
        defender_roll_request_id=item.defender_roll_request_id,
        attacker_skill=item.attacker_skill,
        defender_skill=item.defender_skill,
        resolution_result=dict(item.resolution_result) if item.resolution_result else None,
    )


class CombatSpecialAttackService:
    """Actor-neutral 2014 Grapple/Shove service on formal opposed checks."""

    def __init__(
        self,
        repository: SpecialAttackRepository,
        core_roll_repository: CombatCoreRollRepository,
        combat_repository: CombatRepository,
        combat_service: CombatService,
        character_repository: CharacterRepository,
        monster_repository: MonsterRepository,
        registry: ContentRegistry,
        roll_service: RollService,
        table_event_service: TableEventService,
    ) -> None:
        self.repository = repository
        self.core_roll_repository = core_roll_repository
        self.combat_repository = combat_repository
        self.combat_service = combat_service
        self.character_repository = character_repository
        self.monster_repository = monster_repository
        self.registry = registry
        self.roll_service = roll_service
        self.table_event_service = table_event_service

    def _active_entry(self, actor: TableActorContext, entry_id: UUID) -> StoredCombatEntry:
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        entry = self.combat_repository.get_entry(entry_id)
        if entry is None or entry.combat_id != combat.id or entry.status != "active":
            raise CombatNotFoundError("CombatEntry is missing or inactive")
        return entry

    @staticmethod
    def _parse_size(value: object) -> SizeCategory:
        if not isinstance(value, str) or not value.strip():
            raise CombatStateConflictError("Combatant size is required for Grapple/Shove")
        key = value.strip().upper().replace(" ", "_")
        try:
            return SizeCategory[key]
        except KeyError as exc:
            raise CombatStateConflictError(f"Unsupported combatant size: {value}") from exc

    def _size(self, entry: StoredCombatEntry) -> SizeCategory:
        if entry.subject_kind == "character":
            if entry.character_id is None:
                raise CombatStateConflictError("Character CombatEntry has no Character identity")
            character = self.character_repository.load_character(entry.character_id)
            race = self.registry.get_optional(character.build.race_ref)
            if race is None:
                raise CombatStateConflictError("Character race content is unavailable for size resolution")
            return self._parse_size(race.data.get("size"))
        if entry.subject_kind == "monster":
            if entry.monster_instance_id is None:
                raise CombatStateConflictError("Monster CombatEntry has no Monster identity")
            monster = self.monster_repository.get_instance(entry.monster_instance_id)
            if monster is None:
                raise CombatNotFoundError("Monster Instance was not found")
            return self._parse_size(monster.rules_snapshot.get("size"))
        raise CombatStateConflictError(f"unsupported CombatEntry kind: {entry.subject_kind}")

    def _has_free_hand(self, entry: StoredCombatEntry) -> bool:
        if entry.subject_kind == "monster":
            if entry.monster_instance_id is None:
                raise CombatStateConflictError("Monster CombatEntry has no Monster identity")
            monster = self.monster_repository.get_instance(entry.monster_instance_id)
            if monster is None:
                raise CombatNotFoundError("Monster Instance was not found")
            explicit = monster.rules_snapshot.get("free_hands")
            return bool(explicit) if isinstance(explicit, int) else True
        if entry.subject_kind != "character" or entry.character_id is None:
            raise CombatStateConflictError("Special Attack attacker has no Character identity")
        character = self.character_repository.load_character(entry.character_id)
        occupied = 0
        for inventory in character.state.inventory_state:
            if not inventory.equipped:
                continue
            content = self.registry.get_optional(inventory.item_ref)
            if content is None:
                continue
            data = dict(content.data)
            if content.index == "shield":
                occupied += 1
                continue
            if not isinstance(data.get("weapon_range"), str):
                continue
            raw_properties = data.get("properties")
            two_handed = False
            if isinstance(raw_properties, list):
                for raw in raw_properties:
                    if isinstance(raw, dict):
                        candidate = raw.get("index") or raw.get("name")
                    else:
                        candidate = raw
                    if isinstance(candidate, str) and candidate.strip().casefold().replace(" ", "-") == "two-handed":
                        two_handed = True
                        break
            occupied += 2 if two_handed else 1
        return occupied < 2

    def _character_skill_modifier(self, character_id: UUID, skill_ref: str) -> int:
        return self.roll_service.modifier_resolver.modifier_for(
            character_id=character_id,
            request_type=RollRequestType.SKILL,
            ability_ref=None,
            skill_ref=skill_ref,
        )

    @staticmethod
    def _monster_skill_modifier(rules: dict[str, Any], skill_ref: str) -> int:
        skill = skill_ref.rsplit(":", 1)[-1]
        ability = "strength" if skill == "athletics" else "dexterity"
        scores = rules.get("ability_scores", {})
        score = scores.get(ability, 10) if isinstance(scores, dict) else 10
        base = ability_modifier(score if isinstance(score, int) else 10)
        proficiencies = rules.get("proficiencies", [])
        if not isinstance(proficiencies, list):
            return base
        expected = {skill, f"skill-{skill}"}
        for raw in proficiencies:
            if not isinstance(raw, dict):
                continue
            reference = raw.get("proficiency")
            index = None
            if isinstance(reference, dict):
                candidate = reference.get("index") or reference.get("name")
                if isinstance(candidate, str):
                    index = candidate.strip().casefold().replace(" ", "-")
            value = raw.get("value")
            if index in expected and isinstance(value, int):
                return value
        return base

    def _skill_unit(
        self,
        actor: TableActorContext,
        entry: StoredCombatEntry,
        skill_ref: str,
        modifier_mode: RollModifierMode,
        *,
        role: str,
    ) -> SpecialAttackRollUnit:
        if entry.subject_kind == "character":
            if entry.character_id is None:
                raise CombatStateConflictError("Character CombatEntry has no Character identity")
            seat_id = self.combat_repository.controlling_seat_for_character(
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
                character_id=entry.character_id,
            )
            modifier = self._character_skill_modifier(entry.character_id, skill_ref)
            return SpecialAttackRollUnit(
                role=role,
                target_entry_id=entry.id,
                target_seat_id=seat_id,
                target_character_id=entry.character_id,
                skill_ref=skill_ref,
                modifier=modifier,
                modifier_mode=modifier_mode.value,
            )
        if entry.subject_kind == "monster":
            if entry.monster_instance_id is None:
                raise CombatStateConflictError("Monster CombatEntry has no Monster identity")
            monster = self.monster_repository.get_instance(entry.monster_instance_id)
            if monster is None:
                raise CombatNotFoundError("Monster Instance was not found")
            return SpecialAttackRollUnit(
                role=role,
                target_entry_id=entry.id,
                target_seat_id=None,
                target_character_id=None,
                skill_ref=skill_ref,
                modifier=self._monster_skill_modifier(monster.rules_snapshot, skill_ref),
                modifier_mode=modifier_mode.value,
            )
        raise CombatStateConflictError(f"unsupported CombatEntry kind: {entry.subject_kind}")

    def _is_grappled(self, entry: StoredCombatEntry) -> bool:
        ctx = self.combat_service.condition_context(entry)
        return GRAPPLED_REF in ctx.conditions

    def _best_escape_unit(
        self,
        actor: TableActorContext,
        entry: StoredCombatEntry,
        mode: RollModifierMode,
        *,
        role: str,
    ) -> SpecialAttackRollUnit:
        athletics = self._skill_unit(
            actor,
            entry,
            ATHLETICS_REF,
            mode,
            role=role,
        )
        acrobatics = self._skill_unit(
            actor,
            entry,
            ACROBATICS_REF,
            mode,
            role=role,
        )
        return acrobatics if acrobatics.modifier > athletics.modifier else athletics

    def request_special_attack(
        self,
        actor: TableActorContext,
        request: SpecialAttackRequestInput,
    ) -> SpecialAttackView:
        self.table_event_service.require_actor_current(actor)
        attacker = self._active_entry(actor, request.attacker_entry_id)
        target = self._active_entry(actor, request.target_entry_id)
        if attacker.combat_id != target.combat_id:
            raise CombatStateConflictError("Attacker and target must belong to the same Combat")
        if attacker.id == target.id:
            raise CombatStateConflictError("Special Attack target must be a different CombatEntry")
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, attacker)

        if request.kind is SpecialAttackKind.ESCAPE_GRAPPLE:
            if not self._is_grappled(attacker):
                raise CombatStateConflictError("Combatant is not grappled")
            attacker_unit = self._best_escape_unit(
                actor,
                attacker,
                request.attacker_modifier_mode,
                role="attacker",
            )
            defender_unit = self._skill_unit(
                actor,
                target,
                ATHLETICS_REF,
                request.defender_modifier_mode,
                role="defender",
            )
            try:
                stored, _event = self.repository.request_escape(
                    binding=actor_binding(actor),
                    combat_id=attacker.combat_id,
                    attacker_entry_id=attacker.id,
                    target_entry_id=target.id,
                    subject_seat_id=subject_seat_id,
                    execution_mode=execution_mode,
                    attacker_unit=attacker_unit,
                    defender_unit=defender_unit,
                    idempotency_key=request.idempotency_key,
                )
            except SpecialAttackStateConflictError as exc:
                raise CombatStateConflictError(str(exc)) from exc
            if self.table_event_service.notifier is not None:
                self.table_event_service.notifier.notify(actor.session_id)
            return _view(stored)

        attacker_size = self._size(attacker)
        target_size = self._size(target)
        free_hand = self._has_free_hand(attacker)
        preflight = resolve_grapple_or_shove(
            kind=request.kind,
            attacker_size=attacker_size,
            target_size=target_size,
            attacker_check_total=0,
            target_check_total=0,
            attacker_has_free_hand=free_hand,
            reach_confirmed=None,
        )
        if preflight.status == "invalid":
            raise CombatStateConflictError(preflight.reason or "Special Attack is invalid")
        if preflight.status != "dm_adjudication_required":
            raise CombatStateConflictError("Special Attack preflight did not require geometry adjudication")

        attacker_unit = self._skill_unit(
            actor,
            attacker,
            ATHLETICS_REF,
            request.attacker_modifier_mode,
            role="attacker",
        )
        defender_unit = self._best_escape_unit(
            actor,
            target,
            request.defender_modifier_mode,
            role="defender",
        )
        try:
            stored, _event = self.repository.request(
                binding=actor_binding(actor),
                combat_id=attacker.combat_id,
                attacker_entry_id=attacker.id,
                target_entry_id=target.id,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                kind=request.kind,
                attacker_size=attacker_size,
                target_size=target_size,
                attacker_has_free_hand=free_hand,
                attacker_unit=attacker_unit,
                defender_unit=defender_unit,
                idempotency_key=request.idempotency_key,
            )
        except SpecialAttackStateConflictError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return _view(stored)

    def adjudicate_special_attack(
        self,
        actor: TableActorContext,
        request: SpecialAttackAdjudicationInput,
    ) -> SpecialAttackView:
        self.table_event_service.require_actor_current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError("Only the current Session DM can adjudicate Quick Combat reach")
        try:
            stored, _event = self.repository.adjudicate_reach(
                binding=actor_binding(actor),
                action_id=request.action_id,
                in_reach=request.in_reach,
                idempotency_key=request.idempotency_key,
            )
        except SpecialAttackStateConflictError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return _view(stored)

    @staticmethod
    def _authorize_roll(
        actor: TableActorContext,
        target_seat_id: UUID | None,
    ) -> tuple[UUID, str]:
        if target_seat_id is None:
            if not actor.is_current_dm:
                raise TableEventActorUnauthorizedError("Only the current Session DM can roll for Monster combatants")
            return actor.seat_id, "self"
        if target_seat_id in actor.controlled_seat_ids:
            return target_seat_id, "self"
        if actor.is_current_dm:
            return actor.seat_id, "dm_proxy"
        raise TableEventActorUnauthorizedError("Actor cannot complete this Special Attack RollRequest")

    def complete_special_attack_roll(
        self,
        actor: TableActorContext,
        input: FormalRollInput,
    ) -> SpecialAttackView:
        self.table_event_service.require_actor_current(actor)
        action = self.repository.find_by_roll_request(
            session_id=actor.session_id,
            request_id=input.roll_request_id,
        )
        if action is None:
            raise SpecialAttackNotFoundError(str(input.roll_request_id))
        request = self.core_roll_repository.get_request(
            session_id=actor.session_id,
            request_id=input.roll_request_id,
        )
        if request is None or request.request_type != "skill":
            raise SpecialAttackNotFoundError(str(input.roll_request_id))
        acting_seat_id, execution_mode = self._authorize_roll(actor, request.target_seat_id)

        def compute() -> SpecialAttackRollComputation:
            audit = self.roll_service.engine.d20(
                mode=RollModifierMode(request.modifier_mode),
                base_modifier=0,
                flat_adjustment=request.flat_adjustment,
                physical_raw_dice=input.raw_dice if input.source is FormalRollSource.PHYSICAL else None,
            )
            return SpecialAttackRollComputation(
                source=input.source.value,
                formula=audit.formula,
                raw_dice=audit.raw_dice,
                kept_dice=audit.kept_dice,
                base_modifier=audit.base_modifier,
                flat_adjustment=audit.flat_adjustment,
                total=audit.total,
            )

        try:
            stored, _event = self.repository.complete_roll(
                binding=actor_binding(actor),
                request_id=input.roll_request_id,
                acting_seat_id=acting_seat_id,
                execution_mode=execution_mode,
                result_factory=compute,
                idempotency_key=input.idempotency_key,
            )
        except SpecialAttackStateConflictError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return _view(stored)


__all__ = [
    "ACROBATICS_REF",
    "ATHLETICS_REF",
    "CombatSpecialAttackService",
    "SpecialAttackAdjudicationInput",
    "SpecialAttackNotFoundError",
    "SpecialAttackRequestInput",
    "SpecialAttackView",
]
