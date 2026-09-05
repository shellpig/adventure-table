from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.content.registry import ContentRegistry
from app.domain.character.schemas import PersistedCharacter, ResourceCounter, RoleplayProfile
from app.domain.character.validation import derive_hit_dice_totals
from app.domain.rules.abilities import ABILITY_NAMES, ability_modifier, effective_ability_score
from app.domain.rules.armor_class import calculate_armor_class
from app.domain.rules.artificer_dto import ArtificerSummaryDTO, build_artificer_summary
from app.domain.rules.hit_points import calculate_max_hp
from app.domain.rules.m01m_ancestry import (
    effective_feature_modes,
    effective_movement,
    feature_mode_definitions,
    racial_spell_runtime_metadata,
)
from app.domain.rules.proficiency import class_level, proficiency_bonus, total_character_level
from app.domain.rules.skills import (
    all_skill_modifiers,
    all_skill_proficiencies,
    passive_investigation,
    passive_perception,
    saving_throw_modifiers,
)
from app.domain.rules.spellcasting import (
    spell_attack_modifier,
    spell_is_on_class_list,
    spell_save_dc,
    spellcasting_ability,
)


class SheetModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AbilityDTO(SheetModel):
    score: int
    modifier: int


class ClassLevelDTO(SheetModel):
    class_ref: str
    name: str
    level: int


class HitDieDTO(SheetModel):
    die: str
    total: int
    available: int


class NamedReferenceDTO(SheetModel):
    key: str
    name: str


class ConditionDTO(SheetModel):
    condition_ref: str
    name: str
    note: str | None = None


class SpellAccessDTO(SheetModel):
    entry_id: str
    spell_key: str
    name: str
    source_type: str
    source_key: str
    access_type: str
    prepared: bool
    source_profile_id: str | None = None
    source_access_entry_id: str | None = None
    cast_at_level: int | None = None
    waive_components: tuple[str, ...] = ()
    casting_modifiers: tuple[str, ...] = ()
    uses_spell_slot: bool | None = None


class SpellcastingDTO(SheetModel):
    source_key: str
    source_name: str
    ability: str
    save_dc: int
    attack_modifier: int


class InventoryDTO(SheetModel):
    entry_id: str
    item_ref: str
    name: str
    quantity: int
    equipped: bool
    carried: bool
    rules: dict[str, Any]


class FeatureModeDTO(SheetModel):
    key: str
    source_feature_ref: str
    options: tuple[str, ...]
    default: str
    change_timing: str


class CharacterSheetDTO(SheetModel):
    character_id: UUID
    current_version_id: UUID
    name: str
    ruleset: str
    version_no: int
    total_level: int
    classes: list[ClassLevelDTO]
    proficiency_bonus: int
    abilities: dict[str, AbilityDTO]
    saving_throws: dict[str, int]
    skills: dict[str, int]
    skill_proficiencies: tuple[str, ...] = ()
    passive_perception: int
    passive_investigation: int
    initiative_modifier: int
    armor_class: int
    walking_speed: int
    swim_speed: int | None = None
    climb_speed: int | None = None
    fly_speed: int | None = None
    max_hp: int
    current_hp: int
    temporary_hp: int
    hit_dice: list[HitDieDTO]
    features: list[NamedReferenceDTO]
    feature_modes: dict[str, str]
    feature_mode_definitions: list[FeatureModeDTO]
    conditions: list[ConditionDTO]
    spells: list[SpellAccessDTO]
    spellcasting: list[SpellcastingDTO]
    spell_slots: dict[int, ResourceCounter]
    resources: dict[str, ResourceCounter]
    inventory: list[InventoryDTO]
    artificer: ArtificerSummaryDTO | None = None
    roleplay_profile: RoleplayProfile


def build_character_sheet(
    character: PersistedCharacter,
    registry: ContentRegistry,
) -> CharacterSheetDTO:
    build = character.build
    state = character.state
    total_level = total_character_level(build)

    ordered_classes = list(dict.fromkeys(build.class_progression))
    classes = [
        ClassLevelDTO(
            class_ref=class_ref,
            name=registry.get(class_ref).name,
            level=class_level(build, class_ref),
        )
        for class_ref in ordered_classes
    ]

    abilities = {
        name: AbilityDTO(
            score=effective_ability_score(build, name),
            modifier=ability_modifier(effective_ability_score(build, name)),
        )
        for name in ABILITY_NAMES
    }

    movement = effective_movement(build, state, registry)

    totals = derive_hit_dice_totals(build, registry)
    hit_dice = [
        HitDieDTO(
            die=die,
            total=total,
            available=state.hit_dice_state.get(die, 0),
        )
        for die, total in totals.items()
    ]

    legacy_prepared = set(state.prepared_spell_entry_ids)
    canonical_prepared = {
        (selection.source_profile_id, selection.spell_key): selection
        for selection in state.prepared_spells
    }
    profiles_by_source: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for profile in build.spellcasting_profiles:
        profiles_by_source[(profile.source_type, profile.source_key)].append(profile)

    spells: list[SpellAccessDTO] = []
    covered_profile_spells: set[tuple[str, str]] = set()
    for access in build.spell_access_entries:
        matching_profiles = profiles_by_source.get((access.source_type, access.source_key), [])
        profile = next(
            (
                candidate
                for candidate in matching_profiles
                if access.access_type != "spellbook" or candidate.access_model == "spellbook"
            ),
            None,
        )
        pair = (profile.profile_id, access.spell_key) if profile is not None else None
        if pair is not None:
            covered_profile_spells.add(pair)
        spell = registry.get(access.spell_key)
        runtime = racial_spell_runtime_metadata(access, registry)
        spells.append(
            SpellAccessDTO(
                entry_id=access.entry_id,
                spell_key=access.spell_key,
                name=spell.name,
                source_type=access.source_type,
                source_key=access.source_key,
                access_type=access.access_type,
                prepared=(
                    access.access_type == "always_prepared"
                    or (pair is not None and pair in canonical_prepared)
                    or access.entry_id in legacy_prepared
                ),
                source_profile_id=profile.profile_id if profile is not None else None,
                source_access_entry_id=(
                    access.entry_id
                    if profile is not None and access.access_type == "spellbook"
                    else None
                ),
                cast_at_level=runtime.cast_at_level if runtime is not None else None,
                waive_components=runtime.waive_components if runtime is not None else (),
                casting_modifiers=runtime.casting_modifiers if runtime is not None else (),
                uses_spell_slot=runtime.uses_spell_slot if runtime is not None else None,
            )
        )

    # Full-list prepared casters (Cleric/Druid-style) do not have one Build
    # access row per eligible spell. Expose their prepareable list directly from
    # the source-aware class-list contract so Current State remains canonical.
    for profile in build.spellcasting_profiles:
        if profile.access_model != "prepared":
            continue
        for spell in registry.list_kind("spell"):
            level = spell.data.get("level")
            if not isinstance(level, int) or level < 1 or level > profile.max_spell_level:
                continue
            if not spell_is_on_class_list(spell.key, profile.class_ref, registry):
                continue
            pair = (profile.profile_id, spell.key)
            if pair in covered_profile_spells:
                continue
            spells.append(
                SpellAccessDTO(
                    entry_id=f"prepared:{profile.profile_id}:{spell.key}",
                    spell_key=spell.key,
                    name=spell.name,
                    source_type=profile.source_type,
                    source_key=profile.source_key,
                    access_type="prepared",
                    prepared=pair in canonical_prepared,
                    source_profile_id=profile.profile_id,
                    source_access_entry_id=None,
                )
            )
            covered_profile_spells.add(pair)

    source_keys = list(
        dict.fromkeys(
            [profile.source_key for profile in build.spellcasting_profiles]
            + [
                entry.source_key
                for entry in build.spell_access_entries
                if entry.source_type in {"class", "subclass"}
            ]
        )
    )
    spellcasting = []
    for source_key in source_keys:
        ability = spellcasting_ability(source_key, registry)
        save_dc = spell_save_dc(build, source_key, registry)
        attack = spell_attack_modifier(build, source_key, registry)
        if ability is None or save_dc is None or attack is None:
            continue
        source = registry.get(source_key)
        spellcasting.append(
            SpellcastingDTO(
                source_key=source_key,
                source_name=source.name,
                ability=ability,
                save_dc=save_dc,
                attack_modifier=attack,
            )
        )

    sheet_feature_refs = tuple(dict.fromkeys((*build.feature_refs, *build.feat_refs)))
    mode_definitions = feature_mode_definitions(build, registry)
    return CharacterSheetDTO(
        character_id=character.id,
        current_version_id=character.current_version_id,
        name=character.name,
        ruleset=character.ruleset,
        version_no=character.version_no,
        total_level=total_level,
        classes=classes,
        proficiency_bonus=proficiency_bonus(total_level),
        abilities=abilities,
        saving_throws=saving_throw_modifiers(build),
        skills=all_skill_modifiers(build, registry),
        skill_proficiencies=all_skill_proficiencies(build, registry),
        passive_perception=passive_perception(build, registry),
        passive_investigation=passive_investigation(build, registry),
        initiative_modifier=abilities["dexterity"].modifier,
        armor_class=calculate_armor_class(build, state, registry),
        walking_speed=movement.walk,
        swim_speed=movement.swim,
        climb_speed=movement.climb,
        fly_speed=movement.fly,
        max_hp=calculate_max_hp(build),
        current_hp=state.current_hp,
        temporary_hp=state.temporary_hp,
        hit_dice=hit_dice,
        features=[
            NamedReferenceDTO(key=key, name=registry.get(key).name)
            for key in sheet_feature_refs
        ],
        feature_modes={
            **state.feature_modes,
            **effective_feature_modes(build, state, registry),
        },
        feature_mode_definitions=[
            FeatureModeDTO(
                key=definition.key,
                source_feature_ref=definition.source_feature_ref,
                options=definition.options,
                default=definition.default,
                change_timing=definition.change_timing,
            )
            for definition in mode_definitions
        ],
        conditions=[
            ConditionDTO(
                condition_ref=entry.condition_ref,
                name=registry.get(entry.condition_ref).name,
                note=entry.note,
            )
            for entry in state.conditions
        ],
        spells=spells,
        spellcasting=spellcasting,
        spell_slots=state.spell_slots,
        resources=state.resources,
        inventory=[
            InventoryDTO(
                entry_id=entry.entry_id,
                item_ref=entry.item_ref,
                name=registry.get(entry.item_ref).name,
                quantity=entry.quantity,
                equipped=entry.equipped,
                carried=entry.carried,
                rules=registry.get(entry.item_ref).data,
            )
            for entry in state.inventory_state
        ],
        artificer=build_artificer_summary(build, state, registry),
        roleplay_profile=build.roleplay_profile,
    )
