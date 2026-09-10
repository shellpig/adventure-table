from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.rooms.rolls import (
    FormalRollInput,
    FormalRollSource,
    RequestCheckInput,
    RollEngine,
    RollInputInvalidError,
    RollModifierMode,
    RollRequestType,
    RollVisibility,
)


class FixedRng:
    def __init__(self, *values: int) -> None:
        self.values = iter(values)

    def randint(self, low: int, high: int) -> int:
        value = next(self.values)
        assert low <= value <= high
        return value


def test_server_d20_records_raw_kept_modifier_and_total() -> None:
    engine = RollEngine(rng=FixedRng(7))  # type: ignore[arg-type]
    result = engine.d20(
        mode=RollModifierMode.NORMAL,
        base_modifier=5,
        flat_adjustment=-2,
    )
    assert result.raw_dice == (7,)
    assert result.kept_dice == (7,)
    assert result.base_modifier == 5
    assert result.flat_adjustment == -2
    assert result.total == 10
    assert result.formula == "1d20+3"


def test_advantage_and_disadvantage_keep_the_correct_raw_die() -> None:
    advantage = RollEngine(rng=FixedRng(3, 18)).d20(  # type: ignore[arg-type]
        mode=RollModifierMode.ADVANTAGE,
        base_modifier=0,
        flat_adjustment=0,
    )
    disadvantage = RollEngine(rng=FixedRng(3, 18)).d20(  # type: ignore[arg-type]
        mode=RollModifierMode.DISADVANTAGE,
        base_modifier=0,
        flat_adjustment=0,
    )
    assert advantage.raw_dice == (3, 18)
    assert advantage.kept_dice == (18,)
    assert advantage.total == 18
    assert disadvantage.raw_dice == (3, 18)
    assert disadvantage.kept_dice == (3,)
    assert disadvantage.total == 3


def test_physical_roll_requires_raw_dice_shape_not_final_total() -> None:
    engine = RollEngine()
    result = engine.d20(
        mode=RollModifierMode.ADVANTAGE,
        base_modifier=4,
        flat_adjustment=1,
        physical_raw_dice=(11, 16),
    )
    assert result.raw_dice == (11, 16)
    assert result.kept_dice == (16,)
    assert result.total == 21

    with pytest.raises(RollInputInvalidError):
        engine.d20(
            mode=RollModifierMode.ADVANTAGE,
            base_modifier=4,
            flat_adjustment=1,
            physical_raw_dice=(17,),
        )
    with pytest.raises(RollInputInvalidError):
        engine.d20(
            mode=RollModifierMode.NORMAL,
            base_modifier=0,
            flat_adjustment=0,
            physical_raw_dice=(25,),
        )


def test_quick_dice_has_no_formal_request_semantics() -> None:
    result = RollEngine(rng=FixedRng(4, 6)).quick(  # type: ignore[arg-type]
        dice_count=2,
        die_sides=6,
        flat_adjustment=3,
    )
    assert result.formula == "2d6+3"
    assert result.raw_dice == (4, 6)
    assert result.kept_dice == (4, 6)
    assert result.total == 13


def test_request_check_validates_target_and_rule_reference_shape() -> None:
    first = uuid4()
    second = uuid4()
    request = RequestCheckInput(
        target_seat_ids=(first, second),
        request_type=RollRequestType.SKILL,
        skill_ref="perception",
        dc=15,
        modifier_mode=RollModifierMode.ADVANTAGE,
        flat_adjustment=2,
        visibility=RollVisibility.ROLLER_AND_DM,
    )
    assert request.target_seat_ids == (first, second)

    with pytest.raises(ValueError):
        RequestCheckInput(
            target_seat_ids=(first, first),
            request_type=RollRequestType.OTHER,
        )
    with pytest.raises(ValueError):
        RequestCheckInput(
            target_seat_ids=(first,),
            request_type=RollRequestType.SKILL,
        )
    with pytest.raises(ValueError):
        RequestCheckInput(
            target_seat_ids=(first,),
            request_type=RollRequestType.SAVING_THROW,
        )


def test_formal_input_never_accepts_client_dice_for_server_rng() -> None:
    with pytest.raises(ValueError):
        FormalRollInput(
            roll_request_id=uuid4(),
            source=FormalRollSource.SERVER,
            raw_dice=(20,),
        )
    with pytest.raises(ValueError):
        FormalRollInput(
            roll_request_id=uuid4(),
            source=FormalRollSource.PHYSICAL,
        )
