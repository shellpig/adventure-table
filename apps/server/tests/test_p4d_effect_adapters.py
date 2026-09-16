from __future__ import annotations

import pytest

from app.domain.combat.effect_resolver import (
    ActiveEffect,
    Condition,
    Concentration,
    DurationKind,
    DurationSpec,
    EffectSpec,
    ModifierMode,
    ModifierScope,
    TypedModifier,
    active_effect_from_persistent,
    active_effect_to_persistent,
    concentration_from_state,
    concentration_to_state,
    condition_from_state,
    condition_to_state,
)


def test_condition_adapter_uses_canonical_stable_key() -> None:
    state = condition_to_state(Condition.BLINDED)

    assert state.condition_ref == "srd5.1:condition:blinded"
    assert condition_from_state(state) is Condition.BLINDED


def test_concentration_adapter_roundtrips_character_state_shape() -> None:
    current = Concentration(
        owner_ref="character:1",
        source_ref="srd5.1:spell:web",
        effect_ids=("web:1",),
    )

    persisted = concentration_to_state(current)

    assert concentration_from_state("character:1", persisted) == current


def test_persistent_effect_adapter_roundtrips_lossless_duration_and_modifier() -> None:
    effect = ActiveEffect.create(
        "bless:1",
        EffectSpec(
            effect_type="buff",
            tag="bless",
            duration=DurationSpec(DurationKind.UNTIL_SHORT_REST),
            source_ref="srd5.1:spell:bless",
            modifiers=(
                TypedModifier(
                    ModifierScope.SAVE,
                    ModifierMode.BONUS,
                    value=1,
                    target="all",
                ),
            ),
            note="test",
        ),
    )

    persisted = active_effect_to_persistent(effect)
    restored = active_effect_from_persistent(persisted, effect_type="buff")

    assert persisted.duration == "short_rest"
    assert persisted.modifiers[0].scope == "save"
    assert restored == effect


def test_round_bounded_effect_is_not_silently_degraded_in_character_state() -> None:
    effect = ActiveEffect.create(
        "web:1",
        EffectSpec(
            effect_type="condition",
            tag="restrained",
            duration=DurationSpec(DurationKind.ROUNDS, 2),
            source_ref="srd5.1:spell:web",
        ),
    )

    with pytest.raises(ValueError, match="cannot be losslessly persisted"):
        active_effect_to_persistent(effect)
