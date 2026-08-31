from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.content import load_default_content_registry
from app.domain.character.schemas import AbilityScores, CharacterBuild
from app.domain.character.validation import CharacterValidationError, validate_build_references
from app.domain.character_builder.basics import resolve_creation_summary
from app.domain.character_builder.choices import build_foundation_choices
from app.domain.character_builder.origin import compile_origin
from app.domain.character_builder.race_variants import (
    RACE_VARIANT_REPLACEMENT_OPTION_SOURCE,
    RACE_VARIANT_SPELL_OPTION_SOURCE,
    apply_race_variant_summary,
    build_race_variant_choices,
    compile_race_variant,
    suppress_replaced_foundation_choices,
    validate_race_variant,
)
from app.domain.character_builder.schemas import (
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderMode,
    BuilderReferenceSelection,
)
from app.domain.rules.spellcasting import spell_is_on_class_list


HALF_ELF = "srd5.1:race:half-elf"
SKILL_VERSATILITY = "srd5.1:trait:skill-versatility"
WIZARD = "srd5.1:class:wizard"

MOON_SUN = "scag:race-variant:half-elf-moon-sun-descent"
WOOD = "scag:race-variant:half-elf-wood-descent"
AQUATIC = "scag:race-variant:half-elf-aquatic-descent"
DROW = "scag:race-variant:half-elf-drow-descent"


def _draft(
    *,
    variant: str | None = None,
    level: int = 1,
    selections: dict[str, BuilderChoiceSelection] | None = None,
    race: str = HALF_ELF,
) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=BuilderDraftPayload(
            target_level=level,
            race_selection=BuilderReferenceSelection(reference_id=race),
            race_variant_selection=(
                BuilderReferenceSelection(reference_id=variant) if variant else None
            ),
            choice_selections=selections or {},
        ),
        created_at=now,
        updated_at=now,
    )


def _replacement_choice(draft: BuilderDraft):
    registry = load_default_content_registry()
    return next(
        choice
        for choice in build_race_variant_choices(draft, registry)
        if choice.option_source == RACE_VARIANT_REPLACEMENT_OPTION_SOURCE
    )


def _select_variant_option(
    variant: str,
    option_id: str,
    *,
    level: int = 1,
    extra: dict[str, BuilderChoiceSelection] | None = None,
) -> BuilderDraft:
    base = _draft(variant=variant, level=level)
    choice = _replacement_choice(base)
    selections = dict(extra or {})
    selections[choice.choice_id] = BuilderChoiceSelection(
        choice_id=choice.choice_id,
        source_ref=choice.source_ref,
        selected_option_ids=(option_id,),
    )
    return _draft(variant=variant, level=level, selections=selections)


def _summary(draft: BuilderDraft):
    registry = load_default_content_registry()
    foundation = build_foundation_choices(draft, registry)
    variant_choices = build_race_variant_choices(draft, registry)
    effective = suppress_replaced_foundation_choices(
        draft, registry, foundation
    ) + variant_choices
    summary = resolve_creation_summary(draft, registry, effective)
    return registry, effective, apply_race_variant_summary(
        draft, registry, effective, summary
    )


def _skill_versatility_choice():
    registry = load_default_content_registry()
    baseline = _draft()
    return next(
        choice
        for choice in build_foundation_choices(baseline, registry)
        if choice.source_ref == SKILL_VERSATILITY
        and choice.option_source == "content:starting_proficiency_options"
    )


def test_baseline_half_elf_keeps_skill_versatility_without_scag_variant() -> None:
    registry = load_default_content_registry()
    draft = _draft()
    choices = build_foundation_choices(draft, registry)

    skill_choice = next(
        choice
        for choice in choices
        if choice.source_ref == SKILL_VERSATILITY
        and choice.option_source == "content:starting_proficiency_options"
    )

    assert skill_choice.choose_count == 2
    assert len(skill_choice.options) >= 2
    assert not build_race_variant_choices(_draft(race="srd5.1:race:human"), registry)


def test_half_elf_exposes_four_scag_ancestry_variants_only_for_half_elf() -> None:
    registry = load_default_content_registry()
    choices = build_race_variant_choices(_draft(), registry)
    selector = next(choice for choice in choices if choice.option_source == "content:race-variant")

    assert {option.reference_id for option in selector.options} == {
        MOON_SUN,
        WOOD,
        AQUATIC,
        DROW,
    }

    assert not build_race_variant_choices(_draft(race="srd5.1:race:human"), registry)


def test_keep_skill_versatility_preserves_two_skill_branch_and_grants() -> None:
    skill_choice = _skill_versatility_choice()
    selected_skills = tuple(option.option_id for option in skill_choice.options[:2])
    variant_base = _draft(variant=WOOD)
    replacement = _replacement_choice(variant_base)
    draft = _draft(
        variant=WOOD,
        selections={
            skill_choice.choice_id: BuilderChoiceSelection(
                choice_id=skill_choice.choice_id,
                source_ref=skill_choice.source_ref,
                selected_option_ids=selected_skills,
            ),
            replacement.choice_id: BuilderChoiceSelection(
                choice_id=replacement.choice_id,
                source_ref=replacement.source_ref,
                selected_option_ids=("keep-skill-versatility",),
            ),
        },
    )

    _registry, effective, summary = _summary(draft)

    assert any(choice.choice_id == skill_choice.choice_id for choice in effective)
    assert SKILL_VERSATILITY in {grant.reference_id for grant in summary.grants}
    assert set(selected_skills).issubset(
        {grant.reference_id for grant in summary.grants if grant.kind == "proficiency"}
    )


def test_replacement_suppresses_stale_skill_versatility_branch() -> None:
    skill_choice = _skill_versatility_choice()
    selected_skills = tuple(option.option_id for option in skill_choice.options[:2])
    wood = _select_variant_option(
        WOOD,
        "fleet-of-foot",
        extra={
            skill_choice.choice_id: BuilderChoiceSelection(
                choice_id=skill_choice.choice_id,
                source_ref=skill_choice.source_ref,
                selected_option_ids=selected_skills,
            )
        },
    )

    registry, effective, summary = _summary(wood)
    compilation = compile_race_variant(wood, registry, effective)

    assert all(choice.choice_id != skill_choice.choice_id for choice in effective)
    assert SKILL_VERSATILITY not in {grant.reference_id for grant in summary.grants}
    assert not set(selected_skills).intersection(
        {grant.reference_id for grant in summary.grants if grant.kind == "proficiency"}
    )
    assert "scag:feature:half-elf-fleet-of-foot" in {
        grant.reference_id for grant in summary.grants
    }
    assert compilation.walking_speed == 35


def test_stale_variant_child_choices_do_not_pollute_active_branch_and_ids_are_stable() -> None:
    wood_base = _draft(variant=WOOD)
    wood_choice = _replacement_choice(wood_base)
    wood_selection = BuilderChoiceSelection(
        choice_id=wood_choice.choice_id,
        source_ref=wood_choice.source_ref,
        selected_option_ids=("fleet-of-foot",),
    )

    drow_base = _draft(variant=DROW)
    drow_choice = _replacement_choice(drow_base)
    drow = _draft(
        variant=DROW,
        selections={
            wood_choice.choice_id: wood_selection,
            drow_choice.choice_id: BuilderChoiceSelection(
                choice_id=drow_choice.choice_id,
                source_ref=drow_choice.source_ref,
                selected_option_ids=("drow-magic",),
            ),
        },
    )

    _registry, effective, summary = _summary(drow)
    active_replacement = next(
        choice
        for choice in effective
        if choice.option_source == RACE_VARIANT_REPLACEMENT_OPTION_SOURCE
    )

    assert active_replacement.choice_id == drow_choice.choice_id
    assert wood_choice.choice_id != drow_choice.choice_id
    assert active_replacement.choice_id == _replacement_choice(_draft(variant=DROW)).choice_id
    assert "scag:feature:half-elf-drow-magic" in {
        grant.reference_id for grant in summary.grants
    }
    assert "scag:feature:half-elf-fleet-of-foot" not in {
        grant.reference_id for grant in summary.grants
    }


def test_moon_sun_cantrip_uses_runtime_wizard_cantrip_pool_and_intelligence() -> None:
    registry = load_default_content_registry()
    first = _select_variant_option(MOON_SUN, "wizard-cantrip")
    choices = build_race_variant_choices(first, registry)
    spell_choice = next(
        choice for choice in choices if choice.option_source == RACE_VARIANT_SPELL_OPTION_SOURCE
    )

    assert spell_choice.choose_count == 1
    assert spell_choice.options
    for option in spell_choice.options:
        assert option.reference_id is not None
        spell = registry.get(option.reference_id)
        assert spell.data["level"] == 0
        assert spell_is_on_class_list(spell.key, WIZARD, registry)

    selected_spell = spell_choice.options[0].option_id
    selections = dict(first.draft_payload.choice_selections)
    selections[spell_choice.choice_id] = BuilderChoiceSelection(
        choice_id=spell_choice.choice_id,
        source_ref=spell_choice.source_ref,
        selected_option_ids=(selected_spell,),
    )
    complete = _draft(variant=MOON_SUN, selections=selections)
    active = build_race_variant_choices(complete, registry)
    compiled = compile_race_variant(complete, registry, active)

    assert len(compiled.spell_access_entries) == 1
    entry = compiled.spell_access_entries[0]
    assert entry.spell_key == selected_spell
    assert entry.source_key == "scag:feature:half-elf-moon-sun-cantrip"
    assert entry.casting_ability == "intelligence"
    assert entry.access_type == "granted"


@pytest.mark.parametrize(
    ("variant", "option", "walking", "swim"),
    [
        (WOOD, "fleet-of-foot", 35, None),
        (AQUATIC, "swimming-speed", 30, 30),
    ],
)
def test_variant_movement_compiles_to_explicit_modes(
    variant: str,
    option: str,
    walking: int,
    swim: int | None,
) -> None:
    registry = load_default_content_registry()
    draft = _select_variant_option(variant, option)
    choices = build_race_variant_choices(draft, registry)
    compiled = compile_race_variant(draft, registry, choices)

    assert compiled.walking_speed == walking
    assert compiled.swim_speed == swim


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (1, {"srd5.1:spell:dancing-lights"}),
        (2, {"srd5.1:spell:dancing-lights"}),
        (3, {"srd5.1:spell:dancing-lights", "srd5.1:spell:faerie-fire"}),
        (4, {"srd5.1:spell:dancing-lights", "srd5.1:spell:faerie-fire"}),
        (
            5,
            {
                "srd5.1:spell:dancing-lights",
                "srd5.1:spell:faerie-fire",
                "srd5.1:spell:darkness",
            },
        ),
    ],
)
def test_drow_magic_uses_character_level_thresholds_and_separate_rest_metadata(
    level: int,
    expected: set[str],
) -> None:
    draft = _select_variant_option(DROW, "drow-magic", level=level)
    registry, effective, summary = _summary(draft)
    origin = compile_origin(
        grants=summary.grants,
        target_level=level,
        registry=registry,
    )

    by_spell = {entry.spell_key: entry for entry in origin.spell_access_entries}
    assert set(by_spell) == expected
    assert all(entry.casting_ability == "charisma" for entry in by_spell.values())
    assert all(entry.access_type == "granted" for entry in by_spell.values())

    for spell_key in {"srd5.1:spell:faerie-fire", "srd5.1:spell:darkness"}.intersection(expected):
        assert by_spell[spell_key].uses_per_rest == 1
        assert by_spell[spell_key].rest_type == "long_rest"

    dancing_lights = by_spell["srd5.1:spell:dancing-lights"]
    assert dancing_lights.uses_per_rest is None
    assert dancing_lights.rest_type is None


def test_race_variant_build_reference_round_trip_and_mismatch_validation() -> None:
    registry = load_default_content_registry()
    scores = AbilityScores(
        strength=15,
        dexterity=14,
        constitution=13,
        intelligence=12,
        wisdom=10,
        charisma=10,
    )
    build = CharacterBuild(
        content_sources=("scag", "srd5.1"),
        race_ref=HALF_ELF,
        race_variant_ref=WOOD,
        character_level=1,
        class_progression=("srd5.1:class:fighter",),
        ability_scores=scores,
        walking_speed=35,
        hp_progression=(10,),
    )

    validate_build_references(build, registry)
    reloaded = CharacterBuild.model_validate(build.model_dump(mode="python"))
    assert reloaded.race_ref == HALF_ELF
    assert reloaded.race_variant_ref == WOOD
    assert reloaded.walking_speed == 35

    old_payload = build.model_dump(mode="python")
    old_payload.pop("race_variant_ref", None)
    old_payload.pop("walking_speed", None)
    old_payload.pop("swim_speed", None)
    old_payload.pop("climb_speed", None)
    old_payload.pop("fly_speed", None)
    legacy = CharacterBuild.model_validate(old_payload)
    assert legacy.race_variant_ref is None
    assert legacy.walking_speed is None

    mismatch = build.model_copy(update={"race_ref": "srd5.1:race:human"})
    with pytest.raises(CharacterValidationError, match="does not belong"):
        validate_build_references(mismatch, registry)


def test_wrong_kind_variant_selection_is_rejected_and_variant_human_stays_plain_race() -> None:
    registry = load_default_content_registry()
    wrong_kind = _draft(variant="srd5.1:race:human")
    issues = validate_race_variant(wrong_kind, registry)
    assert {issue.code for issue in issues} == {"wrong_reference_kind"}

    variant_human = CharacterBuild(
        content_sources=("phb2014", "srd5.1"),
        race_ref="phb2014:race:variant-human",
        character_level=1,
        class_progression=("srd5.1:class:fighter",),
        ability_scores=AbilityScores(
            strength=15,
            dexterity=14,
            constitution=13,
            intelligence=12,
            wisdom=10,
            charisma=8,
        ),
        hp_progression=(10,),
    )
    assert variant_human.race_variant_ref is None
