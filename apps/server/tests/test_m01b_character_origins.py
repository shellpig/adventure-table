from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character.validation import validate_build_references
from app.domain.character_builder.compiler import compile_builder_draft
from app.domain.character_builder.origin import compile_origin
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderGrantSummary,
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


def _base_payload(
    *,
    race: str,
    background: str = "phb2014:background:soldier",
    subrace: str | None = None,
) -> BuilderDraftPayload:
    return BuilderDraftPayload(
        basic=BuilderBasicInput(name="M01-B Hero"),
        target_level=1,
        race_selection=BuilderReferenceSelection(reference_id=race),
        subrace_selection=(
            BuilderReferenceSelection(reference_id=subrace) if subrace else None
        ),
        background_selection=BuilderReferenceSelection(reference_id=background),
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


def _complete_required_choices(payload: BuilderDraftPayload, registry) -> BuilderDraftPayload:
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
            assert len(selected) == unresolved_equipment.choose_count, unresolved_equipment.choice_id
            equipment[unresolved_equipment.choice_id] = [
                option.option_id for option in selected
            ]
            continue

        return current

    raise AssertionError("M01-B fixture could not resolve all required choices")


def test_phb_pack_contains_required_backgrounds_and_variants() -> None:
    registry = load_default_content_registry()
    backgrounds = registry.list_kind("background", source="phb2014")

    assert len(backgrounds) == 18
    assert {entry.index for entry in backgrounds} >= {
        "acolyte",
        "charlatan",
        "criminal",
        "spy",
        "entertainer",
        "gladiator",
        "folk-hero",
        "guild-artisan",
        "guild-merchant",
        "hermit",
        "noble",
        "knight",
        "outlander",
        "sage",
        "sailor",
        "pirate",
        "soldier",
        "urchin",
    }
    for entry in backgrounds:
        assert entry.data.get("feature")
        suggestions = entry.data.get("roleplay_suggestions")
        assert isinstance(suggestions, dict)
        assert set(suggestions) == {
            "personality_traits",
            "ideals",
            "bonds",
            "flaws",
        }
        assert all(suggestions[key] for key in suggestions)

    assert registry.get("phb2014:background:spy").data["variant_of"]["key"] == "phb2014:background:criminal"
    assert registry.get("phb2014:background:gladiator").data["variant_of"]["key"] == "phb2014:background:entertainer"
    assert registry.get("phb2014:background:knight").data["variant_of"]["key"] == "phb2014:background:noble"
    assert registry.get("phb2014:background:pirate").data["variant_of"]["key"] == "phb2014:background:sailor"


def test_cross_source_subrace_is_eligible_and_compiles_as_its_own_identity() -> None:
    registry = load_default_content_registry()
    payload = _base_payload(
        race="srd5.1:race:elf",
        subrace="phb2014:subrace:wood-elf",
    )
    initial = compile_builder_draft(_draft(payload), registry)
    subrace_choice = next(
        choice for choice in initial.choices if choice.option_source == "content:subrace"
    )
    assert "phb2014:subrace:wood-elf" in {
        option.option_id for option in subrace_choice.options
    }

    completed = _complete_required_choices(payload, registry)
    result = compile_builder_draft(_draft(completed), registry)
    assert result.validation.can_confirm is True
    assert result.build_candidate is not None
    build = result.build_candidate
    assert build.race_ref == "srd5.1:race:elf"
    assert build.subrace_ref == "phb2014:subrace:wood-elf"
    assert "phb2014:feature:mask-of-the-wild" in build.feature_refs
    assert build.ability_scores.wisdom == 11
    assert set(build.content_sources) >= {"srd5.1", "phb2014"}
    validate_build_references(build, registry)


def test_variant_human_choices_persist_feat_skill_language_and_distinct_ability_bonuses() -> None:
    registry = load_default_content_registry()
    payload = _base_payload(race="phb2014:race:variant-human")
    completed = _complete_required_choices(payload, registry)
    result = compile_builder_draft(_draft(completed), registry)

    assert result.validation.can_confirm is True
    assert result.build_candidate is not None
    build = result.build_candidate
    assert build.race_ref == "phb2014:race:variant-human"
    assert build.subrace_ref is None
    assert build.feat_refs == ("srd5.1:feat:grappler",)
    assert "srd5.1:language:common" in build.language_refs
    assert len(build.language_refs) == 2
    assert len(build.skill_choices) >= 1

    selected_ability_choice = next(
        choice
        for choice in result.choices
        if choice.option_source == "content:ability_bonus_options"
        and choice.source_ref == "phb2014:race:variant-human"
    )
    selected = completed.choice_selections[selected_ability_choice.choice_id].selected_option_ids
    assert len(selected) == 2
    assert len(set(selected)) == 2
    bonuses = [
        score.permanent_bonus
        for score in result.resolved_summary.ability_scores
        if score.permanent_bonus
    ]
    assert bonuses.count(1) >= 2
    validate_build_references(build, registry)


def test_variant_human_duplicate_ability_and_illegal_feat_are_blocking() -> None:
    registry = load_default_content_registry()
    payload = _base_payload(race="phb2014:race:variant-human")
    first = compile_builder_draft(_draft(payload), registry)
    ability_choice = next(
        choice
        for choice in first.choices
        if choice.option_source == "content:ability_bonus_options"
        and choice.source_ref == "phb2014:race:variant-human"
    )
    duplicate = ability_choice.options[0].option_id
    bad_payload = payload.model_copy(
        update={
            "choice_selections": {
                ability_choice.choice_id: BuilderChoiceSelection(
                    choice_id=ability_choice.choice_id,
                    source_ref=ability_choice.source_ref,
                    selected_option_ids=(duplicate, duplicate),
                )
            }
        }
    )
    result = compile_builder_draft(_draft(bad_payload), registry)
    assert any(
        issue.severity.value == "blocking_error"
        and "duplicate" in issue.code
        for issue in result.validation.issues
    )

    weak = _base_payload(race="phb2014:race:variant-human").model_copy(
        update={
            "ability_generation": {
                "method": "standard_array",
                "scores": {
                    "strength": 8,
                    "dexterity": 15,
                    "constitution": 14,
                    "intelligence": 13,
                    "wisdom": 12,
                    "charisma": 10,
                },
            }
        }
    )
    weak_first = compile_builder_draft(_draft(weak), registry)
    feat_choice = next(
        choice
        for choice in weak_first.choices
        if choice.option_source == "content:race-feat"
    )
    grappler = next(
        option for option in feat_choice.options if option.reference_id == "srd5.1:feat:grappler"
    )
    assert grappler.disabled_reason is not None


def test_racial_spells_use_feature_source_identity_and_character_level_gates() -> None:
    registry = load_default_content_registry()
    drow_grant = BuilderGrantSummary(
        label="Drow Magic",
        kind="feature",
        source_ref="phb2014:subrace:drow",
        reference_id="phb2014:feature:drow-magic",
    )

    level_one = compile_origin(grants=(drow_grant,), target_level=1, registry=registry)
    assert {entry.spell_key for entry in level_one.spell_access_entries} == {
        "srd5.1:spell:dancing-lights"
    }
    assert all(entry.source_type == "race" for entry in level_one.spell_access_entries)
    assert all(
        entry.source_key == "phb2014:feature:drow-magic"
        for entry in level_one.spell_access_entries
    )
    assert all(entry.access_type == "granted" for entry in level_one.spell_access_entries)

    level_five = compile_origin(grants=(drow_grant,), target_level=5, registry=registry)
    assert {entry.spell_key for entry in level_five.spell_access_entries} == {
        "srd5.1:spell:dancing-lights",
        "srd5.1:spell:faerie-fire",
        "srd5.1:spell:darkness",
    }
