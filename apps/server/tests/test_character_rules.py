from uuid import uuid4

import pytest

from app.content import load_default_content_registry
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character.schemas import NumericOverride, PersistedCharacter
from app.domain.rules.abilities import ability_modifier
from app.domain.rules.character_sheet import build_character_sheet
from app.domain.rules.proficiency import class_level, proficiency_bonus


def _character(build=None, state=None):
    build = build or build_p0_fighter_wizard_fixture()
    state = state or build_p0_fighter_wizard_state(build)
    return PersistedCharacter(
        id=uuid4(),
        name="P0 Test Character",
        ruleset=build.ruleset,
        current_version_id=uuid4(),
        version_no=1,
        build=build,
        state=state,
    )


def test_ability_modifier_examples():
    assert ability_modifier(8) == -1
    assert ability_modifier(10) == 0
    assert ability_modifier(14) == 2
    assert ability_modifier(16) == 3
    assert ability_modifier(18) == 4


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (1, 2),
        (4, 2),
        (5, 3),
        (8, 3),
        (9, 4),
        (12, 4),
        (13, 5),
        (16, 5),
        (17, 6),
        (20, 6),
    ],
)
def test_proficiency_bonus_boundaries(level, expected):
    assert proficiency_bonus(level) == expected


def test_p0_fixture_fixed_derived_expectations():
    registry = load_default_content_registry()
    character = _character()
    build = character.build
    sheet = build_character_sheet(character, registry)

    assert sheet.total_level == 10
    assert class_level(build, "srd5.1:class:fighter") == 5
    assert class_level(build, "srd5.1:class:wizard") == 5
    assert sheet.proficiency_bonus == 4
    assert sheet.saving_throws["strength"] == 7
    assert sheet.saving_throws["constitution"] == 6
    assert sheet.saving_throws["dexterity"] == 2
    assert sheet.skills["athletics"] == 7
    assert sheet.skills["arcana"] == 7
    assert sheet.skills["perception"] == 4
    assert sheet.passive_perception == 14
    assert sheet.armor_class == 18
    assert sheet.max_hp == 74
    assert sheet.initiative_modifier == 2
    assert [(die.die, die.available, die.total) for die in sheet.hit_dice] == [
        ("d10", 5, 5),
        ("d6", 5, 5),
    ]

    wizard = next(
        item
        for item in sheet.spellcasting
        if item.source_key == "srd5.1:class:wizard"
    )
    assert wizard.ability == "intelligence"
    assert wizard.save_dc == 15
    assert wizard.attack_modifier == 7

    prepared = {spell.entry_id: spell.prepared for spell in sheet.spells}
    assert prepared["wizard:fireball"] is True
    assert prepared["wizard:detect-magic"] is False


def test_ac_reads_live_inventory_not_starting_equipment():
    registry = load_default_content_registry()
    character = _character()
    state = character.state.model_copy(
        update={
            "inventory_state": [
                item.model_copy(update={"equipped": False})
                if item.entry_id == "inventory:shield"
                else item
                for item in character.state.inventory_state
            ]
        }
    )
    changed = character.model_copy(update={"state": state})

    assert build_character_sheet(changed, registry).armor_class == 16
    assert changed.build == character.build


def test_effective_con_modifier_recalculates_all_levels():
    registry = load_default_content_registry()
    build = build_p0_fighter_wizard_fixture().model_copy(
        update={
            "numeric_overrides": (
                NumericOverride(key="ability:constitution", value=16),
            )
        }
    )
    sheet = build_character_sheet(_character(build=build), registry)
    assert sheet.abilities["constitution"].modifier == 3
    assert sheet.max_hp == 84


def test_numeric_override_variant_is_applied_last_without_changing_structure():
    registry = load_default_content_registry()
    baseline = build_p0_fighter_wizard_fixture()
    build = baseline.model_copy(
        update={
            "numeric_overrides": (
                NumericOverride(key="ability:strength", value=18),
                NumericOverride(key="ac", value=19),
                NumericOverride(key="max_hp", value=80),
            )
        }
    )
    sheet = build_character_sheet(_character(build=build), registry)

    assert sheet.abilities["strength"].score == 18
    assert sheet.abilities["strength"].modifier == 4
    assert sheet.skills["athletics"] == 8
    assert sheet.saving_throws["strength"] == 8
    assert sheet.armor_class == 19
    assert sheet.max_hp == 80
    assert build.race_ref == baseline.race_ref
    assert build.class_progression == baseline.class_progression
    assert build.feature_refs == baseline.feature_refs
    assert build.spell_access_entries == baseline.spell_access_entries
    assert build.starting_equipment == baseline.starting_equipment
