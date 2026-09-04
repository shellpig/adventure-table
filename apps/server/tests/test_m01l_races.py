from __future__ import annotations

from app.paths import resolve_content_root

CONTENT_PACKS_ROOT = resolve_content_root()


from datetime import UTC, datetime
from pathlib import Path
from typing import get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.m01l_inventory import m01l_reference_inventory
from app.content.m01l_models import (
    NaturalArmorData,
    RacialSpellAccessData,
    RuntimeExecution,
)
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
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderGrantSummary,
    BuilderLevelChoice,
    BuilderMode,
    BuilderReferenceSelection,
)
from app.domain.character_builder.m01i_compiler import (
    compile_builder_draft as composed_compile,
)
from app.domain.rules.armor_class import calculate_armor_class
from app.domain.rules.feature_resources import initial_feature_resource_state, spell_access_resource_key

import m01k_support as S


REPO_ROOT = Path(__file__).resolve().parents[3]


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
        subrace_selection=(BuilderReferenceSelection(reference_id=subrace) if subrace else None),
        background_selection=BuilderReferenceSelection(reference_id="srd5.1:background:acolyte"),
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
    vgm_new = {row.key for row in inventory.rows if row.source == "vgm"}
    scag_new = {row.key for row in inventory.rows if row.source == "scag"}

    assert len(inventory.rows) == 12
    assert len(vgm_new) == 10
    assert len(scag_new) == 2
    assert {entry.key for entry in registry.list_kind("race", source="vgm")} == set(
        inventory.legacy_vgm_race_keys
    ) | vgm_new
    assert {entry.key for entry in registry.list_kind("subrace", source="scag")} == scag_new
    assert all(registry.get_optional(key) is not None for key in inventory.required_dependencies)


def test_negative_racial_ability_modifiers_apply_after_point_buy_base_scores() -> None:
    registry = load_default_content_registry()
    result = compile_builder_draft(
        _draft(
            _payload(
                "vgm:race:kobold",
                ability_generation={
                    "method": "point_buy",
                    "scores": {
                        "strength": 8,
                        "dexterity": 15,
                        "constitution": 15,
                        "intelligence": 15,
                        "wisdom": 8,
                        "charisma": 8,
                    },
                },
            )
        ),
        registry,
    )
    abilities = {row.ability: row for row in result.resolved_summary.ability_scores}
    issue_codes = {issue.code for issue in result.validation.issues}

    assert (abilities["strength"].base, abilities["strength"].permanent_bonus) == (8, -2)
    assert abilities["strength"].effective == 6
    assert "point_buy_score_out_of_range" not in issue_codes
    assert "point_buy_budget_exceeded" not in issue_codes

    orc = _draft(_payload("vgm:race:orc"))
    summary = resolve_creation_summary(orc, registry, build_foundation_choices(orc, registry))
    intelligence = next(row for row in summary.ability_scores if row.ability == "intelligence")
    assert intelligence.permanent_bonus == -2


def test_race_and_subrace_movement_compile_through_one_substrate() -> None:
    # The M01-E / M01-F movement controls (Aquatic and Wood Half-Elf, Dhampir)
    # stay in their own suites so this matrix keeps one harness:
    # test_m01e_half_elf_variants.py::test_variant_movement_compiles_to_explicit_modes
    # and test_m01f_closeout.py cover them against the same resolver.
    registry = load_default_content_registry()
    cases = (
        ("vgm:race:lizardfolk", None, (30, 30, None, None)),
        ("vgm:race:tabaxi", None, (30, None, 20, None)),
        ("vgm:race:triton", None, (30, 30, None, None)),
        ("srd5.1:race:elf", "phb2014:subrace:wood-elf", (35, None, None, None)),
    )

    for race, subrace, expected in cases:
        draft = _draft(_payload(race, subrace=subrace))
        movement = compile_race_variant(draft, registry, build_foundation_choices(draft, registry))
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
            if choice.source_ref == race_ref and choice.option_source == "content:proficiency_choices"
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

    overridden = _lizardfolk_build(numeric_overrides=(NumericOverride(key="ac", value=22),))
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
    assert all(entry.recharge_types == ("short_rest", "long_rest") for entry in origin.spell_access_entries)
    assert all(entry.rest_type is None for entry in origin.spell_access_entries)

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
    by_level = {
        level: {
            entry.spell_key
            for entry in compile_origin(
                grants=(_feature_grant(triton_feature),), target_level=level, registry=registry
            ).spell_access_entries
        }
        for level in (1, 3, 5)
    }
    assert by_level[1] == {"srd5.1:spell:fog-cloud"}
    assert by_level[3] == {"srd5.1:spell:fog-cloud", "srd5.1:spell:gust-of-wind"}
    assert by_level[5] == {
        "srd5.1:spell:fog-cloud",
        "srd5.1:spell:gust-of-wind",
        "xge:spell:wall-of-water",
    }

    feature = registry.get("vgm:feature:yuan-ti-innate-spellcasting")
    origin = compile_origin(
        grants=(_feature_grant(feature.key),), target_level=3, registry=registry
    )
    by_spell = {entry.spell_key: entry for entry in origin.spell_access_entries}
    assert by_spell["srd5.1:spell:poison-spray"].uses_per_rest is None
    assert by_spell["srd5.1:spell:animal-friendship"].recharge_types == ()
    assert by_spell["srd5.1:spell:suggestion"].uses_per_rest == 1
    assert by_spell["srd5.1:spell:suggestion"].recharge_types == ("long_rest",)

    animal_friendship = next(
        row
        for row in feature.data["racial_spell_access"]
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
    assert legacy_build_row.rest_type == "long_rest"

    phb = compile_origin(
        grants=(_feature_grant("phb2014:feature:drow-magic"),), target_level=5, registry=registry
    )
    scag = compile_origin(
        grants=(_feature_grant("scag:feature:half-elf-drow-magic"),), target_level=5, registry=registry
    )
    limited = [
        entry
        for result in (phb, scag)
        for entry in result.spell_access_entries
        if entry.uses_per_rest
    ]
    assert limited
    assert all(entry.recharge_types == ("long_rest",) for entry in limited)
    assert all(entry.rest_type is None for entry in limited)


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

    assert not catalog.policy.is_required("vgm", "race", "data.ability_bonuses.0.bonus", "zh-TW")
    assert not catalog.policy.is_required("vgm", "race", "data.movement_grants.0.speed", "zh-TW")
    assert not catalog.policy.is_required("vgm", "feature", "data.natural_armor.base", "zh-TW")
    assert catalog.policy.is_required("vgm", "feature", "data.desc.0", "zh-TW")
    assert catalog.policy.is_required("xge", "spell", "data.desc.0", "zh-TW")


def test_m01l_runtime_never_depends_on_authoring_markdown() -> None:
    authoring_markers = (
        "暫用規則資訊",
        "種族_VGM",
        "種族_SCAG",
    )
    roots = (
        REPO_ROOT / "apps" / "server" / "app",
        REPO_ROOT / "apps" / "web" / "src",
    )
    offenders: list[str] = []
    for root in roots:
        for path in (*root.rglob("*.py"), *root.rglob("*.ts"), *root.rglob("*.tsx")):
            text = path.read_text(encoding="utf-8")
            if any(marker in text for marker in authoring_markers):
                offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == [], f"runtime code references authoring markdown: {offenders}"

    # The shipped server image copies data packs explicitly and never docs/, so
    # the runtime the E2E suite exercises already has no authoring reference.
    dockerfile = (REPO_ROOT / "apps" / "server" / "Dockerfile").read_text(encoding="utf-8")
    copied = [line for line in dockerfile.splitlines() if line.startswith("COPY ")]
    assert copied
    assert not [line for line in copied if "docs" in line]

    registry = load_default_content_registry()
    for row in m01l_reference_inventory().rows:
        assert registry.get_optional(row.key) is not None


def test_natural_armor_descriptor_rejects_unsupported_shapes() -> None:
    valid = NaturalArmorData.model_validate(
        {"base": 13, "ability": "dexterity", "requires_unarmored": True}
    )
    assert (valid.base, valid.ability, valid.requires_unarmored) == (13, "dexterity", True)

    for malformed in (
        {"base": 0, "ability": "dexterity"},
        {"base": 13, "ability": "strength"},
        {"ability": "dexterity"},
        {"base": 13, "ability": "dexterity", "bonus_when_shielded": 2},
    ):
        with pytest.raises(ValidationError):
            NaturalArmorData.model_validate(malformed)


def test_racial_spell_recharge_invariants_are_enforced() -> None:
    at_will = RacialSpellAccessData.model_validate(
        {"spell": {"key": "srd5.1:spell:poison-spray", "name": "Poison Spray"}}
    )
    assert (at_will.uses_per_rest, at_will.recharge_types) == (None, [])

    multi_rest = RacialSpellAccessData.model_validate(
        {
            "spell": {"key": "srd5.1:spell:detect-magic", "name": "Detect Magic"},
            "uses_per_rest": 1,
            "recharge_types": ["short_rest", "long_rest"],
        }
    )
    assert multi_rest.recharge_types == ["short_rest", "long_rest"]

    legacy = RacialSpellAccessData.model_validate(
        {
            "spell": {"key": "srd5.1:spell:darkness", "name": "Darkness"},
            "uses_per_rest": 1,
            "rest_type": "long_rest",
        }
    )
    assert legacy.recharge_types == ["long_rest"]

    spell = {"key": "srd5.1:spell:darkness", "name": "Darkness"}
    for malformed in (
        {"spell": spell, "recharge_types": ["long_rest"]},
        {"spell": spell, "uses_per_rest": 1},
        {"spell": spell, "uses_per_rest": 1, "recharge_types": ["long_rest", "long_rest"]},
        {"spell": spell, "uses_per_rest": 1, "recharge_types": ["short_rest"], "rest_type": "long_rest"},
        {"spell": spell, "uses_per_rest": 1, "recharge_types": ["daily"]},
        {"spell": spell, "min_character_level": 0},
        {"spell": spell, "uses_spell_slot": True},
    ):
        with pytest.raises(ValidationError):
            RacialSpellAccessData.model_validate(malformed)


def test_m01l_race_features_declare_a_runtime_execution_classification() -> None:
    registry = load_default_content_registry()
    feature_refs: set[str] = set()
    for row in m01l_reference_inventory().rows:
        entry = registry.get(row.key)
        for feature in entry.data.get("features", ()):
            feature_refs.add(feature["key"])
    assert feature_refs

    automatic_payload_keys = ("natural_armor", "racial_spell_access")
    for feature_ref in sorted(feature_refs):
        data = registry.get(feature_ref).data
        classification = data.get("runtime_execution")
        assert classification in get_args(RuntimeExecution), (
            f"{feature_ref} has no M01-L runtime execution classification: {classification!r}"
        )
        if any(data.get(key) for key in automatic_payload_keys):
            assert classification == "automatic_static", (
                f"{feature_ref} is applied by the server but classified {classification!r}"
            )


def test_m01l_race_skill_choices_reject_wrong_count_and_forged_options() -> None:
    registry = load_default_content_registry()
    payload = _payload("vgm:race:kenku")
    baseline = compile_builder_draft(_draft(payload), registry)
    choice = next(
        item
        for item in baseline.choices
        if item.source_ref == "vgm:race:kenku"
        and item.option_source == "content:proficiency_choices"
    )

    def _codes(selected: tuple[str, ...]) -> set[str]:
        mutated = payload.model_copy(
            update={
                "choice_selections": {
                    choice.choice_id: BuilderChoiceSelection(
                        choice_id=choice.choice_id,
                        source_ref=choice.source_ref,
                        selected_option_ids=selected,
                    )
                }
            }
        )
        result = compile_builder_draft(_draft(mutated), registry)
        return {
            issue.code
            for issue in result.validation.issues
            if choice.choice_id in (issue.path or "") or choice.choice_id in issue.related_refs
        }

    assert "invalid_choice_count" in _codes(("srd5.1:proficiency:skill-stealth",))
    assert "invalid_choice_option" in _codes(
        ("srd5.1:proficiency:skill-stealth", "srd5.1:proficiency:skill-arcana")
    )
    assert "invalid_choice_count" in _codes(
        (
            "srd5.1:proficiency:skill-stealth",
            "srd5.1:proficiency:skill-deception",
            "srd5.1:proficiency:skill-acrobatics",
        )
    )

    accepted = _codes(
        ("srd5.1:proficiency:skill-stealth", "srd5.1:proficiency:skill-deception")
    )
    assert "invalid_choice_count" not in accepted
    assert "invalid_choice_option" not in accepted


def _triton_payload(level: int) -> BuilderDraftPayload:
    payload = _payload("vgm:race:triton", level=level)
    return payload.model_copy(
        update={
            "level_choices": tuple(
                BuilderLevelChoice(
                    character_level=index + 1,
                    class_ref="srd5.1:class:fighter",
                    hp_method="first_level" if index == 0 else "fixed_average",
                    hp_base_gain=10 if index == 0 else 6,
                    subclass_ref="srd5.1:subclass:champion" if index == 2 else None,
                )
                for index in range(level)
            )
        }
    )


def _racial_spell_view(build: CharacterBuild) -> set[tuple[str, int | None, tuple[str, ...]]]:
    return {
        (entry.spell_key, entry.uses_per_rest, entry.recharge_types)
        for entry in build.spell_access_entries
        if entry.source_type == "race"
    }


def _versioned_draft(payload: BuilderDraftPayload, mode: BuilderMode) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=mode,
        character_id=uuid4(),
        base_version_id=uuid4(),
        revision=1,
        draft_payload=payload,
        created_at=now,
        updated_at=now,
    )


def test_triton_direct_create_matches_sequential_level_up_and_build_edit() -> None:
    # Compiles through the composed service entry point, so the M01-L origin
    # resolver is exercised the same way Create, Level Up and Build Edit reach it.
    registry = S.registry()
    level_five = S.auto_fill(_triton_payload(5), registry, skip_sources=set())
    level_three = S.auto_fill(_triton_payload(3), registry, skip_sources=set())

    direct = composed_compile(S.draft(level_five), registry)
    assert direct.build_candidate is not None
    assert _racial_spell_view(direct.build_candidate) == {
        ("srd5.1:spell:fog-cloud", 1, ("long_rest",)),
        ("srd5.1:spell:gust-of-wind", 1, ("long_rest",)),
        ("xge:spell:wall-of-water", 1, ("long_rest",)),
    }

    base = composed_compile(S.draft(level_three), registry)
    assert base.build_candidate is not None
    assert _racial_spell_view(base.build_candidate) == {
        ("srd5.1:spell:fog-cloud", 1, ("long_rest",)),
        ("srd5.1:spell:gust-of-wind", 1, ("long_rest",)),
    }

    stepped = composed_compile(
        _versioned_draft(level_five, BuilderMode.LEVEL_UP),
        registry,
        base_build=base.build_candidate,
    )
    assert stepped.build_candidate is not None
    assert _racial_spell_view(stepped.build_candidate) == _racial_spell_view(direct.build_candidate)

    edited = composed_compile(
        _versioned_draft(level_five, BuilderMode.BUILD_EDIT),
        registry,
        base_build=direct.build_candidate,
    )
    assert edited.build_candidate is not None
    assert _racial_spell_view(edited.build_candidate) == _racial_spell_view(direct.build_candidate)
    assert (
        edited.build_candidate.swim_speed,
        edited.build_candidate.walking_speed,
    ) == (30, 30)
