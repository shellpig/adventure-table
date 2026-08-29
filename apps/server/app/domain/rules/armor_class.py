from __future__ import annotations

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, CharacterState
from app.domain.rules.abilities import ability_modifier, effective_ability_score, numeric_override


def calculate_armor_class(
    build: CharacterBuild,
    state: CharacterState,
    registry: ContentRegistry,
) -> int:
    dex_modifier = ability_modifier(effective_ability_score(build, "dexterity"))
    unarmored_ac = 10 + dex_modifier
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

    result = max(armor_values, default=unarmored_ac)
    if shield_values:
        result += max(shield_values)

    override = numeric_override(build, "ac")
    return int(override) if override is not None else result
