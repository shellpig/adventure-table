from collections.abc import Mapping
from typing import Any, Literal
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
from app.domain.combat.spell_resources import (
    access_matches_profile,
    authorize_character_spell,
    monster_casting_sources,
    monster_spell_ref,
    resolve_monster_spell_source,
)
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


class CastableSpellView(StrictModel):
    spell_ref: str
    name: str
    level: int
    profile_id: str | None
    concentration: bool
    targeting: Literal["single", "self", "aoe"]
    cast_mode: SpellCastMode
    castable_slot_levels: tuple[int, ...]


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

    @staticmethod
    def _cast_mode(spell_data: Mapping[str, object]) -> SpellCastMode:
        if spell_data.get("attack_type"):
            return SpellCastMode.ATTACK
        if spell_data.get("dc"):
            return SpellCastMode.SAVE
        if spell_data.get("heal_at_slot_level"):
            return SpellCastMode.HEAL
        return SpellCastMode.UTILITY

    @staticmethod
    def _targeting(spell_data: Mapping[str, object]) -> Literal["single", "self", "aoe"]:
        if spell_data.get("area_of_effect"):
            return "aoe"
        spell_range = spell_data.get("range")
        if isinstance(spell_range, str) and spell_range.strip().lower() == "self":
            return "self"
        return "single"

    def _castable_spell_view(
        self,
        spell_ref: str,
        *,
        profile_id: str | None,
        castable_slot_levels: tuple[int, ...],
    ) -> CastableSpellView:
        spell_entry = self.registry.get(spell_ref)
        spell_data = spell_entry.data
        return CastableSpellView(
            spell_ref=spell_ref,
            name=spell_entry.name,
            level=int(spell_data.get("level", 0)),
            profile_id=profile_id,
            concentration=bool(spell_data.get("concentration", False)),
            targeting=self._targeting(spell_data),
            cast_mode=self._cast_mode(spell_data),
            castable_slot_levels=castable_slot_levels,
        )

    def available_spells(
        self,
        actor: TableActorContext,
        entry_id: UUID,
    ) -> tuple[CastableSpellView, ...]:
        self.table_event_service.require_actor_current(actor)
        entry = self._active_entry(actor, entry_id)
        self.combat_service._authorize_entry(actor, entry)

        views: list[CastableSpellView] = []
        if entry.subject_kind == "character":
            if entry.character_id is None:
                raise CombatSpellStateConflictError("Character entry has no character_id")
            character = self.character_repository.load_character(entry.character_id)
            seen: set[tuple[str, str]] = set()
            for profile in character.build.spellcasting_profiles:
                for access in character.build.spell_access_entries:
                    key = (profile.profile_id, access.spell_key)
                    if key in seen or not access_matches_profile(
                        character.build, access=access, profile=profile
                    ):
                        continue
                    seen.add(key)
                    spell_entry = self.registry.get(access.spell_key)
                    spell_level = int(spell_entry.data.get("level", 0))
                    castable_levels: list[int] = []
                    levels = (0,) if spell_level == 0 else range(spell_level, 10)
                    for slot_level in levels:
                        try:
                            authorize_character_spell(
                                build=character.build,
                                state=character.state,
                                profile_id=profile.profile_id,
                                spell_ref=access.spell_key,
                                spell_level=spell_level,
                                slot_level=slot_level,
                            )
                        except ValueError:
                            continue
                        castable_levels.append(slot_level)
                    if castable_levels:
                        views.append(
                            self._castable_spell_view(
                                access.spell_key,
                                profile_id=profile.profile_id,
                                castable_slot_levels=tuple(castable_levels),
                            )
                        )
        elif entry.subject_kind == "monster":
            if entry.monster_instance_id is None:
                raise CombatSpellStateConflictError("Monster entry has no monster_instance_id")
            monster = self.monster_repository.get_instance(entry.monster_instance_id)
            if monster is None:
                raise CombatSpellNotFoundError(str(entry.monster_instance_id))
            seen_refs: set[str] = set()
            for casting in monster_casting_sources(monster.rules_snapshot):
                candidates = casting.get("spells")
                if not isinstance(candidates, (list, tuple)):
                    continue
                for candidate in candidates:
                    spell_ref = monster_spell_ref(candidate)
                    if spell_ref is None or spell_ref in seen_refs:
                        continue
                    seen_refs.add(spell_ref)
                    spell_entry = self.registry.get(spell_ref)
                    spell_level = int(spell_entry.data.get("level", 0))
                    castable_levels = []
                    levels = (0,) if spell_level == 0 else range(spell_level, 10)
                    for slot_level in levels:
                        try:
                            resolve_monster_spell_source(
                                rules_snapshot=monster.rules_snapshot,
                                resources=monster.resources,
                                spell_ref=spell_ref,
                                spell_level=spell_level,
                                slot_level=slot_level,
                            )
                        except ValueError:
                            continue
                        castable_levels.append(slot_level)
                    if castable_levels:
                        views.append(
                            self._castable_spell_view(
                                spell_ref,
                                profile_id=None,
                                castable_slot_levels=tuple(castable_levels),
                            )
                        )
        else:
            raise CombatSpellStateConflictError(
                f"Unsupported caster kind: {entry.subject_kind}"
            )
        return tuple(views)

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
    "CastableSpellView",
    "CastSpellInput",
    "CombatSpellNotFoundError",
    "CombatSpellService",
    "CombatSpellStateConflictError",
    "ProposeAoeSpellInput",
    "ResolveAoeSpellInput",
    "SpellCastView",
]
