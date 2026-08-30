from app.content import load_default_content_registry


def test_gos_background_features_preserve_manual_runtime_mechanics() -> None:
    registry = load_default_content_registry()

    fisher = registry.get("gos:background:fisher").data
    fishing = fisher["feature_metadata"]["fishing"]
    assert fishing["ability_check_advantage_with_equipment"] == "srd5.1:equipment:fishing-tackle"
    assert fishing["daily_people_fed_in_suitable_waters"] == 11
    assert fishing["lifestyle_supported"] == "poor"
    assert fishing["automation"] == "manual"

    marine = registry.get("gos:background:marine").data
    travel = marine["feature_metadata"]["travel"]
    assert travel["hours_before_forced_march"] == 16
    assert travel["normal_travel_time_multiplier"] == 2
    assert travel["safe_ship_landing_route"] is True
    assert travel["automation"] == "manual"

    shipwright = registry.get("gos:background:shipwright").data
    repair = shipwright["feature_metadata"]["repair"]
    assert repair["target"] == "water_vehicle_hull"
    assert repair["requires"] == ["carpenters_tools", "wood"]
    assert repair["amount"] == {"type": "proficiency_bonus_multiplier", "multiplier": 5}
    assert repair["reuse_condition"] == "vehicle_hauled_ashore_and_fully_repaired"
    assert repair["automation"] == "manual"

    smuggler = registry.get("gos:background:smuggler").data
    safe_house = smuggler["feature_metadata"]["safe_house"]
    assert safe_house["cost"] == "free"
    assert safe_house["lifestyle"] == "poor"
    assert safe_house["may_keep_presence_secret"] is True
    assert safe_house["automation"] == "manual"


def test_gos_optional_flavor_tables_cover_all_four_backgrounds_without_builder_mechanics() -> None:
    registry = load_default_content_registry()

    assert len(registry.get("gos:background:fisher").data["optional_roleplay_tables"]["fishing_tale"]) == 8
    assert len(registry.get("gos:background:marine").data["optional_roleplay_tables"]["hardship_endured"]) == 6
    assert len(registry.get("gos:background:shipwright").data["optional_roleplay_tables"]["life_at_sea"]) == 6
    assert len(registry.get("gos:background:smuggler").data["optional_roleplay_tables"]["claim_to_fame"]) == 6
