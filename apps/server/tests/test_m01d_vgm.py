from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.content import load_default_content_registry
from app.domain.character.schemas import (
    AbilityScores,
    CharacterBuild,
    CharacterState,
    InventoryEntry,
    ResourceCounter,
)
from app.domain.character_builder.basics import resolve_creation_summary
from app.domain.character_builder.choices import build_foundation_choices
from app.domain.character_builder.compiler import compile_builder_draft
from app.domain.character_builder.origin import compile_origin
from app.domain.character_builder.reconciliation import reconcile_character_state
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderHPMethod,
    BuilderLevelChoice,
    BuilderMode,
    BuilderReferenceSelection,
)
from app.domain.rules.feature_resources import initial_feature_resource_state


def _draft(payload: BuilderDraftPayload) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=payload,
        created_at=now,
        updated_at=now,
    )


def _payload(
    *,
    race: str,
    subrace: str | None = None,
    level: int = 1,
) -> BuilderDraftPayload:
    return BuilderDraftPayload(
        basic=BuilderBasicInput(name="M01-D Hero"),
        target_level=level,
        race_selection=BuilderReferenceSelection(reference_id=race),
        subrace_selection=(
            BuilderReferenceSelection(reference_id=subrace) if subrace else None
        ),
        background_selection=BuilderReferenceSelection(
            reference_id="srd5.1:background:acolyte"
        ),
        ability_generation={
            "method": "standard_array",
            "scores": {
                "strength": 15,
                "dexterity": 14,
                "constitution": 13,
                "intelligence": 12,
                "wisdom": 10,
                "charisma": 8,
            },
        },
    )


def _origin_for(*, subrace: str, level: int):
    registry = load_default_content_registry()
    payload = _payload(race="vgm:race:aasimar", subrace=subrace, level=level)
    draft = _draft(payload)
    choices = build_foundation_choices(draft, registry)
    summary = resolve_creation_summary(draft, registry, choices)
    origin = compile_origin(
        grants=summary.grants,
        target_level=level,
        registry=registry,
    )
    return registry, summary, origin


def _aasimar_build(
    *,
    level: int,
    subrace_ref: str = "vgm:subrace:protector-aasimar",
    feature_refs: tuple[str, ...],
    ability_scores: AbilityScores | None = None,
) -> CharacterBuild:
    return CharacterBuild(
        race_ref="vgm:race:aasimar",
        subrace_ref=subrace_ref,
        character_level=level,
        class_progression=("srd5.1:class:fighter",) * level,
        ability_scores=ability_scores
        or AbilityScores(
            strength=15,
            dexterity=14,
            constitution=13,
            intelligence=12,
            wisdom=11,
            charisma=10,
        ),
        feature_refs=feature_refs,
        hp_progression=(10,) + (6,) * (level - 1),
    )


def test_vgm_pack_exposes_goblin_and_hobgoblin_rules() -> None:
    registry = load_default_content_registry()

    goblin = registry.get("vgm:race:goblin")
    assert goblin.data["size"] == "Small"
    assert goblin.data["speed"] == 30
    assert goblin.data["darkvision"] == 60
    assert [row["bonus"] for row in goblin.data["ability_bonuses"]] == [2, 1]
    assert {row["key"] for row in goblin.data["languages"]} == {
        "srd5.1:language:common",
        "srd5.1:language:goblin",
    }

    fury = registry.get("vgm:feature:fury-of-the-small")
    assert fury.data["bonus"] == {"type": "character_level"}
    assert fury.data["trigger"]["target_size"] == "larger_than_self"
    assert fury.data["resource"] == {
        "capacity": {"type": "fixed", "value": 1},
        "recharge": ["short_rest", "long_rest"],
    }

    hobgoblin = registry.get("vgm:race:hobgoblin")
    assert hobgoblin.data["size"] == "Medium"
    assert hobgoblin.data["proficiencies"][0]["key"] == "srd5.1:proficiency:light-armor"
    saving_face = registry.get("vgm:feature:saving-face")
    assert saving_face.data["bonus"] == {"type": "ally_count", "maximum": 5}
    assert saving_face.data["trigger"]["ally_count_radius_ft"] == 30


def test_hobgoblin_weapon_choice_is_registry_derived_martial_only_and_unique() -> None:
    registry = load_default_content_registry()
    draft = _draft(_payload(race="vgm:race:hobgoblin"))
    result = compile_builder_draft(draft, registry)
    choice = next(
        item
        for item in result.choices
        if item.source_ref == "vgm:race:hobgoblin"
        and item.option_source == "content:proficiency_choices"
    )

    assert choice.choose_count == 2
    assert len(choice.options) >= 2
    assert "srd5.1:proficiency:martial-weapons" not in {
        option.reference_id for option in choice.options
    }
    for option in choice.options:
        proficiency = registry.get(option.reference_id or "")
        equipment = registry.resolve_reference(
            proficiency.data["reference"], kinds={"equipment"}
        )
        assert equipment.data["weapon_category"] == "Martial"

    duplicate = choice.options[0].option_id
    payload = draft.draft_payload.model_copy(
        update={
            "choice_selections": {
                choice.choice_id: BuilderChoiceSelection(
                    choice_id=choice.choice_id,
                    source_ref=choice.source_ref,
                    selected_option_ids=(duplicate, duplicate),
                )
            }
        }
    )
    duplicate_result = compile_builder_draft(_draft(payload), registry)
    assert "duplicate_starting_choice" in {
        issue.code for issue in duplicate_result.validation.issues
    }


def test_aasimar_requires_matching_subrace_and_grants_parent_once() -> None:
    registry = load_default_content_registry()
    missing = compile_builder_draft(
        _draft(_payload(race="vgm:race:aasimar")), registry
    )
    assert "missing_subrace" in {issue.code for issue in missing.validation.issues}

    mismatch = compile_builder_draft(
        _draft(
            _payload(
                race="vgm:race:aasimar",
                subrace="phb2014:subrace:wood-elf",
            )
        ),
        registry,
    )
    assert "subrace_race_mismatch" in {
        issue.code for issue in mismatch.validation.issues
    }

    _, summary, origin = _origin_for(
        subrace="vgm:subrace:protector-aasimar", level=1
    )
    abilities = {row.ability: row.permanent_bonus for row in summary.ability_scores}
    assert abilities["charisma"] == 2
    assert abilities["wisdom"] == 1
    assert origin.language_refs == (
        "srd5.1:language:common",
        "srd5.1:language:celestial",
    )
    assert origin.feature_refs.count("vgm:feature:healing-hands") == 1
    assert "vgm:feature:radiant-soul" not in origin.feature_refs
    assert any(
        entry.spell_key == "srd5.1:spell:light"
        and entry.source_type == "race"
        and entry.source_key == "vgm:feature:light-bearer"
        for entry in origin.spell_access_entries
    )


@pytest.mark.parametrize(
    ("subrace", "ability", "bonus"),
    [
        ("vgm:subrace:protector-aasimar", "wisdom", 1),
        ("vgm:subrace:scourge-aasimar", "constitution", 1),
        ("vgm:subrace:fallen-aasimar", "strength", 1),
    ],
)
def test_each_aasimar_subrace_applies_its_ability_bonus(
    subrace: str,
    ability: str,
    bonus: int,
) -> None:
    _, summary, _origin = _origin_for(subrace=subrace, level=1)
    abilities = {row.ability: row.permanent_bonus for row in summary.ability_scores}
    assert abilities["charisma"] == 2
    assert abilities[ability] == bonus


@pytest.mark.parametrize(
    ("subrace", "feature"),
    [
        ("vgm:subrace:protector-aasimar", "vgm:feature:radiant-soul"),
        ("vgm:subrace:scourge-aasimar", "vgm:feature:radiant-consumption"),
        ("vgm:subrace:fallen-aasimar", "vgm:feature:necrotic-shroud"),
    ],
)
def test_aasimar_transformation_features_use_character_level_gate(
    subrace: str,
    feature: str,
) -> None:
    _, level_two_summary, level_two_origin = _origin_for(subrace=subrace, level=2)
    _, level_three_summary, level_three_origin = _origin_for(subrace=subrace, level=3)

    assert feature not in level_two_origin.feature_refs
    assert feature not in {
        grant.reference_id for grant in level_two_summary.grants
    }
    assert feature in level_three_origin.feature_refs
    assert feature in {
        grant.reference_id for grant in level_three_summary.grants
    }


def test_aasimar_gate_uses_total_character_level_for_multiclass_progression() -> None:
    registry = load_default_content_registry()
    level_three_payload = _payload(
        race="vgm:race:aasimar",
        subrace="vgm:subrace:protector-aasimar",
        level=3,
    ).model_copy(
        update={
            "level_choices": (
                BuilderLevelChoice(
                    character_level=1,
                    class_ref="srd5.1:class:fighter",
                    hp_method=BuilderHPMethod.FIRST_LEVEL,
                    hp_base_gain=10,
                ),
                BuilderLevelChoice(
                    character_level=2,
                    class_ref="srd5.1:class:fighter",
                    hp_method=BuilderHPMethod.FIXED_AVERAGE,
                    hp_base_gain=6,
                ),
                BuilderLevelChoice(
                    character_level=3,
                    class_ref="srd5.1:class:rogue",
                    hp_method=BuilderHPMethod.FIXED_AVERAGE,
                    hp_base_gain=5,
                ),
            )
        }
    )

    level_three = compile_builder_draft(_draft(level_three_payload), registry)

    # No single class reaches level 3; only the total character level does.
    assert [node.class_ref for node in level_three.resolved_summary.progression] == [
        "srd5.1:class:fighter",
        "srd5.1:class:fighter",
        "srd5.1:class:rogue",
    ]
    assert "vgm:feature:radiant-soul" in {
        grant.reference_id for grant in level_three.resolved_summary.grants
    }

    level_two_payload = _payload(
        race="vgm:race:aasimar",
        subrace="vgm:subrace:protector-aasimar",
        level=2,
    ).model_copy(
        update={
            "level_choices": (
                BuilderLevelChoice(
                    character_level=1,
                    class_ref="srd5.1:class:fighter",
                    hp_method=BuilderHPMethod.FIRST_LEVEL,
                    hp_base_gain=10,
                ),
                BuilderLevelChoice(
                    character_level=2,
                    class_ref="srd5.1:class:rogue",
                    hp_method=BuilderHPMethod.FIXED_AVERAGE,
                    hp_base_gain=5,
                ),
            )
        }
    )
    level_two = compile_builder_draft(_draft(level_two_payload), registry)
    assert "vgm:feature:radiant-soul" not in {
        grant.reference_id for grant in level_two.resolved_summary.grants
    }


def test_vgm_feature_resources_use_deterministic_keys() -> None:
    registry = load_default_content_registry()
    build = _aasimar_build(
        level=3,
        feature_refs=(
            "vgm:feature:healing-hands",
            "vgm:feature:radiant-soul",
        ),
    )

    resources = initial_feature_resource_state(build, registry)
    assert resources["feature:vgm:feature:healing-hands"].remaining == 1
    assert resources["feature:vgm:feature:radiant-soul"].remaining == 1
    assert all(counter.used == 0 for counter in resources.values())


def test_level_up_two_to_three_adds_transformation_resource_without_resting() -> None:
    registry = load_default_content_registry()
    old_build = _aasimar_build(
        level=2,
        feature_refs=("vgm:feature:healing-hands",),
    )
    new_build = _aasimar_build(
        level=3,
        feature_refs=(
            "vgm:feature:healing-hands",
            "vgm:feature:radiant-soul",
        ),
    )
    old_snapshot = deepcopy(old_build.model_dump(mode="python"))
    old_state = CharacterState(
        current_hp=1,
        resources={
            "feature:vgm:feature:healing-hands": ResourceCounter(
                used=1,
                remaining=0,
            )
        },
        hit_dice_state={"d10": 2},
    )

    preview = reconcile_character_state(old_build, old_state, new_build, registry)

    assert preview.can_apply is True
    assert old_build.model_dump(mode="python") == old_snapshot
    assert "vgm:feature:radiant-soul" not in old_build.feature_refs
    assert "vgm:feature:radiant-soul" in new_build.feature_refs
    assert preview.proposed_state.resources[
        "feature:vgm:feature:healing-hands"
    ] == ResourceCounter(used=1, remaining=0)
    assert preview.proposed_state.resources[
        "feature:vgm:feature:radiant-soul"
    ] == ResourceCounter(used=0, remaining=1)


def test_protector_to_fallen_build_edit_reconciles_without_mutating_old_build() -> None:
    registry = load_default_content_registry()
    old_build = _aasimar_build(
        level=3,
        subrace_ref="vgm:subrace:protector-aasimar",
        ability_scores=AbilityScores(
            strength=15,
            dexterity=14,
            constitution=13,
            intelligence=12,
            wisdom=11,
            charisma=10,
        ),
        feature_refs=(
            "vgm:feature:celestial-resistance",
            "vgm:feature:healing-hands",
            "vgm:feature:light-bearer",
            "vgm:feature:radiant-soul",
        ),
    )
    new_build = _aasimar_build(
        level=3,
        subrace_ref="vgm:subrace:fallen-aasimar",
        ability_scores=AbilityScores(
            strength=16,
            dexterity=14,
            constitution=13,
            intelligence=12,
            wisdom=10,
            charisma=10,
        ),
        feature_refs=(
            "vgm:feature:celestial-resistance",
            "vgm:feature:healing-hands",
            "vgm:feature:light-bearer",
            "vgm:feature:necrotic-shroud",
        ),
    )
    old_snapshot = deepcopy(old_build.model_dump(mode="python"))
    old_state = CharacterState(
        current_hp=12,
        temporary_hp=3,
        resources={
            "feature:vgm:feature:healing-hands": ResourceCounter(used=1, remaining=0),
            "feature:vgm:feature:radiant-soul": ResourceCounter(used=0, remaining=1),
        },
        hit_dice_state={"d10": 2},
        inventory_state=[
            InventoryEntry(
                entry_id="inventory:keepsake",
                item_ref="srd5.1:equipment:dagger",
                quantity=1,
            )
        ],
    )

    preview = reconcile_character_state(old_build, old_state, new_build, registry)

    assert preview.can_apply is True
    assert old_build.model_dump(mode="python") == old_snapshot
    assert old_build.subrace_ref == "vgm:subrace:protector-aasimar"
    assert new_build.subrace_ref == "vgm:subrace:fallen-aasimar"
    assert old_build.ability_scores.wisdom == 11
    assert new_build.ability_scores.wisdom == 10
    assert old_build.ability_scores.strength == 15
    assert new_build.ability_scores.strength == 16
    assert "vgm:feature:radiant-soul" in old_build.feature_refs
    assert "vgm:feature:radiant-soul" not in new_build.feature_refs
    assert "vgm:feature:necrotic-shroud" in new_build.feature_refs
    assert new_build.feature_refs.count("vgm:feature:healing-hands") == 1
    assert preview.proposed_state.current_hp == old_state.current_hp
    assert preview.proposed_state.temporary_hp == old_state.temporary_hp
    assert preview.proposed_state.inventory_state == old_state.inventory_state
    assert preview.proposed_state.resources[
        "feature:vgm:feature:healing-hands"
    ] == ResourceCounter(used=1, remaining=0)
    assert "feature:vgm:feature:radiant-soul" not in preview.proposed_state.resources
    assert preview.proposed_state.resources[
        "feature:vgm:feature:necrotic-shroud"
    ] == ResourceCounter(used=0, remaining=1)


def test_scourge_and_fallen_formula_metadata_is_preserved() -> None:
    registry = load_default_content_registry()
    consumption = registry.get("vgm:feature:radiant-consumption")
    assert consumption.data["self_damage"]["type"] == "half_character_level_ceil"
    assert consumption.data["nearby_damage"] == {
        "type": "half_character_level_ceil",
        "damage_type": "radiant",
        "radius_ft": 10,
    }

    shroud = registry.get("vgm:feature:necrotic-shroud")
    assert shroud.data["fear_save_dc"] == {
        "base": 8,
        "add": ["proficiency_bonus", "charisma_modifier"],
    }
