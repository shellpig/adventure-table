from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character.validation import validate_build_references
from app.domain.character_builder.compiler import compile_builder_draft
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderLevelChoice,
    BuilderMode,
    BuilderReferenceSelection,
)


DIRECT_SOURCES = {
    "content:race",
    "content:background",
    "content:alignment",
    "content:subrace",
    "content:class",
    "content:subclass",
    "builder:ability-generation",
}


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


def _payload(*, race: str, subrace: str) -> BuilderDraftPayload:
    return BuilderDraftPayload(
        basic=BuilderBasicInput(name="M01-B Subrace Matrix"),
        target_level=1,
        race_selection=BuilderReferenceSelection(reference_id=race),
        subrace_selection=BuilderReferenceSelection(reference_id=subrace),
        background_selection=BuilderReferenceSelection(
            reference_id="phb2014:background:soldier"
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
        level_choices=(
            BuilderLevelChoice(
                character_level=1,
                class_ref="srd5.1:class:fighter",
                hp_method="first_level",
                hp_base_gain=10,
            ),
        ),
    )


def _complete(payload: BuilderDraftPayload, registry) -> BuilderDraftPayload:
    selections = dict(payload.choice_selections)
    equipment = dict(payload.starting_equipment_choices)
    used_refs: set[str] = set()

    for _ in range(128):
        current = payload.model_copy(
            update={
                "choice_selections": selections,
                "starting_equipment_choices": equipment,
            }
        )
        result = compile_builder_draft(_draft(current), registry)

        unresolved = next(
            (
                choice
                for choice in result.choices
                if choice.required
                and choice.disabled_reason is None
                and choice.option_source not in DIRECT_SOURCES
                and choice.option_source != "equipment"
                and choice.choice_id not in selections
            ),
            None,
        )
        if unresolved is not None:
            eligible = [
                option
                for option in unresolved.options
                if option.disabled_reason is None
                and (option.reference_id is None or option.reference_id not in used_refs)
            ]
            selected = eligible[: unresolved.choose_count]
            assert len(selected) == unresolved.choose_count, unresolved.choice_id
            selections[unresolved.choice_id] = BuilderChoiceSelection(
                choice_id=unresolved.choice_id,
                source_ref=unresolved.source_ref,
                selected_option_ids=tuple(option.option_id for option in selected),
            )
            used_refs.update(
                option.reference_id
                for option in selected
                if option.reference_id is not None
            )
            continue

        unresolved_equipment = next(
            (
                choice
                for choice in result.choices
                if choice.required
                and choice.disabled_reason is None
                and choice.option_source == "equipment"
                and choice.choice_id not in equipment
            ),
            None,
        )
        if unresolved_equipment is not None:
            eligible = [
                option
                for option in unresolved_equipment.options
                if option.disabled_reason is None
            ]
            selected = eligible[: unresolved_equipment.choose_count]
            assert len(selected) == unresolved_equipment.choose_count
            equipment[unresolved_equipment.choice_id] = [
                option.option_id for option in selected
            ]
            continue

        return current

    raise AssertionError("M01-B subrace fixture could not resolve all required choices")


def _compile(*, race: str, subrace: str):
    registry = load_default_content_registry()
    payload = _complete(_payload(race=race, subrace=subrace), registry)
    result = compile_builder_draft(_draft(payload), registry)
    assert result.validation.can_confirm is True
    assert result.build_candidate is not None
    validate_build_references(result.build_candidate, registry)
    return result.build_candidate


def test_drow_combines_base_elf_and_subrace_grants_once() -> None:
    build = _compile(race="srd5.1:race:elf", subrace="phb2014:subrace:drow")

    assert build.ability_scores.dexterity == 16
    assert build.ability_scores.charisma == 9
    assert {
        "phb2014:feature:superior-darkvision",
        "phb2014:feature:sunlight-sensitivity",
        "phb2014:feature:drow-magic",
    }.issubset(set(build.feature_refs))
    assert {
        "srd5.1:proficiency:rapiers",
        "srd5.1:proficiency:shortswords",
        "srd5.1:proficiency:hand-crossbows",
    }.issubset(set(build.proficiencies))
    racial_spells = [entry for entry in build.spell_access_entries if entry.source_type == "race"]
    assert {entry.spell_key for entry in racial_spells} == {"srd5.1:spell:dancing-lights"}
    assert all(entry.source_key == "phb2014:feature:drow-magic" for entry in racial_spells)


def test_mountain_dwarf_combines_base_and_subrace_ability_and_armor_grants_once() -> None:
    build = _compile(
        race="srd5.1:race:dwarf",
        subrace="phb2014:subrace:mountain-dwarf",
    )

    assert build.ability_scores.strength == 17
    assert build.ability_scores.constitution == 15
    assert "srd5.1:proficiency:light-armor" in build.proficiencies
    assert "srd5.1:proficiency:medium-armor" in build.proficiencies
    assert len(build.proficiencies) == len(set(build.proficiencies))


def test_stout_halfling_combines_base_dexterity_and_stout_resilience() -> None:
    build = _compile(
        race="srd5.1:race:halfling",
        subrace="phb2014:subrace:stout-halfling",
    )

    assert build.ability_scores.dexterity == 16
    assert build.ability_scores.constitution == 14
    assert "phb2014:feature:stout-resilience" in build.feature_refs
    assert len(build.feature_refs) == len(set(build.feature_refs))


def test_forest_gnome_combines_base_intelligence_and_racial_cantrip() -> None:
    build = _compile(
        race="srd5.1:race:gnome",
        subrace="phb2014:subrace:forest-gnome",
    )

    assert build.ability_scores.intelligence == 14
    assert build.ability_scores.dexterity == 15
    assert "phb2014:feature:natural-illusionist" in build.feature_refs
    assert "phb2014:feature:speak-with-small-beasts" in build.feature_refs
    racial_spells = [entry for entry in build.spell_access_entries if entry.source_type == "race"]
    assert {entry.spell_key for entry in racial_spells} == {"srd5.1:spell:minor-illusion"}
    assert all(
        entry.source_key == "phb2014:feature:natural-illusionist"
        for entry in racial_spells
    )
