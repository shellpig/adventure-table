from __future__ import annotations

from app.domain.character.schemas import (
    AbilityScores,
    CharacterBuild,
    ResourceCounter,
    SpellResourcePool,
    SpellSlotCapacity,
    SpellcastingProfile,
)
from app.domain.rules.spellcasting import (
    pact_resource_key,
    reconcile_spell_resource_state,
    resource_counter_matches_capacity,
)


def _build_with_new_capacity() -> CharacterBuild:
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
                max_spell_level=2,
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
                max_spell_level=2,
            ),
        ),
        spell_resource_pools=(
            SpellResourcePool(
                pool_id="spell_slots:combined",
                pool_type="normal_multiclass_slots",
                slots=(
                    SpellSlotCapacity(level=1, capacity=3),
                    SpellSlotCapacity(level=2, capacity=2),
                ),
            ),
            SpellResourcePool(
                pool_id="pact_magic:srd5.1:class:warlock",
                pool_type="pact_magic",
                source_profile_id="class:warlock",
                slots=(SpellSlotCapacity(level=2, capacity=2),),
            ),
        ),
    )


def test_capacity_reconciliation_preserves_legal_usage_and_removes_obsolete_spell_pools() -> None:
    build = _build_with_new_capacity()
    old_pact_key = pact_resource_key("pact_magic:srd5.1:class:warlock", 1)
    new_pact_key = pact_resource_key("pact_magic:srd5.1:class:warlock", 2)

    next_slots, next_resources = reconcile_spell_resource_state(
        build,
        current_spell_slots={
            1: ResourceCounter(used=1, remaining=1),
            3: ResourceCounter(used=1, remaining=0),
        },
        current_resources={
            old_pact_key: ResourceCounter(used=1, remaining=0),
            new_pact_key: ResourceCounter(used=1, remaining=0),
            "feature:second-wind": ResourceCounter(used=0, remaining=1),
        },
    )

    assert next_slots == {
        1: ResourceCounter(used=1, remaining=2),
        2: ResourceCounter(used=0, remaining=2),
    }
    assert old_pact_key not in next_resources
    assert next_resources[new_pact_key] == ResourceCounter(used=1, remaining=1)
    assert next_resources["feature:second-wind"] == ResourceCounter(used=0, remaining=1)
    assert resource_counter_matches_capacity(next_slots[1], 3)
    assert resource_counter_matches_capacity(next_slots[2], 2)
    assert resource_counter_matches_capacity(next_resources[new_pact_key], 2)
