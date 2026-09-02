from __future__ import annotations

from app.content.identity import reference_to_stable_key
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, ResourceCounter
from app.domain.rules.artificer import (
    ability_modifier,
    advanced_feature_resource_rules,
    class_level,
    proficiency_bonus,
)


SUPERIORITY_DICE_RESOURCE_KEY = "feature:superiority-dice"
BATTLE_MASTER_COMBAT_SUPERIORITY = "phb2014:feature:battle-master-3-combat-superiority"
SUPERIOR_TECHNIQUE = "tce:feature:superior-technique"
FIGHTER_REF = "srd5.1:class:fighter"


def spell_access_resource_key(source_key: str, spell_key: str) -> str:
    """Stable live-state identity for Build-granted limited-use spell access."""

    return f"spell-access:{source_key}:{spell_key}"


def _capacity_from_content_expression(
    build: CharacterBuild,
    capacity: dict[str, object],
) -> int | None:
    capacity_type = capacity.get("type")
    minimum = capacity.get("minimum")
    minimum_value = minimum if isinstance(minimum, int) else 0
    if capacity_type == "fixed":
        value = capacity.get("value")
        return value if isinstance(value, int) and value >= 0 else None
    if capacity_type == "proficiency_bonus":
        return proficiency_bonus(build.character_level)
    if capacity_type in {"ability_modifier", "ability_modifier_x2"}:
        ability = capacity.get("ability")
        if not isinstance(ability, str):
            return None
        value = ability_modifier(build, ability)
        if capacity_type == "ability_modifier_x2":
            value *= 2
        return max(minimum_value, value)
    if capacity_type == "class_level":
        raw_class_ref = capacity.get("class_ref")
        if not isinstance(raw_class_ref, dict):
            return None
        class_ref = reference_to_stable_key(raw_class_ref, kinds={"class"})
        if class_ref is None:
            return None
        return max(minimum_value, class_level(build, class_ref))
    return None


def _battle_master_superiority_dice(build: CharacterBuild) -> int:
    """Return the canonical Battle Master pool contribution already granted by Build.

    M01-J materialized Combat Superiority before generic resource metadata existed,
    so K bridges that historical content identity here rather than duplicating the
    feature or rewriting immutable old Builds. New contributors aggregate into the
    same Current State resource key below.
    """

    if BATTLE_MASTER_COMBAT_SUPERIORITY not in build.feature_refs:
        return 0
    fighter_level = class_level(build, FIGHTER_REF)
    if fighter_level >= 15:
        return 6
    if fighter_level >= 7:
        return 5
    if fighter_level >= 3:
        return 4
    return 0


def _superiority_dice_capacity(build: CharacterBuild) -> int:
    capacity = _battle_master_superiority_dice(build)

    # TCE Superior Technique predates the K feat-resource contract but is another
    # canonical source of one superiority die. Keep its existing StableKey and
    # aggregate it without widening native maneuver eligibility.
    if SUPERIOR_TECHNIQUE in build.feature_refs:
        capacity += 1

    for grant in build.feat_resource_grants:
        if (
            grant.resource_id == "superiority-dice"
            and grant.stacking == "aggregate-superiority-dice"
        ):
            capacity += grant.capacity
    return capacity


def feature_resource_capacities(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> dict[str, int]:
    capacities: dict[str, int] = {}
    for feature_ref in build.feature_refs:
        feature = registry.get_optional(feature_ref)
        if feature is None:
            continue
        resource = feature.data.get("resource")
        if not isinstance(resource, dict):
            continue
        capacity = resource.get("capacity")
        if not isinstance(capacity, dict):
            continue
        value = _capacity_from_content_expression(build, capacity)
        if value is None:
            continue
        capacities[f"feature:{feature_ref}"] = value

    # M01-H advanced Artificer resources are deliberately Rules Layer derived.
    # They remain generic CharacterState.resources counters so Build-version
    # reconciliation preserves used values without adding a class-only state bag.
    for rule in advanced_feature_resource_rules(build):
        capacities[rule.resource_id] = rule.capacity

    # Some ancestry/feature spell grants do not consume normal spell slots but
    # instead have their own per-rest uses (for example SCAG Half-Elf Drow
    # Magic). Keep those counters in generic Current State resources so they
    # participate in the same creation and Build-version reconciliation flow as
    # other Build-derived resources without polluting class spell-slot pools.
    for access in build.spell_access_entries:
        if access.uses_per_rest is None:
            continue
        capacities[
            spell_access_resource_key(access.source_key, access.spell_key)
        ] = access.uses_per_rest

    # M01-K Martial Adept contributes one superiority die. The pool is shared
    # with canonical Battle Master / Superior Technique contributors while the
    # feat's die-size and recharge provenance remain on CharacterBuild.
    superiority_capacity = _superiority_dice_capacity(build)
    if superiority_capacity > 0:
        capacities[SUPERIORITY_DICE_RESOURCE_KEY] = superiority_capacity

    # Future feat resources that explicitly request a separate pool can reuse the
    # same Build-derived State substrate without inventing feat-specific state.
    for grant in build.feat_resource_grants:
        if grant.stacking != "separate":
            continue
        key = f"feat:{grant.source_ref}:{grant.resource_id}"
        capacities[key] = capacities.get(key, 0) + grant.capacity

    return capacities


def initial_feature_resource_state(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> dict[str, ResourceCounter]:
    return {
        key: ResourceCounter(used=0, remaining=capacity)
        for key, capacity in feature_resource_capacities(build, registry).items()
    }
