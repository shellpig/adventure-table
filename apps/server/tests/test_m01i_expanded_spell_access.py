from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character_builder.m01i_runtime import prepare_optional_class_features_for_m01i
from app.domain.character_builder.optional_class_features import _choice_id
from app.domain.character_builder.schemas import (
    BuilderChoiceSelection,
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


def _draft(active: bool) -> BuilderDraft:
    now = datetime.now(UTC)
    draft = BuilderDraft(
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
    if not active:
        return draft
    choice_id = _choice_id(draft, "optional-feature", ADDITIONAL_BARD_SPELLS)
    selection = BuilderChoiceSelection(
        choice_id=choice_id,
        source_ref=ADDITIONAL_BARD_SPELLS,
        selected_option_ids=(ADDITIONAL_BARD_SPELLS,),
    )
    payload = draft.draft_payload.model_copy(
        update={"choice_selections": {choice_id: selection}}
    )
    return draft.model_copy(update={"draft_payload": payload})


def test_expanded_spell_access_changes_eligibility_without_auto_granting_spell() -> None:
    registry = load_default_content_registry()

    inactive = _draft(False)
    inactive_runtime = prepare_optional_class_features_for_m01i(inactive, registry)
    inactive_spellcasting = compile_spellcasting(
        inactive,
        inactive_runtime.registry,
        effective_abilities={"charisma": 16},
    )
    inactive_available = {
        option.spell_key
        for profile in inactive_spellcasting.profiles
        for option in profile.available_spells
    }
    assert COLOR_SPRAY not in inactive_available

    active = _draft(True)
    active_runtime = prepare_optional_class_features_for_m01i(active, registry)
    assert ADDITIONAL_BARD_SPELLS in active_runtime.active_feature_refs
    active_spellcasting = compile_spellcasting(
        active,
        active_runtime.registry,
        effective_abilities={"charisma": 16},
    )
    active_available = {
        option.spell_key
        for profile in active_spellcasting.profiles
        for option in profile.available_spells
    }

    assert COLOR_SPRAY in active_available
    assert COLOR_SPRAY not in {entry.spell_key for entry in active_spellcasting.spell_access_entries}
    assert COLOR_SPRAY not in {entry.spell_key for entry in active_spellcasting.initial_prepared_spells}
