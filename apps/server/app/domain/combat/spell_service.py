from typing import Any
from uuid import UUID

from pydantic import Field

from app.content.registry import ContentRegistry
from app.domain.combat.effect_resolver import EffectSpec
from app.domain.combat.event_projection import project_combat_event_payload
from app.domain.combat.lifecycle import (
    CombatNotFoundError,
    CombatService,
    CombatStateConflictError,
)
from app.domain.combat.projection import CombatantAudience
from app.domain.combat.resolution import DamageRollPart, RollMode
from app.domain.combat.spell_content_adapter import SpellDefinitionResolver
from app.domain.combat.spell_resolver import SaveDamageMode, SpellCastMode
from app.domain.rooms.rolls import FormalRollSource, RollService
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
    slot_level: int | None = Field(default=None, ge=0, le=9)
    profile_id: str | None = None
    attack_mode: RollMode = RollMode.NORMAL
    roll_source: FormalRollSource = FormalRollSource.SERVER
    raw_dice: tuple[int, ...] | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class ProposeAoeSpellInput(StrictModel):
    caster_entry_id: UUID
    spell_ref: str = Field(min_length=1, max_length=320)
    slot_level: int | None = Field(default=None, ge=0, le=9)
    profile_id: str | None = None
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
        self.resolver = SpellDefinitionResolver(
            character_repository=character_repository,
            monster_repository=monster_repository,
            combat_repository=combat_repository,
            roll_service=roll_service,
            registry=registry,
        )

    def _active_entry(self, actor: TableActorContext, entry_id: UUID) -> StoredCombatEntry:
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        entry = self.combat_repository.get_entry(entry_id)
        if entry is None or entry.combat_id != combat.id or entry.status != "active":
            raise CombatSpellNotFoundError(str(entry_id))
        return entry

    def cast_spell(self, actor: TableActorContext, input: CastSpellInput) -> SpellCastView:
        self.table_event_service.require_actor_current(actor)
        caster_entry = self._active_entry(actor, input.caster_entry_id)
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, caster_entry)

        target_entry: StoredCombatEntry | None = None
        if input.target_entry_id is not None:
            target_entry = self._active_entry(actor, input.target_entry_id)

        try:
            resolved = self.resolver.resolve_cast(
                actor=actor,
                caster_entry=caster_entry,
                target_entry=target_entry,
                spell_ref=input.spell_ref,
                slot_level=input.slot_level,
                profile_id=input.profile_id,
                attack_mode=input.attack_mode,
                roll_source=input.roll_source,
                raw_dice=input.raw_dice,
                subject_seat_id=subject_seat_id,
            )
        except LookupError as exc:
            raise CombatSpellNotFoundError(str(exc)) from exc
        except ValueError as exc:
            raise CombatSpellStateConflictError(str(exc)) from exc

        if caster_entry.subject_kind == "character":
            stored, _event = self.repository.cast_character_spell(
                binding=actor_binding(actor),
                combat_id=caster_entry.combat_id,
                caster_entry_id=input.caster_entry_id,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                profile_id=resolved.profile_id or "default",
                spell_ref=resolved.spell_ref,
                spell_level=resolved.spell_level,
                slot_level=resolved.slot_level,
                cast_mode=resolved.cast_mode,
                target_entry_id=input.target_entry_id,
                roll_source=input.roll_source.value,
                idempotency_key=input.idempotency_key,
                target_seat_id=resolved.target_seat_id,
                attack_modifier=resolved.attack_modifier,
                attack_d20s=resolved.attack_d20s,
                attack_mode=input.attack_mode,
                target_ac=resolved.target_ac,
                save_ability_ref=resolved.save_ability_ref,
                save_dc=resolved.save_dc,
                save_modifier=resolved.save_modifier,
                save_d20=resolved.save_d20,
                save_damage_mode=resolved.save_damage_mode,
                damage_parts=resolved.damage_parts,
                healing_amount=resolved.healing_amount,
                concentration=resolved.concentration,
                apply_effects=resolved.apply_effects,
            )
        elif caster_entry.subject_kind == "monster":
            stored, _event = self.repository.cast_monster_spell(
                binding=actor_binding(actor),
                combat_id=caster_entry.combat_id,
                caster_entry_id=input.caster_entry_id,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                spell_ref=resolved.spell_ref,
                spell_level=resolved.spell_level,
                slot_level=resolved.slot_level,
                cast_mode=resolved.cast_mode,
                target_entry_id=input.target_entry_id,
                roll_source=input.roll_source.value,
                idempotency_key=input.idempotency_key,
                target_seat_id=resolved.target_seat_id,
                attack_modifier=resolved.attack_modifier,
                attack_d20s=resolved.attack_d20s,
                attack_mode=input.attack_mode,
                target_ac=resolved.target_ac,
                save_ability_ref=resolved.save_ability_ref,
                save_dc=resolved.save_dc,
                save_modifier=resolved.save_modifier,
                save_d20=resolved.save_d20,
                save_damage_mode=resolved.save_damage_mode,
                damage_parts=resolved.damage_parts,
                healing_amount=resolved.healing_amount,
                concentration=resolved.concentration,
                apply_effects=resolved.apply_effects,
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

        try:
            (
                spell_level,
                effective_slot_level,
                effective_profile_id,
                save_ability_ref,
                save_dc,
                save_damage_mode,
            ) = self.resolver.resolve_aoe_proposal(
                actor=actor,
                caster_entry=caster_entry,
                spell_ref=input.spell_ref,
                slot_level=input.slot_level,
                profile_id=input.profile_id,
            )
        except LookupError as exc:
            raise CombatSpellNotFoundError(str(exc)) from exc
        except ValueError as exc:
            raise CombatSpellStateConflictError(str(exc)) from exc

        stored, _event = self.repository.propose_character_aoe(
            binding=actor_binding(actor),
            combat_id=caster_entry.combat_id,
            caster_entry_id=input.caster_entry_id,
            subject_seat_id=subject_seat_id,
            execution_mode=execution_mode,
            profile_id=effective_profile_id,
            spell_ref=input.spell_ref,
            spell_level=spell_level,
            slot_level=effective_slot_level,
            save_ability_ref=save_ability_ref,
            save_dc=save_dc,
            save_damage_mode=save_damage_mode,
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

        try:
            save_modifiers, save_d20s, damage_parts, target_seat_ids = self.resolver.resolve_aoe_defaults(
                actor=actor,
                existing=existing,
                confirmed_target_ids=input.confirmed_target_ids,
                dm_save_modifiers=tuple(input.save_modifiers.items()),
                dm_save_d20s=tuple(input.save_d20s.items()),
                dm_damage_parts=input.damage_parts,
                get_active_entry=self._active_entry,
            )
        except LookupError as exc:
            raise CombatSpellNotFoundError(str(exc)) from exc
        except ValueError as exc:
            raise CombatSpellStateConflictError(str(exc)) from exc

        stored, _event = self.repository.resolve_character_aoe(
            binding=actor_binding(actor),
            action_id=input.action_id,
            confirmed_target_ids=input.confirmed_target_ids,
            save_modifiers=save_modifiers,
            save_d20s=save_d20s,
            damage_parts=damage_parts,
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
