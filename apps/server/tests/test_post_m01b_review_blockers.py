from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.characters import _canonicalize_prepared_patch
from app.content import ContentEntry, ContentRegistry, load_default_content_registry
from app.domain.character.schemas import (
    CharacterBuild,
    CharacterState,
    ClassLevelChoice,
    PersistedCharacter,
    PreparedSpellSelection,
    SpellAccessEntry,
    SpellcastingProfile,
)
from app.domain.character.validation import CharacterValidationError, validate_state_against_build
from app.domain.rules.character_sheet import build_character_sheet


def _persisted(build: CharacterBuild, state: CharacterState) -> PersistedCharacter:
    version_id = uuid4()
    return PersistedCharacter(
        id=uuid4(),
        name="Review fixture",
        ruleset="dnd5e-2014",
        current_version_id=version_id,
        current_version_no=1,
        build=build,
        state=state,
    )


def _wizard_build(*, prepared_limit: int) -> CharacterBuild:
    registry = load_default_content_registry()
    wizard = registry.stable_key("class", "wizard")
    magic_missile = registry.stable_key("spell", "magic-missile")
    shield = registry.stable_key("spell", "shield")
    return CharacterBuild(
        class_progression=[wizard],
        class_level_choices=[
            ClassLevelChoice(
                class_ref=wizard,
                class_level=1,
                hit_die_choice="fixed",
                hit_die_roll=6,
            )
        ],
        spell_access_entries=[
            SpellAccessEntry(
                entry_id="wizard:magic-missile",
                spell_key=magic_missile,
                access_type="spellbook",
                source_type="class",
                source_key=wizard,
                source_label="Wizard",
                origin="build",
            ),
            SpellAccessEntry(
                entry_id="wizard:shield",
                spell_key=shield,
                access_type="spellbook",
                source_type="class",
                source_key=wizard,
                source_label="Wizard",
                origin="build",
            ),
        ],
        spellcasting_profiles=[
            SpellcastingProfile(
                profile_id="class:wizard",
                source_type="class",
                source_key=wizard,
                source_label="Wizard",
                ability="intelligence",
                access_model="spellbook",
                prepared_limit=prepared_limit,
            )
        ],
    )


def test_duplicate_known_spell_access_does_not_consume_known_count_twice() -> None:
    registry = load_default_content_registry()
    bard = registry.stable_key("class", "bard")
    spell = registry.stable_key("spell", "healing-word")
    build = CharacterBuild(
        class_progression=[bard],
        spell_access_entries=[
            SpellAccessEntry(
                entry_id="bard:healing-word:one",
                spell_key=spell,
                access_type="known",
                source_type="class",
                source_key=bard,
                source_label="Bard",
                origin="build",
            ),
            SpellAccessEntry(
                entry_id="bard:healing-word:two",
                spell_key=spell,
                access_type="known",
                source_type="class",
                source_key=bard,
                source_label="Bard",
                origin="build",
            ),
        ],
        spellcasting_profiles=[
            SpellcastingProfile(
                profile_id="class:bard",
                source_type="class",
                source_key=bard,
                source_label="Bard",
                ability="charisma",
                access_model="known",
                known_count=1,
            )
        ],
    )

    validate_state_against_build(CharacterState(current_hp=8), build, registry)


def test_prepared_spell_source_is_rendered_on_character_sheet() -> None:
    registry = load_default_content_registry()
    cleric = registry.stable_key("class", "cleric")
    cure_wounds = registry.stable_key("spell", "cure-wounds")
    healing_word = registry.stable_key("spell", "healing-word")
    build = CharacterBuild(
        class_progression=[cleric],
        spell_access_entries=[
            SpellAccessEntry(
                entry_id="cleric:cure-wounds",
                spell_key=cure_wounds,
                access_type="prepared",
                source_type="class",
                source_key=cleric,
                source_label="Cleric",
                origin="build",
            ),
            SpellAccessEntry(
                entry_id="cleric:healing-word",
                spell_key=healing_word,
                access_type="prepared",
                source_type="class",
                source_key=cleric,
                source_label="Cleric",
                origin="build",
            ),
        ],
        spellcasting_profiles=[
            SpellcastingProfile(
                profile_id="class:cleric",
                source_type="class",
                source_key=cleric,
                source_label="Cleric",
                ability="wisdom",
                access_model="prepared",
                max_spell_level=1,
                prepared_limit=2,
            ),
        ],
    )
    state = CharacterState(
        current_hp=9,
        prepared_spells=[
            PreparedSpellSelection(
                spell_key="srd5.1:spell:cure-wounds",
                source_profile_id="class:cleric",
            )
        ],
        hit_dice_state={"d8": 1},
    )

    sheet = build_character_sheet(_persisted(build, state), load_default_content_registry())
    cure_wounds = next(spell for spell in sheet.spells if spell.spell_key.endswith(":cure-wounds"))

    assert cure_wounds.access_type == "prepared"
    assert cure_wounds.prepared is True
    assert cure_wounds.source_profile_id == "class:cleric"
    assert any(spell.access_type == "prepared" and not spell.prepared for spell in sheet.spells)
    assert any(source.source_key == cleric for source in sheet.spellcasting)


def test_legacy_sheet_patch_is_translated_before_prepared_limit_validation() -> None:
    build = _wizard_build(prepared_limit=1)
    character = _persisted(build, CharacterState(current_hp=7))
    changes: dict[str, object] = {
        "prepared_spell_entry_ids": ["wizard:magic-missile", "wizard:shield"]
    }

    _canonicalize_prepared_patch(build, character.state, changes)

    assert changes["prepared_spell_entry_ids"] == []
    assert len(changes["prepared_spells"]) == 2
    candidate = CharacterState.model_validate(
        {**character.state.model_dump(mode="python"), **changes}
    )
    with pytest.raises(CharacterValidationError, match="exceeds profile limit"):
        validate_state_against_build(candidate, build, load_default_content_registry())


def test_non_srd_spell_and_class_level_runtime_lookups_are_source_aware() -> None:
    base_registry = load_default_content_registry()
    artificer_ref = "tce:class:artificer"
    spell_ref = "tce:spell:fixture-spell"
    entries = {
        artificer_ref: ContentEntry(
            key=artificer_ref,
            type="class",
            name="Artificer",
            source="TCE",
            description=None,
            data={
                "hit_die": 8,
                "levels": [
                    {
                        "level": 1,
                        "prof_bonus": 2,
                        "features": [],
                        "spellcasting": {"cantrips_known": 2, "spells_known": 0},
                    }
                ],
            },
        ),
        spell_ref: ContentEntry(
            key=spell_ref,
            type="spell",
            name="Fixture Spell",
            source="TCE",
            description=None,
            data={"level": 0, "school": "Evocation"},
        ),
    }
    registry = ContentRegistry([*base_registry.values(), *entries.values()])
    build = CharacterBuild(
        class_progression=[artificer_ref],
        class_level_choices=[
            ClassLevelChoice(
                class_ref=artificer_ref,
                class_level=1,
                hit_die_choice="fixed",
                hit_die_roll=5,
            )
        ],
        spell_access_entries=[
            SpellAccessEntry(
                entry_id="artificer:fixture-spell",
                spell_key=spell_ref,
                access_type="known",
                source_type="class",
                source_key=artificer_ref,
                source_label="Artificer",
                origin="build",
            )
        ],
        spellcasting_profiles=[
            SpellcastingProfile(
                profile_id="class:artificer",
                source_type="class",
                source_key=artificer_ref,
                source_label="Artificer",
                ability="intelligence",
                access_model="known",
                known_count=1,
            )
        ],
    )
    state = CharacterState(current_hp=8)

    validate_state_against_build(state, build, registry)
    sheet = build_character_sheet(_persisted(build, state), registry)

    assert sheet.spellcasting[0].source_key == artificer_ref
    assert any(spell.spell_key == spell_ref for spell in sheet.spells)
