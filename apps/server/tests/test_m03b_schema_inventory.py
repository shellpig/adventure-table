"""M03-B — the portability inventory must stay in step with the persisted models.

The runtime walker only inspects the field names the inventory declares, so it
cannot be the thing that notices a brand-new persisted field. This test is: every
field reachable from ``CharacterBuild`` / ``CharacterState`` is either declared a
StableKey portability path or explicitly classified as carrying no content
reference. Adding, renaming or removing a persisted field fails here until the
developer classifies it, which is exactly when ``content_requirements`` coverage
should be reconsidered.
"""

from __future__ import annotations

import re
import typing

from pydantic import BaseModel

from app.domain.character.schemas import CharacterBuild, CharacterState
from app.interop.content_ref_walker import (
    BUILD_STABLE_KEY_PATHS,
    STATE_STABLE_KEY_PATHS,
)


NON_REF_BUILD_FIELDS = frozenset(
    {
        "ability_scores",
        "ability_scores.charisma",
        "ability_scores.constitution",
        "ability_scores.dexterity",
        "ability_scores.intelligence",
        "ability_scores.strength",
        "ability_scores.wisdom",
        "ancestral_legacy",
        "ancestral_legacy.retained_movement_modes",
        "character_level",
        "climb_speed",
        "content_sources",
        "feat_acquisitions",
        "feat_acquisitions.acquisition_id",
        "feat_acquisitions.selections",
        "feat_acquisitions.source_opportunity",
        "feat_resource_grants",
        "feat_resource_grants.capacity",
        "feat_resource_grants.die_size",
        "feat_resource_grants.recharge",
        "feat_resource_grants.resource_id",
        "feat_resource_grants.stacking",
        "feature_grant_sources",
        "feature_grant_sources.grant_kind",
        "fly_speed",
        "hp_progression",
        "numeric_overrides",
        "numeric_overrides.value",
        "race_variant_group_selections",
        "race_variant_group_selections.replacement_group_id",
        "race_variant_group_selections.selected_option_id",
        "roleplay_profile",
        "roleplay_profile.appearance",
        "roleplay_profile.biography",
        "roleplay_profile.bonds",
        "roleplay_profile.custom_fields",
        "roleplay_profile.flaws",
        "roleplay_profile.ideals",
        "roleplay_profile.personality_traits",
        "ruleset",
        "size",
        "spell_access_entries",
        "spell_access_entries.access_type",
        "spell_access_entries.casting_ability",
        "spell_access_entries.entry_id",
        "spell_access_entries.recharge_types",
        "spell_access_entries.rest_type",
        "spell_access_entries.source_type",
        "spell_access_entries.uses_per_rest",
        "spell_resource_pools",
        "spell_resource_pools.pool_id",
        "spell_resource_pools.pool_type",
        "spell_resource_pools.slots",
        "spell_resource_pools.slots.capacity",
        "spell_resource_pools.slots.level",
        "spell_resource_pools.source_profile_id",
        "spellcasting_profiles",
        "spellcasting_profiles.ability",
        "spellcasting_profiles.access_model",
        "spellcasting_profiles.max_spell_level",
        "spellcasting_profiles.prepared_limit",
        "spellcasting_profiles.profile_id",
        "spellcasting_profiles.resource_pool_type",
        "spellcasting_profiles.source_type",
        "starting_equipment",
        "starting_equipment.entry_id",
        "starting_equipment.quantity",
        "static_derived_modifiers",
        "static_derived_modifiers.per_level",
        "static_derived_modifiers.target",
        "static_derived_modifiers.value",
        "subclasses",
        "swim_speed",
        "walking_speed",
    }
)

NON_REF_STATE_FIELDS = frozenset(
    {
        "active_infusions",
        "active_infusions.arcane_armor_part",
        "active_infusions.inventory_entry_id",
        "active_infusions.resource",
        "conditions",
        "conditions.note",
        "current_hp",
        "feature_modes",
        "hit_dice_state",
        "inventory_state",
        "inventory_state.carried",
        "inventory_state.entry_id",
        "inventory_state.equipped",
        "inventory_state.quantity",
        "prepared_spell_entry_ids",
        "prepared_spells",
        "prepared_spells.source_access_entry_id",
        "prepared_spells.source_profile_id",
        "resources",
        "spell_slots",
        "spell_slots.remaining",
        "spell_slots.used",
        "spell_storing_item",
        "spell_storing_item.inventory_entry_id",
        "spell_storing_item.remaining_uses",
        "temporary_hp",
    }
)


def _nested_models(annotation: object, seen: set[type]) -> set[type]:
    found: set[type] = set()
    for argument in typing.get_args(annotation) or ():
        found |= _nested_models(argument, seen)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        found.add(annotation)
    return found


def _field_paths(model: type[BaseModel], prefix: str, seen: set[type]) -> set[str]:
    if model in seen:
        return set()
    seen.add(model)
    paths: set[str] = set()
    for name, field in model.model_fields.items():
        paths.add(f"{prefix}{name}")
        for nested in _nested_models(field.annotation, seen):
            paths |= _field_paths(nested, f"{prefix}{name}.", seen)
    return paths


def _declared_ref_paths(inventory: frozenset[str]) -> set[str]:
    """Strip the inventory's collection/selector notation down to field paths."""

    return {re.sub(r"\[[^\]]*\]", "", path) for path in inventory}


def test_m03b_every_build_field_is_classified_for_portability() -> None:
    actual = _field_paths(CharacterBuild, "", set())
    declared = _declared_ref_paths(BUILD_STABLE_KEY_PATHS) | NON_REF_BUILD_FIELDS
    assert actual == declared, (
        "CharacterBuild changed shape. Classify each field: add it to "
        "BUILD_STABLE_KEY_PATHS and the walker, or to NON_REF_BUILD_FIELDS. "
        f"unclassified={sorted(actual - declared)} stale={sorted(declared - actual)}"
    )


def test_m03b_every_state_field_is_classified_for_portability() -> None:
    actual = _field_paths(CharacterState, "", set())
    declared = _declared_ref_paths(STATE_STABLE_KEY_PATHS) | NON_REF_STATE_FIELDS
    assert actual == declared, (
        "CharacterState changed shape. Classify each field: add it to "
        "STATE_STABLE_KEY_PATHS and the walker, or to NON_REF_STATE_FIELDS. "
        f"unclassified={sorted(actual - declared)} stale={sorted(declared - actual)}"
    )


def test_m03b_declared_ref_paths_exist_on_the_models() -> None:
    build_fields = _field_paths(CharacterBuild, "", set())
    state_fields = _field_paths(CharacterState, "", set())
    assert _declared_ref_paths(BUILD_STABLE_KEY_PATHS) <= build_fields
    assert _declared_ref_paths(STATE_STABLE_KEY_PATHS) <= state_fields
