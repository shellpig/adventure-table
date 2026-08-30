from app.content import load_default_content_registry


EXPECTED_COUNTS = {
    "personality_traits": 8,
    "ideals": 6,
    "bonds": 6,
    "flaws": 6,
}

VARIANT_TABLE_SOURCES = {
    "spy": "criminal",
    "gladiator": "entertainer",
    "guild-merchant": "guild-artisan",
    "knight": "noble",
    "pirate": "sailor",
}


def test_all_phb_backgrounds_expose_complete_roleplay_tables() -> None:
    registry = load_default_content_registry()
    backgrounds = registry.list_kind("background", source="phb2014")

    assert len(backgrounds) == 18
    for background in backgrounds:
        suggestions = background.data["roleplay_suggestions"]
        assert set(suggestions) == set(EXPECTED_COUNTS)
        for field, expected_count in EXPECTED_COUNTS.items():
            values = suggestions[field]
            assert len(values) == expected_count, (background.key, field)
            assert len(set(values)) == expected_count, (background.key, field)
            assert all(value.strip() for value in values)
            assert all("suggestion." not in value.lower() for value in values)


def test_phb_variants_receive_the_documented_parent_roleplay_table() -> None:
    registry = load_default_content_registry()

    for variant_index, source_index in VARIANT_TABLE_SOURCES.items():
        variant = registry.get(f"phb2014:background:{variant_index}")
        source = registry.get(f"phb2014:background:{source_index}")

        assert variant.data["roleplay_suggestions"] == source.data["roleplay_suggestions"]
        assert variant.data["variant_of"]["key"] == source.key

    # Roleplay-table reuse does not turn variant_of into mechanical inheritance.
    knight = registry.get("phb2014:background:knight")
    noble = registry.get("phb2014:background:noble")
    pirate = registry.get("phb2014:background:pirate")
    sailor = registry.get("phb2014:background:sailor")
    assert knight.data["feature"]["name"] != noble.data["feature"]["name"]
    assert pirate.data["feature"]["name"] != sailor.data["feature"]["name"]
