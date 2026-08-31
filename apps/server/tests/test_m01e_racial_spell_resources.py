from __future__ import annotations

from app.content import load_default_content_registry
from app.domain.character.schemas import (
    AbilityScores,
    CharacterBuild,
    SpellAccessEntry,
)
from app.domain.rules.feature_resources import (
    initial_feature_resource_state,
    spell_access_resource_key,
)


def _build_with_drow_magic(*entries: SpellAccessEntry) -> CharacterBuild:
    return CharacterBuild(
        content_sources=("scag", "srd5.1"),
        race_ref="srd5.1:race:half-elf",
        race_variant_ref="scag:race-variant:half-elf-drow-descent",
        character_level=5,
        class_progression=("srd5.1:class:fighter",) * 5,
        ability_scores=AbilityScores(
            strength=15,
            dexterity=14,
            constitution=13,
            intelligence=10,
            wisdom=10,
            charisma=12,
        ),
        feature_refs=("scag:feature:half-elf-drow-magic",),
        spell_access_entries=entries,
        hp_progression=(10, 6, 6, 6, 6),
    )


def test_limited_drow_magic_spells_get_independent_live_resources() -> None:
    registry = load_default_content_registry()
    dancing_lights = SpellAccessEntry(
        entry_id="race:dancing-lights",
        spell_key="srd5.1:spell:dancing-lights",
        source_type="race",
        source_key="scag:feature:half-elf-drow-magic",
        access_type="granted",
        casting_ability="charisma",
    )
    faerie_fire = SpellAccessEntry(
        entry_id="race:faerie-fire",
        spell_key="srd5.1:spell:faerie-fire",
        source_type="race",
        source_key="scag:feature:half-elf-drow-magic",
        access_type="granted",
        casting_ability="charisma",
        uses_per_rest=1,
        rest_type="long_rest",
    )
    darkness = SpellAccessEntry(
        entry_id="race:darkness",
        spell_key="srd5.1:spell:darkness",
        source_type="race",
        source_key="scag:feature:half-elf-drow-magic",
        access_type="granted",
        casting_ability="charisma",
        uses_per_rest=1,
        rest_type="long_rest",
    )

    state = initial_feature_resource_state(
        _build_with_drow_magic(dancing_lights, faerie_fire, darkness),
        registry,
    )

    faerie_key = spell_access_resource_key(
        faerie_fire.source_key,
        faerie_fire.spell_key,
    )
    darkness_key = spell_access_resource_key(
        darkness.source_key,
        darkness.spell_key,
    )
    dancing_key = spell_access_resource_key(
        dancing_lights.source_key,
        dancing_lights.spell_key,
    )

    assert state[faerie_key].used == 0
    assert state[faerie_key].remaining == 1
    assert state[darkness_key].used == 0
    assert state[darkness_key].remaining == 1
    assert dancing_key not in state
    assert all(not key.startswith("pact_magic:") for key in (faerie_key, darkness_key))
