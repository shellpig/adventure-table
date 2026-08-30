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


def test_phb_variants_receive_the_documented_parent_roleplay_table_only() -> None:
    registry = load_default_content_registry()

    for variant_index, source_index in VARIANT_TABLE_SOURCES.items():
        variant = registry.get(f"phb2014:background:{variant_index}")
        source = registry.get(f"phb2014:background:{source_index}")

        assert variant.data["roleplay_suggestions"] == source.data["roleplay_suggestions"]
        assert variant.data["variant_of"]["key"] == source.key

        # The roleplay-table overlay must not replace the variant's own mechanics.
        if variant_index in {"gladiator", "knight", "pirate"}:
            assert variant.data["feature"]["name"] != source.data["feature"]["name"]
