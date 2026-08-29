from __future__ import annotations

from app.domain.character.schemas import (
    AbilityScores,
    CharacterBuild,
    CharacterState,
    InventoryEntry,
    ResourceCounter,
    SpellAccessEntry,
    StartingEquipmentEntry,
    SubclassSelection,
)


P0_FIXTURE_NAME = "P0 Human Fighter 5 / Wizard 5"


def build_p0_fighter_wizard_fixture() -> CharacterBuild:
    fighter = "srd5.1:class:fighter"
    wizard = "srd5.1:class:wizard"

    return CharacterBuild(
        race_ref="srd5.1:race:human",
        background_ref="srd5.1:background:acolyte",
        character_level=10,
        class_progression=(fighter,) * 5 + (wizard,) * 5,
        subclasses=(
            SubclassSelection(
                class_ref=fighter,
                subclass_ref="srd5.1:subclass:champion",
            ),
            SubclassSelection(
                class_ref=wizard,
                subclass_ref="srd5.1:subclass:evocation",
            ),
        ),
        ability_scores=AbilityScores(
            strength=16,
            dexterity=14,
            constitution=14,
            intelligence=16,
            wisdom=10,
            charisma=8,
        ),
        saving_throw_proficiencies=(
            "srd5.1:ability:str",
            "srd5.1:ability:con",
        ),
        skill_choices=(
            "srd5.1:skill:athletics",
            "srd5.1:skill:arcana",
            "srd5.1:skill:perception",
        ),
        feature_refs=(
            "srd5.1:feature:second-wind",
            "srd5.1:feature:arcane-recovery",
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
            SpellAccessEntry(
                entry_id="wizard:detect-magic",
                spell_key="srd5.1:spell:detect-magic",
                source_type="class",
                source_key=wizard,
                access_type="spellbook",
            ),
            SpellAccessEntry(
                entry_id="wizard:fireball",
                spell_key="srd5.1:spell:fireball",
                source_type="class",
                source_key=wizard,
                access_type="spellbook",
            ),
        ),
        hp_progression=(10, 6, 6, 6, 6, 4, 4, 4, 4, 4),
        starting_equipment=(
            StartingEquipmentEntry(
                entry_id="starting:chain-mail",
                item_ref="srd5.1:equipment:chain-mail",
                quantity=1,
            ),
            StartingEquipmentEntry(
                entry_id="starting:shield",
                item_ref="srd5.1:equipment:shield",
                quantity=1,
            ),
            StartingEquipmentEntry(
                entry_id="starting:longsword",
                item_ref="srd5.1:equipment:longsword",
                quantity=1,
            ),
            StartingEquipmentEntry(
                entry_id="starting:healing-potion",
                item_ref="srd5.1:item:potion-of-healing-common",
                quantity=2,
            ),
        ),
    )


def initialize_inventory_from_starting_equipment(
    build: CharacterBuild,
) -> list[InventoryEntry]:
    """Create the one-time initial live inventory from the immutable Build choices."""
    return [
        InventoryEntry(
            entry_id=f"inventory:{entry.entry_id.removeprefix('starting:')}",
            item_ref=entry.item_ref,
            quantity=entry.quantity,
        )
        for entry in build.starting_equipment
    ]


def build_p0_fighter_wizard_state(
    build: CharacterBuild | None = None,
) -> CharacterState:
    build = build or build_p0_fighter_wizard_fixture()
    equipped_ids = {
        "inventory:chain-mail",
        "inventory:shield",
        "inventory:longsword",
    }
    initial_inventory = [
        entry.model_copy(update={"equipped": entry.entry_id in equipped_ids})
        for entry in initialize_inventory_from_starting_equipment(build)
    ]

    return CharacterState(
        current_hp=74,
        temporary_hp=0,
        prepared_spell_entry_ids=[
            "wizard:magic-missile",
            "wizard:shield",
            "wizard:fireball",
        ],
        spell_slots={
            1: ResourceCounter(used=1, remaining=3),
            2: ResourceCounter(used=0, remaining=3),
            3: ResourceCounter(used=1, remaining=1),
        },
        resources={
            "wizard:arcane-recovery": ResourceCounter(used=0, remaining=1),
        },
        hit_dice_state={"d10": 5, "d6": 5},
        inventory_state=initial_inventory,
    )