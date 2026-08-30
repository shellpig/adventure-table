from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.characters import _canonicalize_prepared_patch
from app.content import load_default_content_registry
from app.content.registry import ContentRegistry, ContentValidationError
from app.content.schemas import ContentEntry
from app.domain.character.schemas import (
    AbilityScores,
    CharacterBuild,
    CharacterState,
    PersistedCharacter,
    PreparedSpellSelection,
    SpellAccessEntry,
    SpellcastingProfile,
)
from app.domain.character.validation import CharacterValidationError, validate_state_against_build
from app.domain.rules.character_sheet import build_character_sheet
from app.domain.rules.spellcasting import max_spell_level_for_class, spell_is_on_class_list
from test_m01a_content_packs import entry, feature, write_pack


def _abilities() -> AbilityScores:
    return AbilityScores(
        strength=10,
        dexterity=12,
        constitution=12,
        intelligence=16,
        wisdom=16,
        charisma=8,
    )


def _persisted(build: CharacterBuild, state: CharacterState, name: str = "Regression") -> PersistedCharacter:
    return PersistedCharacter(
        id=uuid4(),
        name=name,
        ruleset="dnd5e-2014",
        current_version_id=uuid4(),
        version_no=1,
        build=build,
        state=state,
    )


def _wizard_build(*, prepared_limit: int = 1) -> CharacterBuild:
    wizard = "srd5.1:class:wizard"
    return CharacterBuild(
        race_ref="srd5.1:race:human",
        character_level=1,
        class_progression=(wizard,),
        ability_scores=_abilities(),
        hp_progression=(6,),
        spellcasting_profiles=(
            SpellcastingProfile(
                profile_id="class:wizard",
                source_type="class",
                source_key=wizard,
                class_ref=wizard,
                ability="intelligence",
                access_model="spellbook",
                resource_pool_type="normal_multiclass_slots",
                max_spell_level=1,
                prepared_limit=prepared_limit,
            ),
        ),
        spell_access_entries=(
            SpellAccessEntry(
                entry_id="wizard:magic-missile",
                spell_key="srd5.1:spell:magic-missile",
                source_type="class",
                source_key=wizard,
                access_type="spellbook",
            ),
            SpellAccessEntry(
                entry_id="wizard:shield",
                spell_key="srd5.1:spell:shield",
                source_type="class",
                source_key=wizard,
                access_type="spellbook",
            ),
        ),
    )


def test_character_sheet_reads_p1_canonical_wizard_prepared_state() -> None:
    build = _wizard_build(prepared_limit=2)
    state = CharacterState(
        current_hp=7,
        prepared_spells=[
            PreparedSpellSelection(
                spell_key="srd5.1:spell:magic-missile",
                source_profile_id="class:wizard",
                source_access_entry_id="wizard:magic-missile",
            )
        ],
        hit_dice_state={"d6": 1},
    )

    sheet = build_character_sheet(_persisted(build, state), load_default_content_registry())
    magic_missile = next(spell for spell in sheet.spells if spell.spell_key.endswith(":magic-missile"))
    shield = next(spell for spell in sheet.spells if spell.spell_key.endswith(":shield"))

    assert magic_missile.prepared is True
    assert magic_missile.source_profile_id == "class:wizard"
    assert magic_missile.source_access_entry_id == "wizard:magic-missile"
    assert shield.prepared is False


def test_character_sheet_exposes_full_list_prepared_caster_spells() -> None:
    cleric = "srd5.1:class:cleric"
    build = CharacterBuild(
        race_ref="srd5.1:race:human",
        character_level=1,
        class_progression=(cleric,),
        ability_scores=_abilities(),
        hp_progression=(8,),
        spellcasting_profiles=(
            SpellcastingProfile(
                profile_id="class:cleric",
                source_type="class",
                source_key=cleric,
                class_ref=cleric,
                ability="wisdom",
                access_model="prepared",
                resource_pool_type="normal_multiclass_slots",
                max_spell_level=1,
                prepared_limit=2,
            ),
        ),
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

    _canonicalize_prepared_patch(character, changes)

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
            index="artificer",
            name="Artificer",
            source="tce",
            ruleset="dnd5e-2014",
            data={"index": "artificer", "name": "Artificer", "hit_die": 8},
        ),
        spell_ref: ContentEntry(
            key=spell_ref,
            index="fixture-spell",
            name="Fixture Spell",
            source="tce",
            ruleset="dnd5e-2014",
            data={
                "index": "fixture-spell",
                "name": "Fixture Spell",
                "level": 1,
                "classes": [{"key": artificer_ref, "name": "Artificer"}],
            },
        ),
        "tce:level:artificer-1": ContentEntry(
            key="tce:level:artificer-1",
            index="artificer-1",
            name="Artificer 1",
            source="tce",
            ruleset="dnd5e-2014",
            data={
                "index": "artificer-1",
                "name": "Artificer 1",
                "level": 1,
                "class": {"key": artificer_ref, "name": "Artificer"},
                "features": [],
                "prof_bonus": 2,
                "spellcasting": {"spell_slots_level_1": 2},
            },
        ),
    }
    registry = ContentRegistry(
        base_registry.manifest,
        entries,
        {
            "class": (entries[artificer_ref],),
            "spell": (entries[spell_ref],),
            "level": (entries["tce:level:artificer-1"],),
        },
    )
    build = CharacterBuild(
        race_ref="srd5.1:race:human",
        character_level=1,
        class_progression=(artificer_ref,),
        ability_scores=_abilities(),
        hp_progression=(8,),
    )

    assert spell_is_on_class_list(spell_ref, artificer_ref, registry) is True
    assert max_spell_level_for_class(build, artificer_ref, registry) == 1


def test_equipment_cross_reference_rejects_existing_wrong_kind(tmp_path) -> None:
    write_pack(
        tmp_path,
        "pack-a",
        "Pack A",
        {
            "features": ("feature", [feature("pack-a", "one", "One")]),
            "equipment-categories": (
                "equipment-category",
                [
                    entry(
                        "pack-a",
                        "equipment-category",
                        "bad-category",
                        "Bad Category",
                        {
                            "equipment": [
                                {"key": "pack-a:feature:one", "name": "One"}
                            ]
                        },
                    )
                ],
            ),
        },
    )

    with pytest.raises(ContentValidationError, match="wrong-kind reference"):
        ContentRegistry.from_root(tmp_path, ("pack-a",))
