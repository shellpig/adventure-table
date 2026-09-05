from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.content import load_default_content_registry
from app.content.identity import reference_to_stable_key
from app.domain.character_builder.progression import (
    compile_progression,
    progression_summary,
    subclass_selection_level,
)
from app.domain.character_builder.rules import (
    caster_level_contribution,
    load_spellcasting_rules,
    normalize_slot_contribution,
    prepared_limit,
)
from app.domain.character_builder.schemas import (
    BuilderDraft,
    BuilderDraftPayload,
    BuilderHPMethod,
    BuilderLevelChoice,
    BuilderMode,
)
from app.domain.character_builder.m01j_extension import prepare_m01j_subclasses
from app.domain.character_builder.spellcasting import (
    calculate_multiclass_spell_slots,
    compile_spellcasting,
)


ARTIFICER = "tce:class:artificer"
SPECIALISTS = {
    "tce:subclass:alchemist": {
        3: {
            "tce:feature:alchemist-tool-proficiency",
            "tce:feature:alchemist-spells",
            "tce:feature:experimental-elixir",
        },
        5: {"tce:feature:alchemical-savant"},
        9: {"tce:feature:restorative-reagents"},
        15: {"tce:feature:chemical-mastery"},
    },
    "tce:subclass:armorer": {
        3: {
            "tce:feature:tools-of-the-trade",
            "tce:feature:armorer-spells",
            "tce:feature:arcane-armor",
            "tce:feature:armor-model",
        },
        5: {"tce:feature:armorer-extra-attack"},
        9: {"tce:feature:armor-modifications"},
        15: {"tce:feature:perfected-armor"},
    },
    "tce:subclass:artillerist": {
        3: {
            "tce:feature:artillerist-tool-proficiency",
            "tce:feature:artillerist-spells",
            "tce:feature:eldritch-cannon",
        },
        5: {"tce:feature:arcane-firearm"},
        9: {"tce:feature:explosive-cannon"},
        15: {"tce:feature:fortified-position"},
    },
    "tce:subclass:battle-smith": {
        3: {
            "tce:feature:battle-smith-tool-proficiency",
            "tce:feature:battle-smith-spells",
            "tce:feature:battle-ready",
            "tce:feature:steel-defender",
        },
        5: {"tce:feature:battle-smith-extra-attack"},
        9: {"tce:feature:arcane-jolt"},
        15: {"tce:feature:improved-defender"},
    },
}


def _draft(levels: tuple[BuilderLevelChoice, ...]) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=BuilderDraftPayload(
            target_level=len(levels),
            level_choices=levels,
        ),
        created_at=now,
        updated_at=now,
    )


def _level(
    character_level: int,
    class_ref: str,
    *,
    subclass_ref: str | None = None,
) -> BuilderLevelChoice:
    hit_die = {
        ARTIFICER: 8,
        "srd5.1:class:wizard": 6,
        "srd5.1:class:paladin": 10,
        "srd5.1:class:ranger": 10,
        "srd5.1:class:warlock": 8,
        "srd5.1:class:fighter": 10,
    }.get(class_ref, 8)
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=class_ref,
        hp_method=(
            BuilderHPMethod.FIRST_LEVEL
            if character_level == 1
            else BuilderHPMethod.FIXED_AVERAGE
        ),
        hp_base_gain=(hit_die if character_level == 1 else hit_die // 2 + 1),
        subclass_ref=subclass_ref,
    )


def _artificer_levels(
    target: int,
    *,
    subclass_ref: str | None = None,
) -> tuple[BuilderLevelChoice, ...]:
    return tuple(
        _level(
            level,
            ARTIFICER,
            subclass_ref=(subclass_ref if subclass_ref is not None and level == 3 else None),
        )
        for level in range(1, target + 1)
    )


def _mixed_levels(class_refs: tuple[str, ...]) -> tuple[BuilderLevelChoice, ...]:
    return tuple(
        _level(character_level, class_ref)
        for character_level, class_ref in enumerate(class_refs, start=1)
    )


def test_tce_pack_exposes_complete_artificer_core_dataset() -> None:
    registry = load_default_content_registry()
    artificer = registry.get(ARTIFICER)

    assert "tce" in registry.enabled_pack_ids
    assert artificer.data["hit_die"] == 8
    assert [reference["index"] for reference in artificer.data["saving_throws"]] == [
        "con",
        "int",
    ]

    proficiencies = {reference["index"] for reference in artificer.data["proficiencies"]}
    assert {
        "light-armor",
        "medium-armor",
        "shields",
        "simple-weapons",
        "hand-crossbows",
        "crossbows-heavy",
        "thieves-tools",
        "tinkers-tools",
    } <= proficiencies
    assert not any("firearm" in value for value in proficiencies)

    proficiency_choices = artificer.data["proficiency_choices"]
    assert [choice["choose"] for choice in proficiency_choices] == [2, 1]
    assert {
        option["item"]["index"]
        for option in proficiency_choices[0]["from"]["options"]
    } == {
        "skill-arcana",
        "skill-history",
        "skill-insight",
        "skill-medicine",
        "skill-nature",
        "skill-perception",
        "skill-sleight-of-hand",
    }

    multiclass = artificer.data["multi_classing"]
    assert multiclass["prerequisites"] == [
        {
            "ability_score": {
                "index": "int",
                "name": "INT",
                "url": "/api/2014/ability-scores/int",
            },
            "minimum_score": 13,
        }
    ]
    assert {reference["index"] for reference in multiclass["proficiencies"]} == {
        "light-armor",
        "medium-armor",
        "shields",
        "thieves-tools",
        "tinkers-tools",
    }

    assert {reference["key"] for reference in artificer.data["subclasses"]} == set(SPECIALISTS)
    assert artificer.data["spellcasting"]["ritual_casting"] is True
    assert artificer.data["spellcasting"]["focus_requirement"]["required"] is True


def test_artificer_levels_are_continuous_and_table_driven() -> None:
    registry = load_default_content_registry()
    expected_asi = {4: 1, 8: 2, 12: 3, 16: 4, 19: 5}
    last_asi = 0

    for level in range(1, 21):
        entry = registry.get(f"tce:level:artificer-{level}")
        assert entry.data["level"] == level
        assert reference_to_stable_key(entry.data["class"], kinds={"class"}) == ARTIFICER
        assert entry.data["prof_bonus"] == 2 + (level - 1) // 4

        if level in expected_asi:
            last_asi = expected_asi[level]
        assert entry.data["ability_score_bonuses"] == last_asi

        spellcasting = entry.data["spellcasting"]
        assert isinstance(spellcasting["cantrips_known"], int)
        for spell_level in range(1, 6):
            assert isinstance(spellcasting[f"spell_slots_level_{spell_level}"], int)

        class_specific = entry.data["class_specific"]
        assert isinstance(class_specific["infusions_known"], int)
        assert isinstance(class_specific["infused_items_max"], int)

        for reference in entry.data["features"]:
            feature_ref = reference_to_stable_key(reference, kinds={"feature"})
            assert feature_ref is not None
            assert registry.get_optional(feature_ref) is not None


@pytest.mark.parametrize(
    ("raw", "formula", "rounding"),
    [
        ("full", "full", "floor"),
        ("half", "half", "floor"),
        ("none", "none", "none"),
        ({"formula": "half", "rounding": "ceil"}, "half", "ceil"),
    ],
)
def test_slot_contribution_normalization(raw: object, formula: str, rounding: str) -> None:
    result = normalize_slot_contribution(raw)
    assert result.formula == formula
    assert result.rounding == rounding


@pytest.mark.parametrize(
    "raw",
    [
        "quarter",
        {"formula": "half", "rounding": "none"},
        {"formula": "none", "rounding": "floor"},
        {"formula": "full", "rounding": "ceil"},
        {"formula": "quarter", "rounding": "floor"},
    ],
)
def test_invalid_slot_contribution_config_fails_fast(raw: object) -> None:
    with pytest.raises(ValueError):
        normalize_slot_contribution(raw)


def test_default_rules_keep_legacy_classes_and_artificer_canonical_rounding() -> None:
    rules = load_spellcasting_rules()

    assert rules.classes["srd5.1:class:wizard"].slot_contribution.formula == "full"
    assert rules.classes["srd5.1:class:wizard"].slot_contribution.rounding == "floor"
    assert rules.classes["srd5.1:class:paladin"].slot_contribution.formula == "half"
    assert rules.classes["srd5.1:class:paladin"].slot_contribution.rounding == "floor"
    assert rules.classes["srd5.1:class:ranger"].slot_contribution.rounding == "floor"
    assert rules.classes["srd5.1:class:warlock"].slot_contribution.formula == "none"
    assert rules.classes["srd5.1:class:warlock"].slot_contribution.rounding == "none"

    artificer = rules.classes[ARTIFICER]
    assert artificer.slot_contribution.formula == "half"
    assert artificer.slot_contribution.rounding == "ceil"
    assert artificer.prepared_formula == "half_class_level_floor_plus_ability"
    assert artificer.prepared_minimum == 1


@pytest.mark.parametrize(
    ("class_level", "expected"),
    [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (6, 3), (7, 4), (19, 10), (20, 10)],
)
def test_artificer_caster_contribution_uses_ceil(class_level: int, expected: int) -> None:
    rule = load_spellcasting_rules().classes[ARTIFICER]
    assert caster_level_contribution(ARTIFICER, class_level, rule) == expected


@pytest.mark.parametrize(
    ("class_level", "int_modifier", "expected"),
    [
        (1, -1, 1),
        (2, -1, 1),
        (3, -1, 1),
        (3, 0, 1),
        (4, 0, 2),
        (3, 3, 4),
        (4, 3, 5),
        (19, 3, 12),
        (20, 3, 13),
    ],
)
def test_artificer_prepared_limit_uses_independent_floor(
    class_level: int,
    int_modifier: int,
    expected: int,
) -> None:
    rule = load_spellcasting_rules().classes[ARTIFICER]
    assert prepared_limit(rule, class_level, int_modifier) == expected


@pytest.mark.parametrize(
    ("classes", "expected"),
    [
        ((ARTIFICER, "srd5.1:class:wizard"), {1: 3}),
        ((ARTIFICER, ARTIFICER, ARTIFICER, "srd5.1:class:wizard", "srd5.1:class:wizard"), {1: 4, 2: 3}),
        ((ARTIFICER, ARTIFICER, ARTIFICER, "srd5.1:class:paladin", "srd5.1:class:paladin"), {1: 4, 2: 2}),
        ((ARTIFICER, ARTIFICER, ARTIFICER, "srd5.1:class:ranger", "srd5.1:class:ranger"), {1: 4, 2: 2}),
        (
            (
                ARTIFICER,
                ARTIFICER,
                ARTIFICER,
                "srd5.1:class:wizard",
                "srd5.1:class:paladin",
                "srd5.1:class:paladin",
            ),
            {1: 4, 2: 3},
        ),
    ],
)
def test_multiclass_normal_slot_matrix(classes: tuple[str, ...], expected: dict[int, int]) -> None:
    registry = load_default_content_registry()
    assert calculate_multiclass_spell_slots(_draft(_mixed_levels(classes)), registry) == expected


def test_warlock_pact_magic_does_not_join_artificer_normal_slots() -> None:
    registry = load_default_content_registry()
    draft = _draft(
        _mixed_levels(
            (
                ARTIFICER,
                ARTIFICER,
                ARTIFICER,
                "srd5.1:class:warlock",
                "srd5.1:class:warlock",
            )
        )
    )

    assert calculate_multiclass_spell_slots(draft, registry) == {1: 3}
    compilation = compile_spellcasting(
        draft,
        registry,
        effective_abilities={"intelligence": 16, "charisma": 14},
    )
    pool_types = [pool.pool_type.value for pool in compilation.resource_pools]
    assert pool_types.count("normal_multiclass_slots") == 1
    assert pool_types.count("pact_magic") == 1


def test_artificer_spell_list_uses_installed_cross_pack_spell_entries_only() -> None:
    registry = load_default_content_registry()
    artificer = registry.get(ARTIFICER)
    spell_refs = {
        reference_to_stable_key(reference, kinds={"spell"})
        for reference in artificer.data["spell_list"]
    }

    assert "srd5.1:spell:cure-wounds" in spell_refs
    assert "srd5.1:spell:magic-missile" not in spell_refs
    assert all(
        spell_ref is not None and registry.get_optional(spell_ref) is not None
        for spell_ref in spell_refs
    )
    assert registry.get_optional("tce:spell:booming-blade") is not None
    assert registry.get_optional("tce:spell:blade-of-disaster") is not None

    draft = _draft(_artificer_levels(5, subclass_ref="tce:subclass:armorer"))
    compilation = compile_spellcasting(
        draft,
        registry,
        effective_abilities={"intelligence": 16},
    )
    profile = next(profile for profile in compilation.profiles if profile.class_ref == ARTIFICER)
    available = {spell.spell_key for spell in profile.available_spells}
    assert "srd5.1:spell:cure-wounds" in available
    assert "srd5.1:spell:magic-missile" not in available
    assert "tce:spell:booming-blade" in available
    assert "tce:spell:blade-of-disaster" not in available

    # Armorer's spell records declare an access_type, so the M01-J producer owns
    # them; compile_spellcasting only grants the SRD record shape.
    runtime = prepare_m01j_subclasses(draft, registry)
    armorer_spells = {
        entry.spell_key
        for entry in runtime.base.spell_access_entries
        if entry.source_type == "subclass" and entry.source_key == "tce:subclass:armorer"
    }
    assert "srd5.1:spell:magic-missile" in armorer_spells
    assert "srd5.1:spell:mirror-image" in armorer_spells
    assert not any(
        entry.source_key == "tce:subclass:armorer"
        for entry in compilation.spell_access_entries
    )


def test_specialist_choice_is_data_driven_at_artificer_level_three() -> None:
    registry = load_default_content_registry()
    class_entry = registry.get(ARTIFICER)
    assert subclass_selection_level(class_entry, registry) == 3

    level_two = progression_summary(_draft(_artificer_levels(2)), registry)
    assert all(node.subclass_required is False for node in level_two)

    level_three = progression_summary(
        _draft(_artificer_levels(3, subclass_ref="tce:subclass:alchemist")),
        registry,
    )
    assert level_three[-1].subclass_required is True
    assert level_three[-1].subclass_ref == "tce:subclass:alchemist"


@pytest.mark.parametrize("subclass_ref", tuple(SPECIALISTS))
def test_specialist_features_carry_forward_after_sparse_level_three_selection(
    subclass_ref: str,
) -> None:
    registry = load_default_content_registry()
    draft = _draft(_artificer_levels(15, subclass_ref=subclass_ref))
    nodes = progression_summary(draft, registry)

    assert nodes[0].subclass_ref is None
    assert nodes[1].subclass_ref is None
    for class_level, expected_features in SPECIALISTS[subclass_ref].items():
        node = nodes[class_level - 1]
        assert node.subclass_ref == subclass_ref
        assert expected_features <= set(node.automatic_feature_refs)

    compiled = compile_progression(draft, registry, grants=(), choices=())
    assert {(item.class_ref, item.subclass_ref) for item in compiled.subclasses} == {
        (ARTIFICER, subclass_ref)
    }
    for expected_features in SPECIALISTS[subclass_ref].values():
        assert expected_features <= set(compiled.feature_refs)


def test_sparse_subclass_carry_forward_also_preserves_existing_srd_progression() -> None:
    registry = load_default_content_registry()
    levels = tuple(
        _level(
            character_level,
            "srd5.1:class:fighter",
            subclass_ref=("srd5.1:subclass:champion" if character_level == 3 else None),
        )
        for character_level in range(1, 11)
    )
    nodes = progression_summary(_draft(levels), registry)

    assert nodes[2].subclass_ref == "srd5.1:subclass:champion"
    assert all(
        node.subclass_ref == "srd5.1:subclass:champion"
        for node in nodes[2:]
    )
