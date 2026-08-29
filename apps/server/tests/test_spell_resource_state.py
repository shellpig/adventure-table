from __future__ import annotations

import pytest

from app.content import load_default_content_registry
from app.domain.character.schemas import (
    AbilityScores,
    CharacterBuild,
    CharacterState,
    ResourceCounter,
    SpellResourcePool,
    SpellSlotCapacity,
    SpellcastingProfile,
)
from app.domain.character.validation import CharacterValidationError, validate_state_against_build
from app.domain.rules.spellcasting import initial_spell_resource_state, pact_resource_key


def _build() -> CharacterBuild:
    return CharacterBuild(
        race_ref="srd5.1:race:human",
        character_level=2,
        class_progression=("srd5.1:class:wizard", "srd5.1:class:warlock"),
        ability_scores=AbilityScores(
            strength=10,
            dexterity=12,
            constitution=10,
            intelligence=16,
            wisdom=12,
            charisma=16,
        ),
        hp_progression=(6, 5),
        spellcasting_profiles=(
            SpellcastingProfile(
                profile_id="class:wizard",
                source_type="class",
                source_key="srd5.1:class:wizard",
                class_ref="srd5.1:class:wizard",
                ability="intelligence",
                access_model="spellbook",
                resource_pool_type="normal_multiclass_slots",
                max_spell_level=1,
                prepared_limit=4,
            ),
            SpellcastingProfile(
                profile_id="class:warlock",
                source_type="class",
                source_key="srd5.1:class:warlock",
                class_ref="srd5.1:class:warlock",
                ability="charisma",
                access_model="known",
                resource_pool_type="pact_magic",
                max_spell_level=1,
            ),
        ),
        spell_resource_pools=(
            SpellResourcePool(
                pool_id="spell_slots:combined",
                pool_type="normal_multiclass_slots",
                slots=(SpellSlotCapacity(level=1, capacity=2),),
            ),
            SpellResourcePool(
                pool_id="pact_magic:srd5.1:class:warlock",
                pool_type="pact_magic",
                source_profile_id="class:warlock",
                slots=(SpellSlotCapacity(level=1, capacity=1),),
            ),
        ),
    )


def test_initial_spell_resources_keep_normal_and_pact_magic_separate() -> None:
    build = _build()

    slots, resources = initial_spell_resource_state(build)

    assert slots == {1: ResourceCounter(used=0, remaining=2)}
    pact_key = pact_resource_key("pact_magic:srd5.1:class:warlock", 1)
    assert resources == {pact_key: ResourceCounter(used=0, remaining=1)}

    state = CharacterState(
        current_hp=11,
        spell_slots={1: ResourceCounter(used=1, remaining=1)},
        resources={pact_key: ResourceCounter(used=1, remaining=0)},
    )
    validate_state_against_build(state, build, load_default_content_registry())


def test_spell_resource_usage_must_match_build_capacity() -> None:
    build = _build()
    pact_key = pact_resource_key("pact_magic:srd5.1:class:warlock", 1)
    invalid = CharacterState(
        current_hp=11,
        spell_slots={1: ResourceCounter(used=1, remaining=0)},
        resources={pact_key: ResourceCounter(used=0, remaining=1)},
    )

    with pytest.raises(CharacterValidationError, match="Build capacity"):
        validate_state_against_build(invalid, build, load_default_content_registry())
