from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.content.registry import load_default_content_registry
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character.schemas import CharacterState, RoleplayProfile, SpellAccessEntry
from app.domain.character.validation import CharacterValidationError, validate_state_against_build


def test_standard_fixture_preserves_multiclass_order_and_ability_scores() -> None:
    build = build_p0_fighter_wizard_fixture()

    assert build.character_level == 10
    assert build.class_progression == (
        ("srd5.1:class:fighter",) * 5 + ("srd5.1:class:wizard",) * 5
    )
    assert build.ability_scores.model_dump() == {
        "strength": 16,
        "dexterity": 14,
        "constitution": 14,
        "intelligence": 16,
        "wisdom": 10,
        "charisma": 8,
    }
    assert build.hp_progression == (10, 6, 6, 6, 6, 4, 4, 4, 4, 4)
    assert build.roleplay_profile == RoleplayProfile()
    assert build.numeric_overrides == ()


def test_prepared_is_not_a_build_spell_access_type() -> None:
    with pytest.raises(ValidationError):
        SpellAccessEntry(
            entry_id="wizard:invalid",
            spell_key="srd5.1:spell:magic-missile",
            source_type="class",
            source_key="srd5.1:class:wizard",
            access_type="prepared",  # type: ignore[arg-type]
        )


def test_prepared_state_must_reference_prepareable_build_entry() -> None:
    registry = load_default_content_registry()
    build = build_p0_fighter_wizard_fixture()
    state = build_p0_fighter_wizard_state()
    state.prepared_spell_entry_ids = ["wizard:not-in-build"]

    with pytest.raises(CharacterValidationError, match="does not exist in build"):
        validate_state_against_build(state, build, registry)


def test_optional_roleplay_can_be_completely_empty() -> None:
    payload = build_p0_fighter_wizard_fixture().model_dump(mode="json")
    payload["roleplay_profile"] = {}

    rebuilt = type(build_p0_fighter_wizard_fixture()).model_validate(payload)

    assert rebuilt.roleplay_profile == RoleplayProfile()


def test_optional_roleplay_custom_fields_round_trip() -> None:
    profile = RoleplayProfile(custom_fields={"fishing_tale": ("A giant lobster",)})

    assert RoleplayProfile.model_validate(profile.model_dump(mode="json")) == profile


def test_character_state_round_trips_json_payload() -> None:
    state = build_p0_fighter_wizard_state()

    rebuilt = CharacterState.model_validate(state.model_dump(mode="json"))

    assert rebuilt == state
