from __future__ import annotations

import pytest

from app.domain.combat.resolution import (
    DamageRollPart,
    DamageType,
    DeathSaveState,
    HitPointState,
    RollMode,
    SizeCategory,
    SpecialAttackKind,
    TargetKind,
    apply_damage,
    apply_healing,
    resolve_attack_roll,
    resolve_death_save,
    resolve_grapple_or_shove,
)


@pytest.mark.parametrize(
    ("rolls", "mode", "modifier", "ac", "hit", "critical", "selected"),
    [
        ((12,), RollMode.NORMAL, 5, 17, True, False, 12),
        ((11,), RollMode.NORMAL, 5, 17, False, False, 11),
        ((4, 17), RollMode.ADVANTAGE, 3, 18, True, False, 17),
        ((18, 4), RollMode.DISADVANTAGE, 10, 15, False, False, 4),
        ((20,), RollMode.NORMAL, -20, 99, True, True, 20),
        ((1,), RollMode.NORMAL, 99, 1, False, False, 1),
    ],
)
def test_attack_roll_table(
    rolls: tuple[int, ...],
    mode: RollMode,
    modifier: int,
    ac: int,
    hit: bool,
    critical: bool,
    selected: int,
) -> None:
    result = resolve_attack_roll(
        d20_rolls=rolls,
        modifier=modifier,
        target_ac=ac,
        mode=mode,
    )

    assert result.hit is hit
    assert result.critical is critical
    assert result.selected_d20 == selected


def test_critical_adds_dice_but_not_flat_modifier() -> None:
    state = HitPointState(current_hp=30, max_hp=30)
    outcome = apply_damage(
        state,
        (
            DamageRollPart(
                damage_type=DamageType.SLASHING,
                dice=(5,),
                critical_dice=(4,),
                flat_modifier=3,
            ),
        ),
        target_kind=TargetKind.CHARACTER,
        critical=True,
    )

    assert outcome.raw_total == 12
    assert outcome.after.current_hp == 18


def test_multi_part_damage_applies_each_damage_type_affinity() -> None:
    outcome = apply_damage(
        HitPointState(current_hp=40, max_hp=40),
        (
            DamageRollPart(damage_type=DamageType.SLASHING, dice=(5,), flat_modifier=2),
            DamageRollPart(damage_type=DamageType.FIRE, dice=(6,)),
            DamageRollPart(damage_type=DamageType.COLD, dice=(3,)),
        ),
        target_kind=TargetKind.CHARACTER,
        resistances=(DamageType.SLASHING,),
        immunities=(DamageType.FIRE,),
        vulnerabilities=(DamageType.COLD,),
    )

    assert dict(outcome.raw_by_type) == {"slashing": 7, "fire": 6, "cold": 3}
    assert dict(outcome.adjusted_by_type) == {"slashing": 3, "fire": 0, "cold": 6}
    assert outcome.adjusted_total == 9
    assert outcome.after.current_hp == 31


def test_same_type_parts_are_aggregated_before_resistance_rounding() -> None:
    outcome = apply_damage(
        HitPointState(current_hp=20, max_hp=20),
        (
            DamageRollPart(damage_type=DamageType.FIRE, dice=(1,)),
            DamageRollPart(damage_type=DamageType.FIRE, dice=(2,)),
        ),
        target_kind=TargetKind.CHARACTER,
        resistances=(DamageType.FIRE,),
    )

    assert dict(outcome.raw_by_type) == {"fire": 3}
    assert dict(outcome.adjusted_by_type) == {"fire": 1}


def test_temp_hp_absorbs_before_current_hp() -> None:
    outcome = apply_damage(
        HitPointState(current_hp=20, max_hp=20, temp_hp=5),
        (DamageRollPart(damage_type=DamageType.SLASHING, dice=(7,)),),
        target_kind=TargetKind.CHARACTER,
    )

    assert outcome.temp_hp_absorbed == 5
    assert outcome.hp_lost == 2
    assert outcome.after == HitPointState(current_hp=18, max_hp=20, temp_hp=0)


def test_character_exact_zero_starts_death_saves_and_conditions() -> None:
    outcome = apply_damage(
        HitPointState(current_hp=7, max_hp=20),
        (DamageRollPart(damage_type=DamageType.PIERCING, dice=(7,)),),
        target_kind=TargetKind.CHARACTER,
    )

    assert outcome.after.current_hp == 0
    assert outcome.dropped_to_zero is True
    assert outcome.instant_death is False
    assert outcome.apply_unconscious is True
    assert outcome.apply_prone is True
    assert outcome.death_saves == DeathSaveState()


def test_massive_damage_can_instantly_kill_character() -> None:
    outcome = apply_damage(
        HitPointState(current_hp=5, max_hp=10),
        (DamageRollPart(damage_type=DamageType.FORCE, dice=(15,)),),
        target_kind=TargetKind.CHARACTER,
    )

    assert outcome.instant_death is True
    assert outcome.death_saves == DeathSaveState(dead=True)


def test_monster_zero_hp_requires_dm_outcome_instead_of_auto_dead() -> None:
    outcome = apply_damage(
        HitPointState(current_hp=4, max_hp=12),
        (DamageRollPart(damage_type=DamageType.BLUDGEONING, dice=(4,)),),
        target_kind=TargetKind.MONSTER,
    )

    assert outcome.after.current_hp == 0
    assert outcome.monster_outcome_required is True
    assert outcome.death_saves is None


def test_damage_while_already_at_zero_adds_death_failure() -> None:
    outcome = apply_damage(
        HitPointState(current_hp=0, max_hp=20),
        (DamageRollPart(damage_type=DamageType.FIRE, dice=(2,)),),
        target_kind=TargetKind.CHARACTER,
        death_saves=DeathSaveState(successes=1, failures=1),
    )

    assert outcome.death_saves == DeathSaveState(successes=1, failures=2)


def test_healing_from_zero_resets_death_saves_removes_unconscious_but_keeps_prone() -> None:
    outcome = apply_healing(
        HitPointState(current_hp=0, max_hp=20, temp_hp=3),
        7,
        target_kind=TargetKind.CHARACTER,
        death_saves=DeathSaveState(successes=2, failures=1),
    )

    assert outcome.after == HitPointState(current_hp=7, max_hp=20, temp_hp=3)
    assert outcome.death_saves == DeathSaveState()
    assert outcome.remove_unconscious is True
    assert outcome.keep_prone is True


@pytest.mark.parametrize(
    ("d20", "initial", "hp_after", "expected"),
    [
        (10, DeathSaveState(), 0, DeathSaveState(successes=1)),
        (19, DeathSaveState(successes=1), 0, DeathSaveState(successes=2)),
        (9, DeathSaveState(), 0, DeathSaveState(failures=1)),
        (2, DeathSaveState(failures=1), 0, DeathSaveState(failures=2)),
        (1, DeathSaveState(), 0, DeathSaveState(failures=2)),
        (20, DeathSaveState(successes=2, failures=2), 1, DeathSaveState()),
        (15, DeathSaveState(successes=2, failures=1), 0, DeathSaveState(stable=True)),
        (1, DeathSaveState(failures=1), 0, DeathSaveState(dead=True)),
    ],
)
def test_death_save_branches(
    d20: int,
    initial: DeathSaveState,
    hp_after: int,
    expected: DeathSaveState,
) -> None:
    outcome = resolve_death_save(d20=d20, state=initial)

    assert outcome.hp_after == hp_after
    assert outcome.death_saves == expected


def test_grapple_requires_free_hand_size_and_reach() -> None:
    no_hand = resolve_grapple_or_shove(
        kind=SpecialAttackKind.GRAPPLE,
        attacker_size=SizeCategory.MEDIUM,
        target_size=SizeCategory.MEDIUM,
        attacker_check_total=20,
        target_check_total=5,
        attacker_has_free_hand=False,
        reach_confirmed=True,
    )
    too_large = resolve_grapple_or_shove(
        kind=SpecialAttackKind.GRAPPLE,
        attacker_size=SizeCategory.SMALL,
        target_size=SizeCategory.LARGE,
        attacker_check_total=20,
        target_check_total=5,
        reach_confirmed=True,
    )
    needs_dm = resolve_grapple_or_shove(
        kind=SpecialAttackKind.GRAPPLE,
        attacker_size=SizeCategory.MEDIUM,
        target_size=SizeCategory.MEDIUM,
        attacker_check_total=20,
        target_check_total=5,
        reach_confirmed=None,
    )

    assert no_hand.status == "invalid"
    assert no_hand.reason == "free_hand_required"
    assert too_large.status == "invalid"
    assert too_large.reason == "target_too_large"
    assert needs_dm.status == "dm_adjudication_required"


def test_grapple_opposed_check_tie_fails_attacker() -> None:
    outcome = resolve_grapple_or_shove(
        kind=SpecialAttackKind.GRAPPLE,
        attacker_size=SizeCategory.MEDIUM,
        target_size=SizeCategory.MEDIUM,
        attacker_check_total=15,
        target_check_total=15,
        reach_confirmed=True,
    )

    assert outcome.status == "failure"
    assert outcome.condition_to_apply is None


@pytest.mark.parametrize(
    ("kind", "condition", "push"),
    [
        (SpecialAttackKind.GRAPPLE, "grappled", None),
        (SpecialAttackKind.SHOVE_PRONE, "prone", None),
        (SpecialAttackKind.SHOVE_PUSH, None, 5),
    ],
)
def test_special_attack_success_outcomes(
    kind: SpecialAttackKind,
    condition: str | None,
    push: int | None,
) -> None:
    outcome = resolve_grapple_or_shove(
        kind=kind,
        attacker_size=SizeCategory.MEDIUM,
        target_size=SizeCategory.LARGE,
        attacker_check_total=17,
        target_check_total=11,
        reach_confirmed=True,
    )

    assert outcome.status == "success"
    assert outcome.condition_to_apply == condition
    assert outcome.push_distance_ft == push
