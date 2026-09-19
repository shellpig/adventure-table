from __future__ import annotations

import pytest

from app.domain.combat.condition_modifiers import (
    AttackModifierDecision,
    SaveModifierDecision,
    attack_modifiers,
    conditions_from_refs,
    save_modifiers,
)
from app.domain.combat.effect_resolver import Condition
from app.domain.combat.resolution import AttackKind, RollMode
from app.domain.rooms.rolls import RollModifierMode


def test_conditions_from_refs_accepts_both_spellings_dedupes_and_rejects_unknown() -> None:
    conditions = conditions_from_refs(["srd5.1:condition:prone", "prone", "blinded"])
    assert conditions == frozenset({Condition.PRONE, Condition.BLINDED})

    with pytest.raises(ValueError, match="unsupported 2014 combat condition: srd5.1:condition:dazed"):
        conditions_from_refs(["srd5.1:condition:dazed"])

    with pytest.raises(ValueError, match="unsupported 2014 combat condition: dazed"):
        conditions_from_refs(["dazed"])


@pytest.mark.parametrize(
    ("attack_kind", "attacker_conditions", "target_conditions", "expected_mode", "expected_adv", "expected_dis"),
    [
        (AttackKind.MELEE, (), ("srd5.1:condition:prone",), RollMode.ADVANTAGE, ("target:prone",), ()),
        (AttackKind.RANGED, (), ("srd5.1:condition:prone",), RollMode.DISADVANTAGE, (), ("target:prone",)),
        (AttackKind.MELEE, ("srd5.1:condition:prone",), (), RollMode.DISADVANTAGE, (), ("attacker:prone",)),
        (AttackKind.RANGED, ("srd5.1:condition:prone",), (), RollMode.DISADVANTAGE, (), ("attacker:prone",)),
    ],
)
def test_prone_target_and_attacker_attack_modifiers(
    attack_kind: AttackKind,
    attacker_conditions: tuple[str, ...],
    target_conditions: tuple[str, ...],
    expected_mode: RollMode,
    expected_adv: tuple[str, ...],
    expected_dis: tuple[str, ...],
) -> None:
    decision = attack_modifiers(
        chosen=RollMode.NORMAL,
        attack_kind=attack_kind,
        attacker_conditions=attacker_conditions,
        target_conditions=target_conditions,
    )
    assert decision.mode is expected_mode
    assert decision.advantage_sources == expected_adv
    assert decision.disadvantage_sources == expected_dis
    assert not decision.critical_on_hit
    assert decision.unresolved == ()


@pytest.mark.parametrize(
    ("chosen", "attacker_conditions", "target_conditions", "expected_adv", "expected_dis"),
    [
        (
            RollMode.NORMAL,
            ("prone",),
            ("blinded",),
            ("target:blinded",),
            ("attacker:prone",),
        ),
        (
            RollMode.ADVANTAGE,
            ("prone",),
            ("blinded",),
            ("chosen:advantage", "target:blinded"),
            ("attacker:prone",),
        ),
        (
            RollMode.DISADVANTAGE,
            ("invisible",),
            ("restrained",),
            ("attacker:invisible", "target:restrained"),
            ("chosen:disadvantage",),
        ),
    ],
)
def test_advantage_and_disadvantage_cancel_to_normal_regardless_of_source_counts(
    chosen: RollMode,
    attacker_conditions: tuple[str, ...],
    target_conditions: tuple[str, ...],
    expected_adv: tuple[str, ...],
    expected_dis: tuple[str, ...],
) -> None:
    decision = attack_modifiers(
        chosen=chosen,
        attack_kind=AttackKind.MELEE,
        attacker_conditions=attacker_conditions,
        target_conditions=target_conditions,
    )
    assert decision.mode is RollMode.NORMAL
    assert decision.advantage_sources == expected_adv
    assert decision.disadvantage_sources == expected_dis


@pytest.mark.parametrize("condition_slug", ["paralyzed", "unconscious"])
@pytest.mark.parametrize(
    ("attack_kind", "expected_critical"),
    [
        (AttackKind.MELEE, True),
        (AttackKind.RANGED, False),
    ],
)
def test_paralyzed_and_unconscious_critical_on_hit_only_for_melee(
    condition_slug: str,
    attack_kind: AttackKind,
    expected_critical: bool,
) -> None:
    decision = attack_modifiers(
        chosen=RollMode.NORMAL,
        attack_kind=attack_kind,
        attacker_conditions=(),
        target_conditions=(f"srd5.1:condition:{condition_slug}",),
    )
    assert decision.mode is RollMode.ADVANTAGE
    assert decision.critical_on_hit is expected_critical
    assert decision.advantage_sources == (f"target:{condition_slug}",)
    assert decision.disadvantage_sources == ()


def test_frightened_attacker_yields_unresolved_source_visibility_and_does_not_affect_mode() -> None:
    decision = attack_modifiers(
        chosen=RollMode.NORMAL,
        attack_kind=AttackKind.MELEE,
        attacker_conditions=("srd5.1:condition:frightened",),
        target_conditions=(),
    )
    assert decision.mode is RollMode.NORMAL
    assert decision.advantage_sources == ()
    assert decision.disadvantage_sources == ()
    assert decision.unresolved == ("attacker:frightened:source_visibility",)

    advantage_decision = attack_modifiers(
        chosen=RollMode.ADVANTAGE,
        attack_kind=AttackKind.MELEE,
        attacker_conditions=("frightened",),
        target_conditions=(),
    )
    assert advantage_decision.mode is RollMode.ADVANTAGE
    assert advantage_decision.unresolved == ("attacker:frightened:source_visibility",)


@pytest.mark.parametrize(
    ("level", "expected_mode", "expected_dis"),
    [
        (0, RollMode.NORMAL, ()),
        (1, RollMode.NORMAL, ()),
        (2, RollMode.NORMAL, ()),
        (3, RollMode.DISADVANTAGE, ("attacker:exhaustion:3",)),
        (4, RollMode.DISADVANTAGE, ("attacker:exhaustion:4",)),
        (5, RollMode.DISADVANTAGE, ("attacker:exhaustion:5",)),
        (6, RollMode.DISADVANTAGE, ("attacker:exhaustion:6",)),
    ],
)
def test_attacker_exhaustion_affects_attacks_at_level_three_and_above(
    level: int,
    expected_mode: RollMode,
    expected_dis: tuple[str, ...],
) -> None:
    decision = attack_modifiers(
        chosen=RollMode.NORMAL,
        attack_kind=AttackKind.MELEE,
        attacker_conditions=(),
        target_conditions=(),
        attacker_exhaustion=level,
    )
    assert decision.mode is expected_mode
    assert decision.disadvantage_sources == expected_dis


def test_attacker_exhaustion_out_of_range_raises_value_error() -> None:
    with pytest.raises(ValueError, match="exhaustion level must be between 0 and 6"):
        attack_modifiers(
            chosen=RollMode.NORMAL,
            attack_kind=AttackKind.MELEE,
            attacker_conditions=(),
            target_conditions=(),
            attacker_exhaustion=7,
        )


@pytest.mark.parametrize(
    (
        "chosen",
        "ability_ref",
        "target_conditions",
        "target_exhaustion",
        "expected_mode",
        "expected_auto_fail",
        "expected_adv",
        "expected_dis",
        "expected_auto_sources",
    ),
    [
        # Paralyzed target STR / DEX auto-fails, WIS normal
        (
            RollModifierMode.NORMAL,
            "str",
            ("paralyzed",),
            0,
            RollModifierMode.NORMAL,
            True,
            (),
            (),
            ("target:paralyzed",),
        ),
        (
            RollModifierMode.NORMAL,
            "dexterity",
            ("srd5.1:condition:paralyzed",),
            0,
            RollModifierMode.NORMAL,
            True,
            (),
            (),
            ("target:paralyzed",),
        ),
        (
            RollModifierMode.NORMAL,
            "wis",
            ("paralyzed",),
            0,
            RollModifierMode.NORMAL,
            False,
            (),
            (),
            (),
        ),
        # Restrained target DEX has disadvantage, WIS normal
        (
            RollModifierMode.NORMAL,
            "dex",
            ("restrained",),
            0,
            RollModifierMode.DISADVANTAGE,
            False,
            (),
            ("target:restrained",),
            (),
        ),
        (
            RollModifierMode.NORMAL,
            "wisdom",
            ("restrained",),
            0,
            RollModifierMode.NORMAL,
            False,
            (),
            (),
            (),
        ),
        # Petrified with full ability ref auto-fails STR save
        (
            RollModifierMode.NORMAL,
            "srd5.1:ability:str",
            ("srd5.1:condition:petrified",),
            0,
            RollModifierMode.NORMAL,
            True,
            (),
            (),
            ("target:petrified",),
        ),
        # Exhaustion 3 on WIS save has disadvantage
        (
            RollModifierMode.NORMAL,
            "wis",
            (),
            3,
            RollModifierMode.DISADVANTAGE,
            False,
            (),
            ("target:exhaustion:3",),
            (),
        ),
        # Cancel rule: chosen advantage cancels restrained DEX disadvantage
        (
            RollModifierMode.ADVANTAGE,
            "dex",
            ("restrained",),
            0,
            RollModifierMode.NORMAL,
            False,
            ("chosen:advantage",),
            ("target:restrained",),
            (),
        ),
    ],
)
def test_saving_throw_conditions_and_exhaustion(
    chosen: RollModifierMode,
    ability_ref: str,
    target_conditions: tuple[str, ...],
    target_exhaustion: int,
    expected_mode: RollModifierMode,
    expected_auto_fail: bool,
    expected_adv: tuple[str, ...],
    expected_dis: tuple[str, ...],
    expected_auto_sources: tuple[str, ...],
) -> None:
    decision = save_modifiers(
        chosen=chosen,
        ability_ref=ability_ref,
        target_conditions=target_conditions,
        target_exhaustion=target_exhaustion,
    )
    assert decision.mode is expected_mode
    assert decision.auto_fail is expected_auto_fail
    assert decision.advantage_sources == expected_adv
    assert decision.disadvantage_sources == expected_dis
    assert decision.auto_fail_sources == expected_auto_sources


def test_target_exhaustion_out_of_range_raises_value_error() -> None:
    with pytest.raises(ValueError, match="exhaustion level must be between 0 and 6"):
        save_modifiers(
            chosen=RollModifierMode.NORMAL,
            ability_ref="dex",
            target_conditions=(),
            target_exhaustion=7,
        )
