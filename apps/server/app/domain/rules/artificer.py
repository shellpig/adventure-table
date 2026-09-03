from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, CharacterState, ResourceCounter
from app.domain.rules.spellcasting import spell_is_on_class_list


ARTIFICER_REF = "tce:class:artificer"
ALCHEMIST_REF = "tce:subclass:alchemist"
ARMORER_REF = "tce:subclass:armorer"
ARTILLERIST_REF = "tce:subclass:artillerist"
BATTLE_SMITH_REF = "tce:subclass:battle-smith"

ARMOR_MODEL_FEATURE_REF = "tce:feature:armor-model"
ELDRITCH_CANNON_FEATURE_REF = "tce:feature:eldritch-cannon"
FLASH_OF_GENIUS_FEATURE_REF = "tce:feature:flash-of-genius"
ARCANE_JOLT_FEATURE_REF = "tce:feature:arcane-jolt"
SPELL_STORING_ITEM_FEATURE_REF = "tce:feature:spell-storing-item"

ARMOR_MODELS = ("guardian", "infiltrator")
ELDRITCH_CANNON_TYPES = ("flamethrower", "force-ballista", "protector")
ARCANE_ARMOR_PARTS = ("armor", "boots", "helmet", "special_weapon")
ARTISAN_TOOL_INDEXES = frozenset(
    {
        "alchemists-supplies",
        "brewers-supplies",
        "calligraphers-supplies",
        "carpenters-tools",
        "cartographers-tools",
        "cobblers-tools",
        "cooks-utensils",
        "glassblowers-tools",
        "jewelers-tools",
        "leatherworkers-tools",
        "masons-tools",
        "painters-supplies",
        "potters-tools",
        "smiths-tools",
        "tinkers-tools",
        "weavers-tools",
        "woodcarvers-tools",
    }
)


@dataclass(frozen=True)
class ArtificerResourceRule:
    resource_id: str
    feature_ref: str
    capacity: int
    capacity_expression: dict[str, Any]
    recharge: tuple[str, ...]


def class_level(build: CharacterBuild, class_ref: str) -> int:
    return sum(1 for value in build.class_progression if value == class_ref)


def artificer_level(build: CharacterBuild) -> int:
    return class_level(build, ARTIFICER_REF)


def selected_artificer_subclass(build: CharacterBuild) -> str | None:
    for selection in build.subclasses:
        if selection.class_ref == ARTIFICER_REF:
            return selection.subclass_ref
    return None


def proficiency_bonus(character_level: int) -> int:
    return 2 + (character_level - 1) // 4


def effective_ability_score(build: CharacterBuild, ability: str) -> int:
    value = int(getattr(build.ability_scores, ability))
    override_key = f"ability:{ability}"
    for override in build.numeric_overrides:
        if override.key == override_key:
            return int(override.value)
    return value


def ability_modifier(build: CharacterBuild, ability: str) -> int:
    return (effective_ability_score(build, ability) - 10) // 2


def known_infusion_count(level: int) -> int:
    if level < 2:
        return 0
    if level < 6:
        return 4
    if level < 10:
        return 6
    if level < 14:
        return 8
    if level < 18:
        return 10
    return 12


def infused_item_capacity(level: int) -> int:
    if level < 2:
        return 0
    if level < 6:
        return 2
    if level < 10:
        return 3
    if level < 14:
        return 4
    if level < 18:
        return 5
    return 6


def attunement_capacity(build: CharacterBuild) -> int:
    level = artificer_level(build)
    if level >= 18:
        return 6
    if level >= 14:
        return 5
    if level >= 10:
        return 4
    return 3


def attunement_requirement_exceptions(build: CharacterBuild) -> dict[str, bool]:
    enabled = artificer_level(build) >= 14
    return {
        "ignore_class_requirement": enabled,
        "ignore_race_requirement": enabled,
        "ignore_spell_requirement": enabled,
        "ignore_level_requirement": enabled,
    }


def armor_modifications_metadata(build: CharacterBuild) -> dict[str, Any] | None:
    if selected_artificer_subclass(build) != ARMORER_REF or artificer_level(build) < 9:
        return None
    return {
        "capacity_bonus": 2,
        "bonus_applies_to": "arcane_armor_parts_only",
        "parts": list(ARCANE_ARMOR_PARTS),
        "separate_infusion_slots": True,
    }


def _capacity_from_descriptor(
    descriptor: dict[str, Any],
    build: CharacterBuild,
) -> int | None:
    capacity = descriptor.get("capacity")
    if not isinstance(capacity, dict):
        return None
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
        class_reference = capacity.get("class_ref")
        if isinstance(class_reference, dict):
            class_key = reference_to_stable_key(class_reference, kinds={"class"})
        else:
            class_key = None
        if class_key is None:
            return None
        return max(minimum_value, class_level(build, class_key))
    return None


def advanced_feature_resource_rules(build: CharacterBuild) -> tuple[ArtificerResourceRule, ...]:
    level = artificer_level(build)
    if level <= 0:
        return ()

    rules: list[ArtificerResourceRule] = []
    if level >= 7:
        capacity = max(1, ability_modifier(build, "intelligence"))
        rules.append(
            ArtificerResourceRule(
                resource_id=f"feature:{FLASH_OF_GENIUS_FEATURE_REF}",
                feature_ref=FLASH_OF_GENIUS_FEATURE_REF,
                capacity=capacity,
                capacity_expression={
                    "type": "ability_modifier",
                    "ability": "intelligence",
                    "minimum": 1,
                },
                recharge=("long_rest",),
            )
        )

    subclass_ref = selected_artificer_subclass(build)
    if subclass_ref == ARMORER_REF and level >= 3:
        rules.append(
            ArtificerResourceRule(
                resource_id="feature:tce:feature:armor-model:defensive-field",
                feature_ref=ARMOR_MODEL_FEATURE_REF,
                capacity=proficiency_bonus(build.character_level),
                capacity_expression={"type": "proficiency_bonus"},
                recharge=("long_rest",),
            )
        )
    if subclass_ref == BATTLE_SMITH_REF and level >= 9:
        capacity = max(1, ability_modifier(build, "intelligence"))
        rules.append(
            ArtificerResourceRule(
                resource_id=f"feature:{ARCANE_JOLT_FEATURE_REF}",
                feature_ref=ARCANE_JOLT_FEATURE_REF,
                capacity=capacity,
                capacity_expression={
                    "type": "ability_modifier",
                    "ability": "intelligence",
                    "minimum": 1,
                },
                recharge=("long_rest",),
            )
        )
    return tuple(rules)


def spell_storing_item_capacity(build: CharacterBuild) -> int:
    if artificer_level(build) < 11:
        return 0
    return max(2, ability_modifier(build, "intelligence") * 2)


def spell_storing_item_metadata(build: CharacterBuild) -> dict[str, Any] | None:
    capacity = spell_storing_item_capacity(build)
    if capacity == 0:
        return None
    return {
        "feature_ref": SPELL_STORING_ITEM_FEATURE_REF,
        "capacity": capacity,
        "capacity_expression": {
            "type": "ability_modifier_x2",
            "ability": "intelligence",
            "minimum": 2,
        },
        "recharge": ["long_rest"],
        "eligible_spell_levels": [1, 2],
        "eligible_casting_time": "1 action",
        "eligible_item_types": ["simple_or_martial_weapon", "artificer_spellcasting_focus"],
    }


def subclass_runtime_metadata(build: CharacterBuild) -> dict[str, Any]:
    level = artificer_level(build)
    subclass_ref = selected_artificer_subclass(build)
    if level <= 0 or subclass_ref is None:
        return {}

    if subclass_ref == ALCHEMIST_REF and level >= 3:
        elixir_count = 3 if level >= 15 else 2 if level >= 6 else 1
        return {
            "feature_ref": "tce:feature:experimental-elixir",
            "runtime_kind": "manual_random_table",
            "free_elixirs_after_long_rest": elixir_count,
            "options": [
                "healing",
                "swiftness",
                "resilience",
                "boldness",
                "flight",
                "transformation",
            ],
            "random_resolution": "manual",
            "consumption": "manual",
        }

    if subclass_ref == ARMORER_REF and level >= 3:
        return {
            "feature_ref": ARMOR_MODEL_FEATURE_REF,
            "runtime_kind": "feature_mode",
            "mode_state_key": ARMOR_MODEL_FEATURE_REF,
            "options": list(ARMOR_MODELS),
            "switch_creates_build_version": False,
            "armor_modifications": armor_modifications_metadata(build),
        }

    if subclass_ref == ARTILLERIST_REF and level >= 3:
        return {
            "feature_ref": ELDRITCH_CANNON_FEATURE_REF,
            "runtime_kind": "feature_mode",
            "mode_state_key": ELDRITCH_CANNON_FEATURE_REF,
            "options": list(ELDRITCH_CANNON_TYPES),
            "combat_entity": "deferred_to_P4",
        }

    if subclass_ref == BATTLE_SMITH_REF and level >= 3:
        return {
            "feature_ref": "tce:feature:steel-defender",
            "runtime_kind": "stat_generation_metadata",
            "armor_class": 15,
            "hit_points_formula": "2 + intelligence_modifier + 5 * artificer_level",
            "speed": 40,
            "proficiency_bonus_source": "character",
            "combat_entity": "deferred_to_P4",
        }
    return {}


def infusion_charge_capacity(infusion_data: dict[str, Any], build: CharacterBuild) -> int | None:
    charges = infusion_data.get("charges")
    if not isinstance(charges, dict):
        return None
    return _capacity_from_descriptor(charges, build)


def _reference_index(reference: Any) -> str | None:
    if isinstance(reference, dict):
        index = reference.get("index")
        if isinstance(index, str):
            return index.lower()
        key = reference.get("key")
        if isinstance(key, str):
            try:
                return parse_stable_key(key).index.lower()
            except ValueError:
                return None
    return None


def _entry_tokens(entry) -> set[str]:
    values = [entry.index, entry.name]
    data = entry.data
    for key in ("armor_category", "weapon_category", "category_range"):
        value = data.get(key)
        if isinstance(value, str):
            values.append(value)
    category = data.get("equipment_category")
    if isinstance(category, dict):
        for key in ("index", "name"):
            value = category.get(key)
            if isinstance(value, str):
                values.append(value)
    tokens: set[str] = set()
    for value in values:
        lowered = value.lower().replace("_", "-").replace(" ", "-")
        tokens.update(part for part in lowered.split("-") if part)
        tokens.add(lowered)
    return tokens


def _equipment_value_gp(entry) -> float | None:
    cost = entry.data.get("cost")
    if not isinstance(cost, dict):
        return None
    quantity = cost.get("quantity")
    unit = cost.get("unit")
    if not isinstance(quantity, (int, float)) or not isinstance(unit, str):
        return None
    multipliers = {"cp": 0.01, "sp": 0.1, "ep": 0.5, "gp": 1.0, "pp": 10.0}
    multiplier = multipliers.get(unit.lower())
    return float(quantity) * multiplier if multiplier is not None else None


def _weapon_property_indexes(entry) -> set[str]:
    properties = entry.data.get("properties")
    if not isinstance(properties, list):
        return set()
    result: set[str] = set()
    for value in properties:
        index = _reference_index(value)
        if index:
            result.add(index)
    return result


def _matches_filter_kind(entry, filter_kind: str, replicated_item_ref: str | None) -> bool:
    parsed = parse_stable_key(entry.key)
    tokens = _entry_tokens(entry)
    armor_category = str(entry.data.get("armor_category", "")).lower()
    weapon_category = str(entry.data.get("weapon_category", "")).lower()
    properties = _weapon_property_indexes(entry)

    if filter_kind == "replicated_item":
        return replicated_item_ref is not None and entry.key == replicated_item_ref
    if parsed.kind != "equipment":
        return False
    if filter_kind == "armor":
        return bool(armor_category) and armor_category != "shield"
    if filter_kind == "shield":
        return armor_category == "shield" or "shield" in tokens
    if filter_kind == "simple_or_martial_weapon":
        return weapon_category in {"simple", "martial"}
    if filter_kind == "thrown_weapon":
        return "thrown" in properties
    if filter_kind == "ammunition_weapon":
        return "ammunition" in properties
    if filter_kind == "rod_staff_wand":
        return bool(tokens.intersection({"rod", "staff", "wand"}))
    if filter_kind == "boots":
        return bool(tokens.intersection({"boot", "boots"}))
    if filter_kind == "ring":
        return "ring" in tokens
    if filter_kind == "helmet":
        return bool(tokens.intersection({"helmet", "helm"}))
    if filter_kind == "crystal_or_gem":
        return bool(tokens.intersection({"crystal", "gem", "gemstone"}))
    return False


def infusion_matches_inventory_item(
    infusion_data: dict[str, Any],
    item_ref: str,
    registry: ContentRegistry,
) -> bool:
    entry = registry.get_optional(item_ref)
    if entry is None:
        return False

    # Mind Sharpener explicitly accepts a suit of armor or robes. Robes are
    # adventuring gear in the canonical SRD dataset, so this exception belongs
    # to the infusion rule rather than globally redefining robes as armor.
    if infusion_data.get("index") == "mind-sharpener" and entry.index == "robes":
        return True

    item_filter = infusion_data.get("item_filter")
    if not isinstance(item_filter, dict):
        return False
    filters = item_filter.get("any_of")
    if not isinstance(filters, list):
        return False
    raw_replicated = infusion_data.get("replicates_item")
    replicated_item_ref = (
        reference_to_stable_key(raw_replicated, kinds={"item"})
        if isinstance(raw_replicated, dict)
        else None
    )
    matches_kind = any(
        isinstance(filter_kind, str)
        and _matches_filter_kind(entry, filter_kind, replicated_item_ref)
        for filter_kind in filters
    )
    if not matches_kind:
        return False

    # Homunculus Servant requires the gem/crystal heart to be worth at least
    # 100 gp. Missing or non-monetary value data fails closed rather than
    # allowing a cheap arcane-focus crystal to satisfy the rule.
    if infusion_data.get("index") == "homunculus-servant":
        value_gp = _equipment_value_gp(entry)
        return value_gp is not None and value_gp >= 100
    return True


def validate_known_infusions(build: CharacterBuild, registry: ContentRegistry) -> None:
    level = artificer_level(build)
    expected_count = known_infusion_count(level)
    if len(build.infusion_refs) != expected_count:
        raise ValueError(
            f"Artificer known infusion count must be {expected_count} at Artificer level {level}; "
            f"got {len(build.infusion_refs)}"
        )
    for infusion_ref in build.infusion_refs:
        infusion = registry.get_optional(infusion_ref)
        if infusion is None or parse_stable_key(infusion_ref).kind != "infusion":
            raise ValueError(f"unknown infusion reference: {infusion_ref}")
        minimum_level = infusion.data.get("minimum_artificer_level")
        if not isinstance(minimum_level, int) or level < minimum_level:
            raise ValueError(
                f"infusion {infusion_ref} requires Artificer level {minimum_level}; got {level}"
            )


def _active_capacity_allows(build: CharacterBuild, state: CharacterState) -> bool:
    base_capacity = infused_item_capacity(artificer_level(build))
    active_count = len(state.active_infusions)
    if active_count <= base_capacity:
        return True
    armor_metadata = armor_modifications_metadata(build)
    if armor_metadata is None or active_count > base_capacity + 2:
        return False
    marked_parts = [
        getattr(active, "arcane_armor_part", None)
        for active in state.active_infusions
        if getattr(active, "arcane_armor_part", None) is not None
    ]
    return active_count - base_capacity <= len(marked_parts) <= len(set(marked_parts))


def _validate_active_infusions(
    state: CharacterState,
    build: CharacterBuild,
    registry: ContentRegistry,
) -> None:
    if not _active_capacity_allows(build, state):
        base_capacity = infused_item_capacity(artificer_level(build))
        raise ValueError(
            f"active infusion count exceeds Artificer capacity {base_capacity}; "
            "Armorer bonus capacity requires distinct arcane armor parts"
        )

    inventory_by_id = {entry.entry_id: entry for entry in state.inventory_state}
    known = set(build.infusion_refs)
    active_counts: Counter[str] = Counter()
    armor_parts: list[str] = []
    for active in state.active_infusions:
        if active.infusion_ref not in known:
            raise ValueError(f"active infusion is not known by this Build: {active.infusion_ref}")
        inventory = inventory_by_id.get(active.inventory_entry_id)
        if inventory is None:
            raise ValueError(
                f"active infusion target inventory entry does not exist: {active.inventory_entry_id}"
            )
        infusion = registry.get_optional(active.infusion_ref)
        if infusion is None:
            raise ValueError(f"active infusion content does not exist: {active.infusion_ref}")
        minimum_level = infusion.data.get("minimum_artificer_level")
        if not isinstance(minimum_level, int) or artificer_level(build) < minimum_level:
            raise ValueError(f"active infusion no longer meets minimum level: {active.infusion_ref}")
        if not infusion_matches_inventory_item(infusion.data, inventory.item_ref, registry):
            raise ValueError(
                f"inventory item {inventory.item_ref} is not eligible for infusion {active.infusion_ref}"
            )
        active_counts[active.infusion_ref] += 1
        copy_limit = infusion.data.get("active_copy_limit", 1)
        if not isinstance(copy_limit, int) or active_counts[active.infusion_ref] > copy_limit:
            raise ValueError(f"active infusion copy limit exceeded: {active.infusion_ref}")

        charge_capacity = infusion_charge_capacity(infusion.data, build)
        if charge_capacity is None:
            if active.resource is not None:
                raise ValueError(
                    f"infusion without a charge resource cannot persist a counter: {active.infusion_ref}"
                )
        else:
            if active.resource is None:
                raise ValueError(f"charged infusion requires a live counter: {active.infusion_ref}")
            if active.resource.used + active.resource.remaining != charge_capacity:
                raise ValueError(
                    f"infusion resource capacity mismatch for {active.infusion_ref}: "
                    f"expected {charge_capacity}"
                )

        armor_part = getattr(active, "arcane_armor_part", None)
        if armor_part is not None:
            if armor_modifications_metadata(build) is None:
                raise ValueError("arcane armor infusion parts require Armorer Armor Modifications")
            if armor_part not in ARCANE_ARMOR_PARTS:
                raise ValueError(f"unknown arcane armor part: {armor_part}")
            armor_parts.append(armor_part)

    if len(armor_parts) != len(set(armor_parts)):
        raise ValueError("each arcane armor part can host at most one active infusion")


def _spell_storing_target_is_eligible(
    state: CharacterState,
    inventory_entry_id: str,
    item_ref: str,
    registry: ContentRegistry,
) -> bool:
    entry = registry.get_optional(item_ref)
    if entry is None or parse_stable_key(entry.key).kind != "equipment":
        return False
    if _matches_filter_kind(entry, "simple_or_martial_weapon", None):
        return True
    if entry.index == "thieves-tools" or entry.index in ARTISAN_TOOL_INDEXES:
        return True
    # From Artificer level 2 onward an infused item can serve as that Artificer's
    # spellcasting focus. Spell-Storing Item is level 11, so an active infusion
    # on this exact inventory entry makes it a legal focus target.
    return any(
        active.inventory_entry_id == inventory_entry_id
        for active in state.active_infusions
    )


def _validate_spell_storing_item(
    state: CharacterState,
    build: CharacterBuild,
    registry: ContentRegistry,
) -> None:
    stored = state.spell_storing_item
    if stored is None:
        return
    capacity = spell_storing_item_capacity(build)
    if capacity <= 0:
        raise ValueError("Spell-Storing Item state requires Artificer level 11")
    inventory_by_id = {entry.entry_id: entry for entry in state.inventory_state}
    target = inventory_by_id.get(stored.inventory_entry_id)
    if target is None:
        raise ValueError(
            f"Spell-Storing Item target inventory entry does not exist: {stored.inventory_entry_id}"
        )
    if not _spell_storing_target_is_eligible(
        state,
        stored.inventory_entry_id,
        target.item_ref,
        registry,
    ):
        raise ValueError(
            "Spell-Storing Item target must be a simple/martial weapon or an item usable as this Artificer's spellcasting focus"
        )
    spell = registry.get_optional(stored.spell_ref)
    if spell is None or parse_stable_key(spell.key).kind != "spell":
        raise ValueError(f"Spell-Storing Item references an unknown spell: {stored.spell_ref}")
    spell_level = spell.data.get("level")
    if spell_level not in {1, 2}:
        raise ValueError("Spell-Storing Item spell must be level 1 or 2")
    casting_time = spell.data.get("casting_time")
    if not isinstance(casting_time, str) or casting_time.strip().lower() not in {"1 action", "action"}:
        raise ValueError("Spell-Storing Item spell must have a casting time of 1 action")
    if not spell_is_on_class_list(spell.key, ARTIFICER_REF, registry):
        raise ValueError("Spell-Storing Item spell must be on the Artificer spell list")
    if stored.remaining_uses > capacity:
        raise ValueError(
            f"Spell-Storing Item remaining uses exceed capacity: {stored.remaining_uses}>{capacity}"
        )



def validate_artificer_state(
    state: CharacterState,
    build: CharacterBuild,
    registry: ContentRegistry,
) -> None:
    # Armor Model and Eldritch Cannon modes are declared as typed content
    # ``feature_mode`` descriptors and validated by the shared feature-mode
    # validator, which is default-deny about who owns a key.
    _validate_active_infusions(state, build, registry)
    _validate_spell_storing_item(state, build, registry)


def initial_artificer_feature_resources(
    build: CharacterBuild,
) -> dict[str, ResourceCounter]:
    return {
        rule.resource_id: ResourceCounter(used=0, remaining=rule.capacity)
        for rule in advanced_feature_resource_rules(build)
    }
