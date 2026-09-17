from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.content.identity import parse_stable_key
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, CharacterState, SpellcastingProfile
from app.domain.combat.concentration_triggers import monster_save_modifier
from app.domain.combat.effect_resolver import DurationKind, DurationSpec, EffectSpec
from app.domain.combat.lifecycle import CombatRepository
from app.domain.combat.resolution import DamageRollPart, DamageType, RollMode
from app.domain.combat.spell_resolver import SaveDamageMode, SpellCastMode
from app.domain.combat.spell_resources import (
    authorize_character_spell,
    resolve_monster_spell_source,
)
from app.domain.rules.abilities import (
    ability_modifier,
    effective_ability_score,
)
from app.domain.rules.armor_class import calculate_armor_class
from app.domain.rules.proficiency import total_character_level
from app.domain.rules.spellcasting import (
    spell_attack_modifier,
    spell_save_dc,
    spellcasting_ability,
)
from app.domain.rooms.rolls import FormalRollSource, RollModifierMode, RollRequestType, RollService
from app.domain.rooms.table_events import TableActorContext
from app.persistence.combat.lifecycle import StoredCombatEntry
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.spells import StoredAoeSpellAction
from app.persistence.characters import CharacterRepository


_DICE_RE = re.compile(r"^\s*(?P<count>\d+)d(?P<size>\d+)(?P<flat>[+-]\d+)?\s*$", re.IGNORECASE)
_HEAL_MOD_RE = re.compile(r"^\s*(?P<count>\d+)d(?P<size>\d+)(?:\s*\+\s*(?:MOD|(?P<flat>\d+)))?\s*$", re.IGNORECASE)

SPELL_CONDITIONS: dict[str, str] = {
    "hold-person": "paralyzed",
    "hold-monster": "paralyzed",
    "blindness-deafness": "blinded",
    "fear": "frightened",
    "hypnotic-pattern": "incapacitated",
    "web": "restrained",
    "grease": "prone",
    "sleep": "unconscious",
}


def resolve_character_profile(
    build: CharacterBuild,
    state: CharacterState,
    spell_ref: str,
    requested_profile_id: str | None = None,
) -> SpellcastingProfile:
    if requested_profile_id is not None:
        profile = next((p for p in build.spellcasting_profiles if p.profile_id == requested_profile_id), None)
        if profile is None:
            raise ValueError(f"Spellcasting profile '{requested_profile_id}' not found")
        return profile

    matching: list[SpellcastingProfile] = []
    for p in build.spellcasting_profiles:
        accesses = [
            entry
            for entry in build.spell_access_entries
            if entry.spell_key == spell_ref
            and (
                entry.source_key == p.source_key
                or (entry.source_type == "class" and entry.source_key == p.class_ref)
            )
        ]
        if accesses:
            matching.append(p)

    if len(matching) == 1:
        return matching[0]
    if len(matching) == 0:
        if len(build.spellcasting_profiles) == 1:
            return build.spellcasting_profiles[0]
        raise ValueError(f"No spellcasting profile found for spell '{spell_ref}'")

    prepared_matches = [
        p
        for p in matching
        if any(
            item.source_profile_id == p.profile_id and item.spell_key == spell_ref
            for item in state.prepared_spells
        )
    ]
    if len(prepared_matches) == 1:
        return prepared_matches[0]

    return matching[0]


@dataclass(frozen=True)
class ResolvedSpellCast:
    spell_ref: str
    spell_level: int
    slot_level: int
    profile_id: str | None
    cast_mode: SpellCastMode
    attack_modifier: int | None
    save_dc: int | None
    save_ability_ref: str | None
    save_damage_mode: SaveDamageMode
    concentration: bool
    damage_parts: tuple[DamageRollPart, ...]
    healing_amount: int
    apply_effects: tuple[EffectSpec, ...]
    target_ac: int | None
    save_modifier: int | None
    attack_d20s: tuple[int, ...]
    save_d20: int | None
    target_seat_id: UUID | None


class SpellDefinitionResolver:
    """Authoritative adapter translating ContentRegistry spell data and combatant stats into engine specs."""

    def __init__(
        self,
        *,
        character_repository: CharacterRepository,
        monster_repository: MonsterRepository,
        combat_repository: CombatRepository,
        roll_service: RollService,
        registry: ContentRegistry,
    ) -> None:
        self.character_repository = character_repository
        self.monster_repository = monster_repository
        self.combat_repository = combat_repository
        self.roll_service = roll_service
        self.registry = registry

    def _target_ac(self, target_entry: StoredCombatEntry) -> int:
        if target_entry.subject_kind == "character":
            if target_entry.character_id is None:
                raise ValueError("Character entry has no character_id")
            loaded = self.character_repository.load_character(target_entry.character_id)
            return calculate_armor_class(loaded.build, loaded.state, self.registry)
        if target_entry.subject_kind == "monster":
            if target_entry.monster_instance_id is None:
                raise ValueError("Monster entry has no monster_instance_id")
            monster = self.monster_repository.get_instance(target_entry.monster_instance_id)
            if monster is None:
                raise LookupError(str(target_entry.monster_instance_id))
            return int(dict(monster.rules_snapshot or {})["armor_class"])
        raise ValueError(f"Unsupported target kind: {target_entry.subject_kind}")

    def target_save_modifier(self, target_entry: StoredCombatEntry, ability_ref: str) -> int:
        clean_ref = ability_ref.split(":")[-1]
        if target_entry.subject_kind == "character":
            if target_entry.character_id is None:
                raise ValueError("Character entry has no character_id")
            return self.roll_service.modifier_resolver.modifier_for(
                character_id=target_entry.character_id,
                request_type=RollRequestType.SAVING_THROW,
                ability_ref=clean_ref,
                skill_ref=None,
            )
        if target_entry.subject_kind == "monster":
            if target_entry.monster_instance_id is None:
                raise ValueError("Monster entry has no monster_instance_id")
            monster = self.monster_repository.get_instance(target_entry.monster_instance_id)
            if monster is None:
                raise LookupError(str(target_entry.monster_instance_id))
            return monster_save_modifier(dict(monster.rules_snapshot or {}), clean_ref)
        raise ValueError(f"Unsupported target kind: {target_entry.subject_kind}")

    def resolve_cast(
        self,
        *,
        actor: TableActorContext,
        caster_entry: StoredCombatEntry,
        target_entry: StoredCombatEntry | None,
        spell_ref: str,
        slot_level: int | None,
        profile_id: str | None,
        attack_mode: RollMode,
        roll_source: FormalRollSource,
        raw_dice: tuple[int, ...] | None,
        subject_seat_id: UUID | None,
    ) -> ResolvedSpellCast:
        spell_entry = self.registry.get(spell_ref)
        spell_data = spell_entry.data
        spell_level = int(spell_data.get("level", 0))
        effective_slot_level = 0 if spell_level == 0 else (slot_level if slot_level is not None else spell_level)
        if effective_slot_level < spell_level:
            raise ValueError(f"slot_level ({effective_slot_level}) cannot be below spell level ({spell_level})")

        concentration = bool(spell_data.get("concentration", False))
        attack_type = spell_data.get("attack_type")
        dc_info = spell_data.get("dc")
        damage_info = spell_data.get("damage")
        heal_info = spell_data.get("heal_at_slot_level")

        if attack_type:
            cast_mode = SpellCastMode.ATTACK
            save_ability_ref = None
            save_damage_mode = SaveDamageMode.NONE
        elif dc_info:
            cast_mode = SpellCastMode.SAVE
            dc_type = dc_info.get("dc_type", {})
            save_ability_index = dc_type.get("index", "dex").lower()
            save_ability_ref = f"srd5.1:ability:{save_ability_index}"
            save_damage_mode = (
                SaveDamageMode.HALF if dc_info.get("dc_success") == "half" else SaveDamageMode.NONE
            )
        elif heal_info:
            cast_mode = SpellCastMode.HEAL
            save_ability_ref = None
            save_damage_mode = SaveDamageMode.NONE
        else:
            cast_mode = SpellCastMode.UTILITY
            save_ability_ref = None
            save_damage_mode = SaveDamageMode.NONE

        effective_profile_id: str | None = None
        caster_ability_mod = 0
        caster_level = 1

        if caster_entry.subject_kind == "character":
            if caster_entry.character_id is None:
                raise ValueError("Character entry has no character_id")
            character = self.character_repository.load_character(caster_entry.character_id)
            profile = resolve_character_profile(
                character.build,
                character.state,
                spell_ref,
                requested_profile_id=profile_id,
            )
            effective_profile_id = profile.profile_id
            authorize_character_spell(
                build=character.build,
                state=character.state,
                profile_id=profile.profile_id,
                spell_ref=spell_ref,
                spell_level=spell_level,
                slot_level=effective_slot_level,
            )
            attack_modifier = (
                spell_attack_modifier(character.build, profile.source_key, self.registry) or 0
            )
            save_dc = spell_save_dc(character.build, profile.source_key, self.registry) or 10
            ability_name = spellcasting_ability(profile.source_key, self.registry)
            caster_ability_mod = (
                ability_modifier(effective_ability_score(character.build, ability_name))
                if ability_name
                else 0
            )
            caster_level = total_character_level(character.build)

        elif caster_entry.subject_kind == "monster":
            if caster_entry.monster_instance_id is None:
                raise ValueError("Monster entry has no monster_instance_id")
            monster = self.monster_repository.get_instance(caster_entry.monster_instance_id)
            if monster is None:
                raise LookupError(str(caster_entry.monster_instance_id))
            source = resolve_monster_spell_source(
                rules_snapshot=monster.rules_snapshot,
                resources=monster.resources,
                spell_ref=spell_ref,
                spell_level=spell_level,
                slot_level=effective_slot_level,
            )
            attack_modifier = source.attack_bonus
            save_dc = source.save_dc
            effective_profile_id = None
        else:
            raise ValueError(f"Unsupported caster kind: {caster_entry.subject_kind}")

        target_ac: int | None = None
        target_seat_id: UUID | None = None
        save_modifier: int | None = None

        if target_entry is not None:
            if cast_mode is SpellCastMode.ATTACK:
                target_ac = self._target_ac(target_entry)
            if cast_mode is SpellCastMode.SAVE and save_ability_ref:
                save_modifier = self.target_save_modifier(target_entry, save_ability_ref)
            if target_entry.subject_kind == "character" and target_entry.character_id is not None:
                target_seat_id = self.combat_repository.controlling_seat_for_character(
                    campaign_id=actor.campaign_id,
                    session_id=actor.session_id,
                    character_id=target_entry.character_id,
                )

        damage_parts: list[DamageRollPart] = []
        if damage_info:
            damage_type_str = damage_info.get("damage_type", {}).get("index", "fire")
            damage_type = DamageType(damage_type_str)
            formula_str: str | None = None
            if effective_slot_level > 0 and "damage_at_slot_level" in damage_info:
                formula_str = damage_info["damage_at_slot_level"].get(str(effective_slot_level))
            elif "damage_at_character_level" in damage_info:
                table = damage_info["damage_at_character_level"]
                tiers = sorted([int(k) for k in table.keys() if k.isdigit()])
                if tiers:
                    matching_tier = max([t for t in tiers if t <= caster_level], default=tiers[0])
                    formula_str = table.get(str(matching_tier))

            if formula_str:
                m = _DICE_RE.match(formula_str)
                if m:
                    count = int(m.group("count"))
                    size = int(m.group("size"))
                    flat = int(m.group("flat") or 0)
                    dice = tuple(self.roll_service.engine.rng.randint(1, size) for _ in range(count))
                    damage_parts.append(
                        DamageRollPart(
                            damage_type=damage_type,
                            dice=dice,
                            flat_modifier=flat,
                        )
                    )

        healing_amount = 0
        if heal_info and effective_slot_level > 0:
            formula_str = heal_info.get(str(effective_slot_level))
            if formula_str:
                m = _HEAL_MOD_RE.match(formula_str)
                if m:
                    count = int(m.group("count"))
                    size = int(m.group("size"))
                    flat = int(m.group("flat") or 0) if m.group("flat") else 0
                    dice = [self.roll_service.engine.rng.randint(1, size) for _ in range(count)]
                    add_mod = caster_ability_mod if "MOD" in formula_str.upper() else 0
                    healing_amount = sum(dice) + flat + add_mod

        apply_effects: list[EffectSpec] = []
        spell_slug = spell_entry.index
        if spell_slug in SPELL_CONDITIONS:
            cond_tag = SPELL_CONDITIONS[spell_slug]
            duration = (
                DurationSpec(DurationKind.UNTIL_CONCENTRATION_ENDS)
                if concentration
                else DurationSpec(DurationKind.ROUNDS, 10)
            )
            apply_effects.append(
                EffectSpec(
                    effect_type="condition",
                    tag=cond_tag,
                    duration=duration,
                    source_ref=spell_ref,
                )
            )

        attack_d20s: tuple[int, ...] = ()
        if cast_mode is SpellCastMode.ATTACK:
            allow_physical_attack = (
                roll_source is FormalRollSource.PHYSICAL
                and (actor.is_current_dm or (subject_seat_id is not None and actor.seat_id == subject_seat_id))
            )
            audit = self.roll_service.engine.d20(
                mode=RollModifierMode(attack_mode.value),
                base_modifier=0,
                flat_adjustment=attack_modifier or 0,
                physical_raw_dice=raw_dice if allow_physical_attack else None,
            )
            attack_d20s = audit.raw_dice

        save_d20: int | None = None
        if cast_mode is SpellCastMode.SAVE and target_entry is not None:
            allow_physical_save = (
                roll_source is FormalRollSource.PHYSICAL
                and (actor.is_current_dm or (target_seat_id is not None and actor.seat_id == target_seat_id))
            )
            audit = self.roll_service.engine.d20(
                mode=RollModifierMode.NORMAL,
                base_modifier=0,
                flat_adjustment=save_modifier or 0,
                physical_raw_dice=raw_dice if allow_physical_save else None,
            )
            save_d20 = audit.kept_dice[0] if audit.kept_dice else audit.total - (save_modifier or 0)

        return ResolvedSpellCast(
            spell_ref=spell_ref,
            spell_level=spell_level,
            slot_level=effective_slot_level,
            profile_id=effective_profile_id,
            cast_mode=cast_mode,
            attack_modifier=attack_modifier if cast_mode is SpellCastMode.ATTACK else None,
            save_dc=save_dc if cast_mode is SpellCastMode.SAVE else None,
            save_ability_ref=save_ability_ref,
            save_damage_mode=save_damage_mode,
            concentration=concentration,
            damage_parts=tuple(damage_parts),
            healing_amount=healing_amount,
            apply_effects=tuple(apply_effects),
            target_ac=target_ac,
            save_modifier=save_modifier,
            attack_d20s=attack_d20s,
            save_d20=save_d20,
            target_seat_id=target_seat_id,
        )

    def resolve_aoe_proposal(
        self,
        *,
        actor: TableActorContext,
        caster_entry: StoredCombatEntry,
        spell_ref: str,
        slot_level: int | None,
        profile_id: str | None,
    ) -> tuple[int, int, str, str, int, SaveDamageMode]:
        spell_entry = self.registry.get(spell_ref)
        spell_data = spell_entry.data
        spell_level = int(spell_data.get("level", 0))
        effective_slot_level = 0 if spell_level == 0 else (slot_level if slot_level is not None else spell_level)
        if effective_slot_level < spell_level:
            raise ValueError(f"slot_level ({effective_slot_level}) cannot be below spell level ({spell_level})")

        dc_info = spell_data.get("dc")
        if not dc_info:
            raise ValueError(f"Spell '{spell_ref}' does not have a saving throw DC definition")

        dc_type = dc_info.get("dc_type", {})
        save_ability_index = dc_type.get("index", "dex").lower()
        save_ability_ref = f"srd5.1:ability:{save_ability_index}"
        save_damage_mode = (
            SaveDamageMode.HALF if dc_info.get("dc_success") == "half" else SaveDamageMode.NONE
        )

        if caster_entry.subject_kind == "character":
            if caster_entry.character_id is None:
                raise ValueError("Character entry has no character_id")
            character = self.character_repository.load_character(caster_entry.character_id)
            profile = resolve_character_profile(
                character.build,
                character.state,
                spell_ref,
                requested_profile_id=profile_id,
            )
            effective_profile_id = profile.profile_id
            authorize_character_spell(
                build=character.build,
                state=character.state,
                profile_id=profile.profile_id,
                spell_ref=spell_ref,
                spell_level=spell_level,
                slot_level=effective_slot_level,
            )
            save_dc = spell_save_dc(character.build, profile.source_key, self.registry) or 10
        elif caster_entry.subject_kind == "monster":
            if caster_entry.monster_instance_id is None:
                raise ValueError("Monster entry has no monster_instance_id")
            monster = self.monster_repository.get_instance(caster_entry.monster_instance_id)
            if monster is None:
                raise LookupError(str(caster_entry.monster_instance_id))
            source = resolve_monster_spell_source(
                rules_snapshot=monster.rules_snapshot,
                resources=monster.resources,
                spell_ref=spell_ref,
                spell_level=spell_level,
                slot_level=effective_slot_level,
            )
            save_dc = source.save_dc
            effective_profile_id = "monster"
        else:
            raise ValueError(f"Unsupported caster kind: {caster_entry.subject_kind}")

        return (
            spell_level,
            effective_slot_level,
            effective_profile_id,
            save_ability_ref,
            save_dc,
            save_damage_mode,
        )

    def resolve_aoe_defaults(
        self,
        *,
        actor: TableActorContext,
        existing: StoredAoeSpellAction,
        confirmed_target_ids: tuple[UUID, ...],
        dm_save_modifiers: tuple[tuple[UUID, int], ...],
        dm_save_d20s: tuple[tuple[UUID, int], ...],
        dm_damage_parts: tuple[DamageRollPart, ...],
        get_active_entry: Any,
    ) -> tuple[dict[UUID, int], dict[UUID, int], tuple[DamageRollPart, ...], dict[UUID, UUID | None]]:
        save_modifiers = dict(dm_save_modifiers)
        save_d20s = dict(dm_save_d20s)
        target_seat_ids: dict[UUID, UUID | None] = {}

        for target_id in confirmed_target_ids:
            target_entry = get_active_entry(actor, target_id)
            if target_id not in save_modifiers:
                save_modifiers[target_id] = self.target_save_modifier(target_entry, existing.save_ability_ref)
            if target_id not in save_d20s:
                audit = self.roll_service.engine.d20(
                    mode=RollModifierMode.NORMAL,
                    base_modifier=0,
                    flat_adjustment=save_modifiers[target_id],
                )
                save_d20s[target_id] = (
                    audit.kept_dice[0] if audit.kept_dice else audit.total - save_modifiers[target_id]
                )

            if target_entry.subject_kind == "character" and target_entry.character_id is not None:
                target_seat_ids[target_id] = self.combat_repository.controlling_seat_for_character(
                    campaign_id=actor.campaign_id,
                    session_id=actor.session_id,
                    character_id=target_entry.character_id,
                )
            else:
                target_seat_ids[target_id] = None

        if dm_damage_parts:
            damage_parts = dm_damage_parts
        else:
            damage_parts_list: list[DamageRollPart] = []
            spell_entry = self.registry.get(existing.spell_ref)
            damage_info = spell_entry.data.get("damage")
            if damage_info:
                damage_type_str = damage_info.get("damage_type", {}).get("index", "fire")
                damage_type = DamageType(damage_type_str)
                formula_str: str | None = None
                if existing.slot_level > 0 and "damage_at_slot_level" in damage_info:
                    formula_str = damage_info["damage_at_slot_level"].get(str(existing.slot_level))
                if formula_str:
                    m = _DICE_RE.match(formula_str)
                    if m:
                        count = int(m.group("count"))
                        size = int(m.group("size"))
                        flat = int(m.group("flat") or 0)
                        dice = tuple(self.roll_service.engine.rng.randint(1, size) for _ in range(count))
                        damage_parts_list.append(
                            DamageRollPart(
                                damage_type=damage_type,
                                dice=dice,
                                flat_modifier=flat,
                            )
                        )
            damage_parts = tuple(damage_parts_list)

        return save_modifiers, save_d20s, damage_parts, target_seat_ids
