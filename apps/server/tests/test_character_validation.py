from __future__ import annotations

import pytest

from app.content.registry import load_default_content_registry
from app.domain.character.fixture import (
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character.schemas import CharacterBuild, SpellAccessEntry
from app.domain.character.validation import CharacterValidationError, validate_state_against_build


@pytest.mark.parametrize("access_type", ["known", "always_prepared", "granted"])
def test_daily_prepared_state_rejects_non_spellbook_access(access_type: str) -> None:
    registry = load_default_content_registry()
    build = build_p0_fighter_wizard_fixture()
    payload = build.model_dump(mode="json")
    payload["spell_access_entries"].append(
        SpellAccessEntry(
            entry_id=f"wizard:not-daily-{access_type}",
            spell_key="srd5.1:spell:light",
            source_type="class",
            source_key="srd5.1:class:wizard",
            access_type=access_type,  # type: ignore[arg-type]
        ).model_dump(mode="json")
    )
    build_with_non_prepareable = CharacterBuild.model_validate(payload)
    state = build_p0_fighter_wizard_state()
    state.prepared_spell_entry_ids = [f"wizard:not-daily-{access_type}"]

    with pytest.raises(CharacterValidationError, match="not prepareable"):
        validate_state_against_build(state, build_with_non_prepareable, registry)
