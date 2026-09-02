from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character_builder.m01i_runtime import prepare_optional_class_features_for_m01i
from app.domain.character_builder.schemas import (
    BuilderDraft,
    BuilderDraftPayload,
    BuilderHPMethod,
    BuilderLevelChoice,
    BuilderMode,
)
from app.domain.character_builder.spellcasting import compile_spellcasting


BARD = "srd5.1:class:bard"
ADDITIONAL_BARD_SPELLS = "tce:feature:additional-bard-spells"
COLOR_SPRAY = "srd5.1:spell:color-spray"


def _draft() -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=BuilderDraftPayload(
            target_level=1,
            level_choices=(
                BuilderLevelChoice(
                    character_level=1,
                    class_ref=BARD,
                    hp_method=BuilderHPMethod.FIRST_LEVEL,
                    hp_base_gain=8,
                ),
            ),
        ),
        created_at=now,
        updated_at=now,
    )


def test_expanded_spell_access_is_available_without_auto_granting_spell() -> None:
    registry = load_default_content_registry()

    draft = _draft()
    runtime = prepare_optional_class_features_for_m01i(draft, registry)
    assert ADDITIONAL_BARD_SPELLS in runtime.active_feature_refs

    spellcasting = compile_spellcasting(
        draft,
        runtime.registry,
        effective_abilities={"charisma": 16},
    )
    available = {
        option.spell_key
        for profile in spellcasting.profiles
        for option in profile.available_spells
    }

    assert COLOR_SPRAY in available
    assert COLOR_SPRAY not in {entry.spell_key for entry in spellcasting.spell_access_entries}
    assert COLOR_SPRAY not in {entry.spell_key for entry in spellcasting.initial_prepared_spells}


def test_expanded_option_pool_is_not_offered_as_an_adoption_choice() -> None:
    registry = load_default_content_registry()

    runtime = prepare_optional_class_features_for_m01i(_draft(), registry)

    assert ADDITIONAL_BARD_SPELLS not in {
        choice.source_ref for choice in runtime.choices
    }
