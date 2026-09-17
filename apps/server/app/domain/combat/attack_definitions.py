from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from app.content.registry import ContentRegistry
from app.domain.character.schemas import PersistedCharacter
from app.domain.combat.resolution import (
    AttackKind,
    DamageFormulaPart,
    DamageType,
    ModifierSource,
    ResolvedAttack,
)
from app.domain.rules.abilities import ability_modifier, effective_ability_score
from app.domain.rules.armor_class import calculate_armor_class
from app.persistence.characters import CharacterRepository
from app.persistence.combat.lifecycle import StoredCombatEntry
from app.persistence.combat.repository import MonsterRepository, StoredMonsterInstance


_DICE_RE = re.compile(r"^\s*(?P<count>\d+)d(?P<size>\d+)(?P<flat>[+-]\d+)?\s*$", re.IGNORECASE)


class AttackDefinitionNotFoundError(LookupError):
    pass


class AttackDefinitionInvalidError(ValueError):
    pass


@dataclass(frozen=True)
class AvailableAttack:
    source_ref: str
    name: str
    attack_bonus: int
    attack_kind: AttackKind
    damage_parts: tuple[DamageFormulaPart, ...]


def _damage_type(value: object) -> DamageType:
    if isinstance(value, dict):
        for key in ("index", "name", "key"):
            if key in value:
                return _damage_type(value[key])
    if isinstance(value, str):
        candidate = value.strip().casefold().replace("_", "-")
        if candidate.count(":") == 2:
            candidate = candidate.rsplit(":", 1)[-1]
        candidate = candidate.removesuffix(" damage")
        try:
            parsed = DamageType(candidate)
        except ValueError as exc:
            raise AttackDefinitionInvalidError(f"unsupported damage type: {value}") from exc
        if parsed is DamageType.UNTYPED:
            raise AttackDefinitionInvalidError("attack definitions cannot use untyped damage")
        return parsed
    raise AttackDefinitionInvalidError("damage type reference is missing")


def _dice_formula(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise AttackDefinitionInvalidError("damage dice formula must be a string")
    match = _DICE_RE.match(value)
    if match is None:
        raise AttackDefinitionInvalidError(f"unsupported damage dice formula: {value}")
    return (
        int(match.group("count")),
        int(match.group("size")),
        int(match.group("flat") or 0),
    )


def _property_indexes(data: dict[str, object]) -> set[str]:
    result: set[str] = set()
    raw = data.get("properties")
    if not isinstance(raw, list):
        return result
    for item in raw:
        if isinstance(item, dict):
            for key in ("index", "name"):
                value = item.get(key)
                if isinstance(value, str):
                    result.add(value.strip().casefold().replace(" ", "-"))
        elif isinstance(item, str):
            result.add(item.strip().casefold().replace(" ", "-"))
    return result


def _proficiency_bonus(level: int) -> int:
    return 2 + (level - 1) // 4


def _weapon_is_proficient(character: PersistedCharacter, item_index: str, category: str) -> bool:
    proficiency_indexes = {ref.rsplit(":", 1)[-1] for ref in character.build.proficiencies}
    normalized_category = category.strip().casefold()
    broad = {
        "simple": {"all-simple-weapons", "simple-weapons"},
        "martial": {"all-martial-weapons", "martial-weapons"},
    }.get(normalized_category, set())
    if proficiency_indexes & broad:
        return True
    candidates = {
        item_index,
        f"{item_index}s",
        item_index.removesuffix("s"),
    }
    return bool(proficiency_indexes & candidates)


def _infusion_modifiers(
    character: PersistedCharacter,
    inventory_entry_id: str,
    registry: ContentRegistry,
) -> tuple[int, int, tuple[ModifierSource, ...]]:
    attack_bonus = 0
    damage_bonus = 0
    sources: list[ModifierSource] = []
    active = next(
        (entry for entry in character.state.active_infusions if entry.inventory_entry_id == inventory_entry_id),
        None,
    )
    if active is None:
        return 0, 0, ()
    content = registry.get_optional(active.infusion_ref)
    if content is None:
        return 0, 0, ()
    modifiers = content.data.get("modifiers")
    if not isinstance(modifiers, list):
        return 0, 0, ()
    for raw in modifiers:
        if not isinstance(raw, dict) or not isinstance(raw.get("value"), int):
            continue
        value = int(raw["value"])
        if raw.get("kind") == "attack":
            attack_bonus += value
            sources.append(ModifierSource(source=f"{active.infusion_ref}:attack", value=value))
        elif raw.get("kind") == "damage":
            damage_bonus += value
            sources.append(ModifierSource(source=f"{active.infusion_ref}:damage", value=value))
    return attack_bonus, damage_bonus, tuple(sources)


class AttackDefinitionResolver:
    """Normalize Character inventory weapons and Monster snapshot attacks."""

    def __init__(
        self,
        character_repository: CharacterRepository,
        monster_repository: MonsterRepository,
        registry: ContentRegistry,
    ) -> None:
        self.character_repository = character_repository
        self.monster_repository = monster_repository
        self.registry = registry

    def _character(self, entry: StoredCombatEntry) -> PersistedCharacter:
        if entry.character_id is None:
            raise AttackDefinitionNotFoundError("Character CombatEntry has no Character identity")
        return self.character_repository.load_character(entry.character_id)

    def _monster(self, entry: StoredCombatEntry) -> StoredMonsterInstance:
        if entry.monster_instance_id is None:
            raise AttackDefinitionNotFoundError("Monster CombatEntry has no Monster identity")
        monster = self.monster_repository.get_instance(entry.monster_instance_id)
        if monster is None:
            raise AttackDefinitionNotFoundError(str(entry.monster_instance_id))
        return monster

    def character_attacks(self, entry: StoredCombatEntry) -> tuple[ResolvedAttack, ...]:
        character = self._character(entry)
        attacks: list[ResolvedAttack] = []
        for inventory in character.state.inventory_state:
            content = self.registry.get_optional(inventory.item_ref)
            if content is None:
                continue
            data = dict(content.data)
            damage = data.get("damage")
            weapon_range = data.get("weapon_range")
            if not isinstance(damage, dict) or not isinstance(weapon_range, str):
                continue
            count, size, intrinsic_flat = _dice_formula(damage.get("damage_dice"))
            properties = _property_indexes(data)
            attack_kind = AttackKind.RANGED if weapon_range.casefold() == "ranged" else AttackKind.MELEE
            strength_mod = ability_modifier(effective_ability_score(character.build, "strength"))
            dexterity_mod = ability_modifier(effective_ability_score(character.build, "dexterity"))
            if attack_kind is AttackKind.RANGED:
                ability_name = "dexterity"
                ability_mod = dexterity_mod
            elif "finesse" in properties:
                ability_name = "dexterity" if dexterity_mod > strength_mod else "strength"
                ability_mod = max(strength_mod, dexterity_mod)
            else:
                ability_name = "strength"
                ability_mod = strength_mod

            category = str(data.get("weapon_category") or "")
            proficient = _weapon_is_proficient(character, content.index, category)
            proficiency = _proficiency_bonus(character.build.character_level) if proficient else 0
            infusion_attack, infusion_damage, infusion_sources = _infusion_modifiers(
                character,
                inventory.entry_id,
                self.registry,
            )
            sources = [ModifierSource(source=f"ability:{ability_name}", value=ability_mod)]
            if proficient:
                sources.append(ModifierSource(source="proficiency_bonus", value=proficiency))
            sources.extend(source for source in infusion_sources if source.source.endswith(":attack"))
            attacks.append(
                ResolvedAttack(
                    source_ref=f"inventory:{inventory.entry_id}",
                    name=content.name,
                    attack_bonus=ability_mod + proficiency + infusion_attack,
                    attack_kind=attack_kind,
                    damage_parts=(
                        DamageFormulaPart(
                            damage_type=_damage_type(damage.get("damage_type")),
                            dice_count=count,
                            die_size=size,
                            flat_modifier=intrinsic_flat + ability_mod + infusion_damage,
                        ),
                    ),
                    modifier_sources=tuple(sources),
                    notes=(f"item_ref={inventory.item_ref}",),
                    content_ref=inventory.item_ref,
                    presentation_field="name",
                )
            )
        return tuple(attacks)

    def monster_attacks(self, entry: StoredCombatEntry) -> tuple[ResolvedAttack, ...]:
        monster = self._monster(entry)
        raw_actions = monster.rules_snapshot.get("actions", [])
        if not isinstance(raw_actions, list):
            return ()
        template_key = monster.template_key
        template_entry = (
            self.registry.get_optional(template_key) if template_key else None
        )
        template_actions = (
            template_entry.data.get("actions", [])
            if template_entry and isinstance(template_entry.data, dict)
            else []
        )
        attacks: list[ResolvedAttack] = []
        for index, raw in enumerate(raw_actions):
            if not isinstance(raw, dict) or raw.get("kind") != "attack":
                continue
            attack_bonus = raw.get("attack_bonus")
            attack_kind_raw = raw.get("attack_kind")
            damage_parts_raw = raw.get("damage_parts")
            if not isinstance(attack_bonus, int) or not isinstance(attack_kind_raw, str) or not isinstance(damage_parts_raw, list):
                continue
            damage_parts: list[DamageFormulaPart] = []
            for part in damage_parts_raw:
                if not isinstance(part, dict):
                    raise AttackDefinitionInvalidError("Monster damage part must be an object")
                count, size, flat = _dice_formula(part.get("dice"))
                damage_parts.append(
                    DamageFormulaPart(
                        damage_type=_damage_type(part.get("damage_type")),
                        dice_count=count,
                        die_size=size,
                        flat_modifier=flat,
                    )
                )
            if not damage_parts:
                continue
            kind = AttackKind.MELEE if attack_kind_raw.startswith("melee") else AttackKind.RANGED
            name = str(raw.get("name") or f"Attack {index + 1}")
            content_ref = None
            presentation_field = None
            if template_entry:
                canonical_idx: int | None = None
                if index < len(template_actions) and isinstance(template_actions[index], dict) and template_actions[index].get("name") == name:
                    canonical_idx = index
                else:
                    for c_idx, c_action in enumerate(template_actions):
                        if isinstance(c_action, dict) and c_action.get("name") == name:
                            canonical_idx = c_idx
                            break
                if canonical_idx is not None:
                    content_ref = template_key
                    presentation_field = f"data.actions.{canonical_idx}.name"
            attacks.append(
                ResolvedAttack(
                    source_ref=f"monster-action:{index}",
                    name=name,
                    attack_bonus=attack_bonus,
                    attack_kind=kind,
                    damage_parts=tuple(damage_parts),
                    modifier_sources=(
                        ModifierSource(source="monster_snapshot:attack_bonus", value=attack_bonus),
                    ),
                    notes=(f"monster_instance_id={monster.id}",),
                    content_ref=content_ref,
                    presentation_field=presentation_field,
                )
            )
        return tuple(attacks)

    def attacks_for(self, entry: StoredCombatEntry) -> tuple[ResolvedAttack, ...]:
        if entry.subject_kind == "character":
            return self.character_attacks(entry)
        if entry.subject_kind == "monster":
            return self.monster_attacks(entry)
        raise AttackDefinitionInvalidError(f"unsupported CombatEntry subject kind: {entry.subject_kind}")

    def resolve(self, entry: StoredCombatEntry, source_ref: str) -> ResolvedAttack:
        for attack in self.attacks_for(entry):
            if attack.source_ref == source_ref:
                return attack
        raise AttackDefinitionNotFoundError(source_ref)

    def armor_class_for(self, entry: StoredCombatEntry) -> int:
        if entry.subject_kind == "character":
            character = self._character(entry)
            return calculate_armor_class(character.build, character.state, self.registry)
        if entry.subject_kind == "monster":
            monster = self._monster(entry)
            value = monster.rules_snapshot.get("armor_class")
            if not isinstance(value, int):
                raise AttackDefinitionInvalidError("Monster snapshot does not contain integer armor_class")
            return value
        raise AttackDefinitionInvalidError(f"unsupported CombatEntry subject kind: {entry.subject_kind}")


__all__ = [
    "AttackDefinitionInvalidError",
    "AttackDefinitionNotFoundError",
    "AttackDefinitionResolver",
    "AvailableAttack",
]
