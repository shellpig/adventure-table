from __future__ import annotations

from app.content.m01l_models import NaturalArmorData
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, CharacterState
from app.domain.rules.abilities import ability_modifier, effective_ability_score, numeric_override


def _natural_armor_candidates(
    build: CharacterBuild,
    registry: ContentRegistry,
    *,
    body_armor_equipped: bool,
) -> tuple[int, ...]:
    candidates: list[int] = []
    for feature_ref in build.feature_refs:
        feature = registry.get_optional(feature_ref)
        if feature is None:
            continue
        raw = feature.data.get("natural_armor")
        if not isinstance(raw, dict):
            continue
        natural = NaturalArmorData.model_validate(raw)
        if natural.requires_unarmored and body_armor_equipped:
            continue
        modifier = ability_modifier(effective_ability_score(build, natural.ability))
        candidates.append(natural.base + modifier)
    return tuple(candidates)


def calculate_armor_class(
    build: CharacterBuild,
    state: CharacterState,
    registry: ContentRegistry,
) -> int:
    dex_modifier = ability_modifier(effective_ability_score(build, "dexterity"))
    ordinary_unarmored_ac = 10 + dex_modifier
    armor_values: list[int] = []
    shield_values: list[int] = []

    for inventory_entry in state.inventory_state:
        if not inventory_entry.equipped:
            continue
        content = registry.get(inventory_entry.item_ref)
        data = content.data
        category = data.get("equipment_category", {}).get("index")
        if category != "armor":
            continue

        armor_class = data.get("armor_class")
        armor_category = data.get("armor_category")
        if not isinstance(armor_class, dict):
            continue
        base = armor_class.get("base")
        if not isinstance(base, int):
            continue

        if armor_category == "Shield":
            shield_values.append(base)
            continue

        value = base
        if armor_class.get("dex_bonus"):
            max_bonus = armor_class.get("max_bonus")
            dex_contribution = dex_modifier
            if isinstance(max_bonus, int):
                dex_contribution = min(dex_contribution, max_bonus)
            value += dex_contribution
        armor_values.append(value)

    body_armor_equipped = bool(armor_values)
    if body_armor_equipped:
        result = max(armor_values)
    else:
        natural_values = _natural_armor_candidates(
            build,
            registry,
            body_armor_equipped=False,
        )
        result = max((ordinary_unarmored_ac, *natural_values))

    if shield_values:
        result += max(shield_values)

    override = numeric_override(build, "ac")
    return int(override) if override is not None else result
