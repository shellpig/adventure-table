from __future__ import annotations

import random
from typing import Any
from uuid import UUID

from pydantic import Field

from app.domain.combat.concentration_triggers import monster_save_modifier
from app.domain.combat.effect_resolver import EffectSpec
from app.domain.combat.event_projection import project_combat_event_payload
from app.domain.combat.lifecycle import (
    CombatNotFoundError,
    CombatService,
    CombatStateConflictError,
)
from app.domain.combat.projection import CombatantAudience
from app.domain.combat.resolution import DamageRollPart, RollMode
from app.domain.combat.spell_resolver import SaveDamageMode, SpellCastMode
from app.domain.rules.armor_class import calculate_armor_class
from app.content.registry import ContentRegistry
from app.domain.rooms.rolls import FormalRollSource, RollModifierMode, RollRequestType, RollService
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.characters import CharacterRepository
from app.persistence.combat.lifecycle import CombatRepository, StoredCombatEntry, actor_binding
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.spells import (
    CombatSpellNotFoundError,
    CombatSpellRepository,
    CombatSpellStateConflictError,
    StoredAoeSpellAction,
    StoredSpellCastAction,
)


class CastSpellInput(StrictModel):
    caster_entry_id: UUID
    target_entry_id: UUID | None = None
    spell_ref: str = Field(min_length=1, max_length=320)
    profile_id: str | None = None
    spell_level: int = Field(ge=0, le=9)
    slot_level: int | None = Field(default=None, ge=0, le=9)
    cast_mode: SpellCastMode = SpellCastMode.UTILITY
    attack_modifier: int | None = None
    attack_d20s: tuple[int, ...] = ()
    attack_mode: RollMode = RollMode.NORMAL
    target_ac: int | None = None
    save_ability_ref: str | None = None
    save_dc: int | None = None
    save_modifier: int | None = None
    save_d20: int | None = None
    save_damage_mode: SaveDamageMode = SaveDamageMode.NONE
    damage_parts: tuple[DamageRollPart, ...] = ()
    healing_amount: int = 0
    concentration: bool = False
    apply_effects: tuple[EffectSpec, ...] = ()
    roll_source: str = "server"
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class ProposeAoeSpellInput(StrictModel):
    caster_entry_id: UUID
    spell_ref: str = Field(min_length=1, max_length=320)
    profile_id: str
    spell_level: int = Field(ge=0, le=9)
    slot_level: int = Field(ge=0, le=9)
    save_ability_ref: str = Field(min_length=1, max_length=120)
    save_dc: int
    save_damage_mode: SaveDamageMode = SaveDamageMode.HALF
    proposed_target_ids: tuple[UUID, ...]
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class ResolveAoeSpellInput(StrictModel):
    action_id: UUID
    confirmed_target_ids: tuple[UUID, ...]
    save_modifiers: dict[UUID, int] = Field(default_factory=dict)
    save_d20s: dict[UUID, int] = Field(default_factory=dict)
    damage_parts: tuple[DamageRollPart, ...] = ()
    roll_source: str = "server"
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class SpellCastView(StrictModel):
    action_id: UUID
    combat_id: UUID
    caster_entry_id: UUID
    target_entry_id: UUID | None
    spell_ref: str
    cast_mode: str
    status: str
    roll_request_id: UUID | None
    roll_result_id: UUID | None
    resolution_result: dict[str, Any] | None = None


class AoeSpellProposalView(StrictModel):
    action_id: UUID
    combat_id: UUID
    caster_entry_id: UUID
    spell_ref: str
    status: str
    proposed_target_ids: tuple[UUID, ...]


class AoeSpellResolutionView(StrictModel):
    action_id: UUID
    combat_id: UUID
    caster_entry_id: UUID
    spell_ref: str
    status: str
    confirmed_target_ids: tuple[UUID, ...]
    resolution_result: dict[str, Any] | None = None


class CombatSpellService:
    def __init__(
        self,
        repository: CombatSpellRepository,
        combat_repository: CombatRepository,
        combat_service: CombatService,
        table_event_service: TableEventService,
        monster_repository: MonsterRepository,
        character_repository: CharacterRepository,
        roll_service: RollService,
        registry: ContentRegistry,
    ) -> None:
        self.repository = repository
        self.combat_repository = combat_repository
        self.combat_service = combat_service
        self.table_event_service = table_event_service
        self.monster_repository = monster_repository
        self.character_repository = character_repository
        self.roll_service = roll_service
        self.registry = registry

    def _active_entry(self, actor: TableActorContext, entry_id: UUID) -> StoredCombatEntry:
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        entry = self.combat_repository.get_entry(entry_id)
        if entry is None or entry.combat_id != combat.id or entry.status != "active":
            raise CombatSpellNotFoundError(str(entry_id))
        return entry

    def _target_ac(self, target_entry: StoredCombatEntry) -> int:
        if target_entry.subject_kind == "character":
            if target_entry.character_id is None:
                raise CombatSpellStateConflictError("Character entry has no character_id")
            loaded = self.character_repository.load_character(target_entry.character_id)
            return calculate_armor_class(loaded.build, loaded.state, self.registry)
        if target_entry.subject_kind == "monster":
            if target_entry.monster_instance_id is None:
                raise CombatSpellStateConflictError("Monster entry has no monster_instance_id")
            monster = self.monster_repository.get_instance(target_entry.monster_instance_id)
            if monster is None:
                raise CombatSpellNotFoundError(str(target_entry.monster_instance_id))
            return int(dict(monster.rules_snapshot or {})["armor_class"])
        raise CombatSpellStateConflictError(f"Unsupported target kind: {target_entry.subject_kind}")

    def _target_save_modifier(self, target_entry: StoredCombatEntry, ability_ref: str) -> int:
        clean_ref = ability_ref.split(":")[-1]
        if target_entry.subject_kind == "character":
            if target_entry.character_id is None:
                raise CombatSpellStateConflictError("Character entry has no character_id")
            return self.roll_service.modifier_resolver.modifier_for(
                character_id=target_entry.character_id,
                request_type=RollRequestType.SAVING_THROW,
                ability_ref=clean_ref,
                skill_ref=None,
            )
        if target_entry.subject_kind == "monster":
            if target_entry.monster_instance_id is None:
                raise CombatSpellStateConflictError("Monster entry has no monster_instance_id")
            monster = self.monster_repository.get_instance(target_entry.monster_instance_id)
            if monster is None:
                raise CombatSpellNotFoundError(str(target_entry.monster_instance_id))
            return monster_save_modifier(dict(monster.rules_snapshot or {}), clean_ref)
        raise CombatSpellStateConflictError(f"Unsupported target kind: {target_entry.subject_kind}")

    def cast_spell(self, actor: TableActorContext, input: CastSpellInput) -> SpellCastView:
        self.table_event_service.require_actor_current(actor)
        caster_entry = self._active_entry(actor, input.caster_entry_id)
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, caster_entry)

        target_entry: StoredCombatEntry | None = None
        if input.target_entry_id is not None:
            target_entry = self._active_entry(actor, input.target_entry_id)

        target_ac = input.target_ac
        if target_ac is None and input.cast_mode is SpellCastMode.ATTACK and target_entry is not None:
            target_ac = self._target_ac(target_entry)

        attack_d20s = input.attack_d20s
        if not attack_d20s and input.cast_mode is SpellCastMode.ATTACK:
            if input.attack_mode in {RollMode.ADVANTAGE, RollMode.DISADVANTAGE}:
                attack_d20s = (random.randint(1, 20), random.randint(1, 20))
            else:
                attack_d20s = (random.randint(1, 20),)

        save_modifier = input.save_modifier
        if save_modifier is None and input.cast_mode is SpellCastMode.SAVE and target_entry is not None and input.save_ability_ref:
            save_modifier = self._target_save_modifier(target_entry, input.save_ability_ref)

        save_d20 = input.save_d20
        if save_d20 is None and input.cast_mode is SpellCastMode.SAVE:
            save_d20 = random.randint(1, 20)

        target_seat_id: UUID | None = None
        if target_entry is not None and target_entry.subject_kind == "character":
            target_seat_id = self.combat_repository.controlling_seat_for_character(
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
                character_id=target_entry.character_id,
            )

        if caster_entry.subject_kind == "character":
            profile_id = input.profile_id
            if profile_id is None:
                if caster_entry.character_id is None:
                    raise CombatSpellStateConflictError("Character entry has no character_id")
                loaded = self.character_repository.load_character(caster_entry.character_id)
                if not loaded.build.spellcasting_profiles:
                    raise CombatSpellStateConflictError("Character has no spellcasting profiles")
                profile_id = loaded.build.spellcasting_profiles[0].profile_id

            stored, _event = self.repository.cast_character_spell(
                binding=actor_binding(actor),
                combat_id=caster_entry.combat_id,
                caster_entry_id=input.caster_entry_id,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                profile_id=profile_id,
                spell_ref=input.spell_ref,
                spell_level=input.spell_level,
                slot_level=input.slot_level if input.slot_level is not None else input.spell_level,
                cast_mode=input.cast_mode,
                target_entry_id=input.target_entry_id,
                roll_source=input.roll_source,
                idempotency_key=input.idempotency_key,
                target_seat_id=target_seat_id,
                attack_modifier=input.attack_modifier,
                attack_d20s=attack_d20s,
                attack_mode=input.attack_mode,
                target_ac=target_ac,
                save_ability_ref=input.save_ability_ref,
                save_dc=input.save_dc,
                save_modifier=save_modifier,
                save_d20=save_d20,
                save_damage_mode=input.save_damage_mode,
                damage_parts=input.damage_parts,
                healing_amount=input.healing_amount,
                concentration=input.concentration,
                apply_effects=input.apply_effects,
            )
        elif caster_entry.subject_kind == "monster":
            stored, _event = self.repository.cast_monster_spell(
                binding=actor_binding(actor),
                combat_id=caster_entry.combat_id,
                caster_entry_id=input.caster_entry_id,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                spell_ref=input.spell_ref,
                spell_level=input.spell_level,
                slot_level=input.slot_level,
                cast_mode=input.cast_mode,
                target_entry_id=input.target_entry_id,
                roll_source=input.roll_source,
                idempotency_key=input.idempotency_key,
                target_seat_id=target_seat_id,
                attack_modifier=input.attack_modifier,
                attack_d20s=attack_d20s,
                attack_mode=input.attack_mode,
                target_ac=target_ac,
                save_ability_ref=input.save_ability_ref,
                save_dc=input.save_dc,
                save_modifier=save_modifier,
                save_d20=save_d20,
                save_damage_mode=input.save_damage_mode,
                damage_parts=input.damage_parts,
                healing_amount=input.healing_amount,
                concentration=input.concentration,
                apply_effects=input.apply_effects,
            )
        else:
            raise CombatSpellStateConflictError(f"Unsupported caster kind: {caster_entry.subject_kind}")

        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)

        audience: CombatantAudience = "dm" if actor.is_current_dm else "player"
        resolution_dict = None
        if stored.resolution_result is not None:
            resolution_dict = project_combat_event_payload(
                "combat.spell_cast_resolved",
                stored.resolution_result,
                audience=audience,
            )

        return SpellCastView(
            action_id=stored.action_id,
            combat_id=stored.combat_id,
            caster_entry_id=stored.caster_entry_id,
            target_entry_id=stored.target_entry_id,
            spell_ref=stored.spell_ref,
            cast_mode=stored.cast_mode.value,
            status=stored.status,
            roll_request_id=stored.roll_request_id,
            roll_result_id=stored.roll_result_id,
            resolution_result=resolution_dict,
        )

    def propose_aoe(self, actor: TableActorContext, input: ProposeAoeSpellInput) -> AoeSpellProposalView:
        self.table_event_service.require_actor_current(actor)
        caster_entry = self._active_entry(actor, input.caster_entry_id)
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, caster_entry)

        stored, _event = self.repository.propose_character_aoe(
            binding=actor_binding(actor),
            combat_id=caster_entry.combat_id,
            caster_entry_id=input.caster_entry_id,
            subject_seat_id=subject_seat_id,
            execution_mode=execution_mode,
            profile_id=input.profile_id,
            spell_ref=input.spell_ref,
            spell_level=input.spell_level,
            slot_level=input.slot_level,
            save_ability_ref=input.save_ability_ref,
            save_dc=input.save_dc,
            save_damage_mode=input.save_damage_mode,
            proposed_target_ids=input.proposed_target_ids,
            idempotency_key=input.idempotency_key,
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)

        return AoeSpellProposalView(
            action_id=stored.action_id,
            combat_id=stored.combat_id,
            caster_entry_id=stored.caster_entry_id,
            spell_ref=stored.spell_ref,
            status=stored.status,
            proposed_target_ids=tuple(UUID(t) for t in stored.adjudication.proposed_target_ids),
        )

    def resolve_aoe(self, actor: TableActorContext, input: ResolveAoeSpellInput) -> AoeSpellResolutionView:
        self.table_event_service.require_actor_current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError("Only the current Session DM can adjudicate AoE spells")

        existing = self.repository.get_aoe_action(session_id=actor.session_id, action_id=input.action_id)
        if existing is None:
            raise CombatSpellNotFoundError(str(input.action_id))

        save_modifiers = dict(input.save_modifiers)
        save_d20s = dict(input.save_d20s)
        target_seat_ids: dict[UUID, UUID | None] = {}

        for target_id in input.confirmed_target_ids:
            target_entry = self._active_entry(actor, target_id)
            if target_id not in save_modifiers:
                save_modifiers[target_id] = self._target_save_modifier(target_entry, existing.save_ability_ref)
            if target_id not in save_d20s:
                save_d20s[target_id] = random.randint(1, 20)
            if target_entry.subject_kind == "character":
                target_seat_ids[target_id] = self.combat_repository.controlling_seat_for_character(
                    campaign_id=actor.campaign_id,
                    session_id=actor.session_id,
                    character_id=target_entry.character_id,
                )
            else:
                target_seat_ids[target_id] = None

        stored, _event = self.repository.resolve_character_aoe(
            binding=actor_binding(actor),
            action_id=input.action_id,
            confirmed_target_ids=input.confirmed_target_ids,
            save_modifiers=save_modifiers,
            save_d20s=save_d20s,
            damage_parts=input.damage_parts,
            roll_source=input.roll_source,
            idempotency_key=input.idempotency_key,
            target_seat_ids=target_seat_ids,
        )
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)

        audience: CombatantAudience = "dm" if actor.is_current_dm else "player"
        resolution_dict = None
        if stored.resolution_result is not None:
            resolution_dict = project_combat_event_payload(
                "combat.spell_aoe_resolved",
                stored.resolution_result,
                audience=audience,
            )

        return AoeSpellResolutionView(
            action_id=stored.action_id,
            combat_id=stored.combat_id,
            caster_entry_id=stored.caster_entry_id,
            spell_ref=stored.spell_ref,
            status=stored.status,
            confirmed_target_ids=input.confirmed_target_ids,
            resolution_result=resolution_dict,
        )


__all__ = [
    "AoeSpellProposalView",
    "AoeSpellResolutionView",
    "CastSpellInput",
    "CombatSpellNotFoundError",
    "CombatSpellService",
    "CombatSpellStateConflictError",
    "ProposeAoeSpellInput",
    "ResolveAoeSpellInput",
    "SpellCastView",
]
