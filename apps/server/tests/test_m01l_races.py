from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.m01l_inventory import m01l_reference_inventory
from app.content.registry import CONTENT_PACKS_ROOT
from app.domain.character.schemas import (
    AbilityScores,
    CharacterBuild,
    CharacterState,
    InventoryEntry,
    NumericOverride,
    SpellAccessEntry,
)
from app.domain.character_builder.basics import resolve_creation_summary
from app.domain.character_builder.choices import build_foundation_choices
from app.domain.character_builder.compiler import compile_builder_draft
from app.domain.character_builder.origin import compile_origin
from app.domain.character_builder.race_variants import compile_race_variant
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderGrantSummary,
    BuilderMode,
    BuilderReferenceSelection,
)
from app.domain.rules.armor_class import calculate_armor_class
from app.domain.rules.feature_resources import (
    initial_feature_resource_state,
    spell_access_resource_key,
)


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
    race: str,
    *,
    subrace: str | None = None,
    level: int = 1,
    ability_generation: dict[str, object] | None = None,
) -> BuilderDraftPayload:
    return BuilderDraftPayload(
        basic=BuilderBasicInput(name="M01-L Hero"),
        target_level=level,
        race_selection=BuilderReferenceSelection(reference_id=race),
        subrace_selection=(
            BuilderReferenceSelection(reference_id=subrace) if subrace else None
        ),
        background_selection=BuilderReferenceSelection(
            reference_id="srd5.1:background:acolyte"
        ),
        ability_generation=ability_generation
        or {
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


def _feature_grant(feature_ref: str) -> BuilderGrantSummary:
    return BuilderGrantSummary(
        label=feature_ref,
        kind="feature",
        source_ref=feature_ref,
        reference_id=feature_ref,
    )


def _lizardfolk_build(*, numeric_overrides: tuple[NumericOverride, ...] = ()) -> CharacterBuild:
    return CharacterBuild(
        race_ref="vgm:race:lizardfolk",
        character_level=1,
        class_progression=("srd5.1:class:fighter",),
        ability_scores=AbilityScores(
            strength=12,
            dexterity=14,
            constitution=14,
            intelligence=10,
            wisdom=12,
            charisma=8,
        ),
        feature_refs=("vgm:feature:lizardfolk-natural-armor",),
        hp_progression=(10,),
        numeric_overrides=numeric_overrides,
    )


def test_m01l_exact_inventory_is_10_vgm_races_plus_2_scag_subraces() -> None:
    registry = load_default_content_registry()
    inventory = m01l_reference_inventory()

    assert len(inventory.rows) == 12
    assert sum(row.source == "vgm" and row.kind == "race" for row in inventory.rows) == 10
    assert sum(row.source == "scag" and row.kind == "subrace" for row in inventory.rows) == 2
    assert {entry.key for entry in registry.list_kind("race", source="vgm")} == {
        *inventory.legacy_vgm_race_keys,
        *(row.key for row in inventory.rows if row.source == "vgm"),
    }
    assert {entry.key for entry in registry.list_kind("subrace", source="scag")} == {
        row.key for row in inventory.rows if row.source == "scag"
    }
    assert all(registry.get_optional(key) is not None for key in inventory.required_dependencies)


def test_negative_racial_ability_modifiers_apply_after_point_buy_base_scores() -> None:
    registry = load_default_content_registry()
    point_buy = {
        "method": "point_buy",
        "scores": {
            "strength": 8,
            "dexterity": 15,
            "constitution": 15,
            "intelligence": 15,
            "wisdom": 8,
            "charisma": 8,
        },
    }
    result = compile_builder_draft(
        _draft(_payload("vgm:race:kobold", ability_generation=point_buy)),
        registry,
    )
    abilities = {
        row.ability: row for row in result.resolved_summary.ability_scores
    }

    assert abilities["strength"].base == 8
    assert abilities["strength"].permanent_bonus == -2
    assert abilities["strength"].effective == 6
    assert "point_buy_score_out_of_range" not in {
        issue.code for issue in result.validation.issues
    }
    assert "point_buy_budget_exceeded" not in {
        issue.code for issue in result.validation.issues
    }

    orc = _draft(_payload("vgm:race:orc"))
    choices = build_foundation_choices(orc, registry)
    summary = resolve_creation_summary(orc, registry, choices)
    intelligence = next(
        row for row in summary.ability_scores if row.ability == "intelligence"
    )
    assert intelligence.permanent_bonus == -2


def test_race_and_subrace_movement_compile_through_one_substrate() -> None:
    registry = load_default_content_registry()
    cases = (
        ("vgm:race:lizardfolk", None, (30, 30, None, None)),
        ("vgm:race:tabaxi", None, (30, None, 20, None)),
        ("vgm:race:triton", None, (30, 30, None, None)),
        (
            "srd5.1:race:elf",
            "phb2014:subrace:wood-elf",
            (35, None, None, None),
        ),
    )

    for race, subrace, expected in cases:
        draft = _draft(_payload(race, subrace=subrace))
        movement = compile_race_variant(
            draft,
            registry,
            build_foundation_choices(draft, registry),
        )
        assert (
            movement.walking_speed,
            movement.swim_speed,
            movement.climb_speed,
            movement.fly_speed,
        ) == expected


def test_kenku_and_lizardfolk_skill_choices_require_exactly_two() -> None:
    registry = load_default_content_registry()
    expected = {
        "vgm:race:kenku": {
            "srd5.1:proficiency:skill-acrobatics",
            "srd5.1:proficiency:skill-deception",
            "srd5.1:proficiency:skill-stealth",
            "srd5.1:proficiency:skill-sleight-of-hand",
        },
        "vgm:race:lizardfolk": {
            "srd5.1:proficiency:skill-animal-handling",
            "srd5.1:proficiency:skill-nature",
            "srd5.1:proficiency:skill-perception",
            "srd5.1:proficiency:skill-stealth",
            "srd5.1:proficiency:skill-survival",
        },
    }

    for race_ref, option_refs in expected.items():
        draft = _draft(_payload(race_ref))
        choice = next(
            choice
            for choice in build_foundation_choices(draft, registry)
            if choice.source_ref == race_ref
            and choice.option_source == "content:proficiency_choices"
        )
        assert choice.choose_count == 2
        assert {option.reference_id for option in choice.options} == option_refs


def test_lizardfolk_natural_armor_is_generic_candidate_with_shield_and_override() -> None:
    registry = load_default_content_registry()
    build = _lizardfolk_build()

    assert calculate_armor_class(build, CharacterState(current_hp=10), registry) == 15

    shield_state = CharacterState(
        current_hp=10,
        inventory_state=[
            InventoryEntry(
                entry_id="shield",
                item_ref="srd5.1:equipment:shield",
                quantity=1,
                equipped=True,
            )
        ],
    )
    assert calculate_armor_class(build, shield_state, registry) == 17

    armored_state = CharacterState(
        current_hp=10,
        inventory_state=[
            InventoryEntry(
                entry_id="chain-mail",
                item_ref="srd5.1:equipment:chain-mail",
                quantity=1,
                equipped=True,
            )
        ],
    )
    assert calculate_armor_class(build, armored_state, registry) == 16

    overridden = _lizardfolk_build(
        numeric_overrides=(NumericOverride(key="ac", value=22),)
    )
    assert calculate_armor_class(overridden, shield_state, registry) == 22


def test_firbolg_multi_rest_spell_access_is_lossless_and_resource_backed() -> None:
    registry = load_default_content_registry()
    origin = compile_origin(
        grants=(_feature_grant("vgm:feature:firbolg-magic"),),
        target_level=1,
        registry=registry,
    )

    assert {entry.spell_key for entry in origin.spell_access_entries} == {
        "srd5.1:spell:detect-magic",
        "srd5.1:spell:disguise-self",
    }
    assert all(entry.uses_per_rest == 1 for entry in origin.spell_access_entries)
    assert all(
        entry.recharge_types == ("short_rest", "long_rest")
        for entry in origin.spell_access_entries
    )

    build = CharacterBuild(
        race_ref="vgm:race:firbolg",
        character_level=1,
        class_progression=("srd5.1:class:fighter",),
        ability_scores=AbilityScores(
            strength=12,
            dexterity=10,
            constitution=12,
            intelligence=10,
            wisdom=16,
            charisma=8,
        ),
        feature_refs=("vgm:feature:firbolg-magic",),
        spell_access_entries=origin.spell_access_entries,
        hp_progression=(10,),
    )
    resources = initial_feature_resource_state(build, registry)
    for entry in origin.spell_access_entries:
        counter = resources[spell_access_resource_key(entry.source_key, entry.spell_key)]
        assert (counter.used, counter.remaining) == (0, 1)


def test_triton_and_yuan_ti_racial_spell_gates_and_restrictions() -> None:
    registry = load_default_content_registry()
    triton_feature = "vgm:feature:control-air-and-water"

    level_one = compile_origin(
        grants=(_feature_grant(triton_feature),), target_level=1, registry=registry
    )
    level_three = compile_origin(
        grants=(_feature_grant(triton_feature),), target_level=3, registry=registry
    )
    level_five = compile_origin(
        grants=(_feature_grant(triton_feature),), target_level=5, registry=registry
    )
    assert {entry.spell_key for entry in level_one.spell_access_entries} == {
        "srd5.1:spell:fog-cloud"
    }
    assert {entry.spell_key for entry in level_three.spell_access_entries} == {
        "srd5.1:spell:fog-cloud",
        "srd5.1:spell:gust-of-wind",
    }
    assert {entry.spell_key for entry in level_five.spell_access_entries} == {
        "srd5.1:spell:fog-cloud",
        "srd5.1:spell:gust-of-wind",
        "xge:spell:wall-of-water",
    }
    assert all(
        entry.uses_per_rest == 1 and entry.recharge_types == ("long_rest",)
        for entry in level_five.spell_access_entries
    )

    yuan_ti_feature = registry.get("vgm:feature:innate-spellcasting")
    yuan_ti = compile_origin(
        grants=(_feature_grant(yuan_ti_feature.key),),
        target_level=3,
        registry=registry,
    )
    by_spell = {entry.spell_key: entry for entry in yuan_ti.spell_access_entries}
    assert by_spell["srd5.1:spell:poison-spray"].uses_per_rest is None
    assert by_spell["srd5.1:spell:animal-friendship"].recharge_types == ()
    assert by_spell["srd5.1:spell:suggestion"].uses_per_rest == 1
    assert by_spell["srd5.1:spell:suggestion"].recharge_types == ("long_rest",)

    animal_friendship = next(
        row
        for row in yuan_ti_feature.data["racial_spell_access"]
        if row["spell"]["key"] == "srd5.1:spell:animal-friendship"
    )
    assert animal_friendship["runtime_restrictions"] == [
        {"kind": "target_creature_type", "creature_type": "snake"}
    ]


def test_legacy_single_rest_spell_access_shapes_remain_readable() -> None:
    registry = load_default_content_registry()

    legacy_build_row = SpellAccessEntry.model_validate(
        {
            "entry_id": "legacy:test",
            "spell_key": "srd5.1:spell:darkness",
            "source_type": "race",
            "source_key": "phb2014:feature:drow-magic",
            "access_type": "granted",
            "uses_per_rest": 1,
            "rest_type": "long_rest",
        }
    )
    assert legacy_build_row.recharge_types == ("long_rest",)

    phb = compile_origin(
        grants=(_feature_grant("phb2014:feature:drow-magic"),),
        target_level=5,
        registry=registry,
    )
    scag = compile_origin(
        grants=(_feature_grant("scag:feature:half-elf-drow-magic"),),
        target_level=5,
        registry=registry,
    )
    for result in (phb, scag):
        limited = [entry for entry in result.spell_access_entries if entry.uses_per_rest]
        assert limited
        assert all(entry.recharge_types == ("long_rest",) for entry in limited)


def test_m01l_localization_scope_is_complete_and_mechanics_are_locale_neutral() -> None:
    registry = load_default_content_registry()
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)

    issues = catalog.completeness_issues(
        locales=("zh-TW", "en"),
        sources={"vgm", "scag", "xge"},
        kinds={"race", "subrace", "feature", "spell", "language"},
    )
    assert issues == (), ", ".join(
        f"{issue.key}::{issue.field_path}::{issue.locale}" for issue in issues[:20]
    )

    assert not catalog.policy.is_required(
        "vgm", "race", "data.ability_bonuses.0.bonus", "zh-TW"
    )
    assert not catalog.policy.is_required(
        "vgm", "race", "data.movement_grants.0.speed", "zh-TW"
    )
    assert not catalog.policy.is_required(
        "vgm", "feature", "data.natural_armor.base", "zh-TW"
    )
    assert catalog.policy.is_required(
        "vgm", "feature", "data.desc.0", "zh-TW"
    )
    assert catalog.policy.is_required(
        "xge", "spell", "data.desc.0", "zh-TW"
    )
