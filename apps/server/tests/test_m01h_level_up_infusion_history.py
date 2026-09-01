from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.content import load_default_content_registry
from app.domain.character.schemas import AbilityScores, CharacterBuild
from app.domain.character_builder.artificer import (
    build_artificer_infusion_choices,
    compile_artificer_infusion_refs,
)
from app.domain.character_builder.schemas import (
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderHPMethod,
    BuilderLevelChoice,
    BuilderMode,
)
from app.domain.rules.artificer import ARTIFICER_REF


KNOWN_LEVEL2 = (
    "tce:infusion:enhanced-defense",
    "tce:infusion:enhanced-weapon",
    "tce:infusion:enhanced-arcane-focus",
    "tce:infusion:returning-weapon",
)


def _base_build() -> CharacterBuild:
    return CharacterBuild(
        content_sources=("srd5.1", "tce"),
        race_ref="srd5.1:race:human",
        character_level=2,
        class_progression=(ARTIFICER_REF, ARTIFICER_REF),
        ability_scores=AbilityScores(
            strength=10,
            dexterity=14,
            constitution=10,
            intelligence=16,
            wisdom=10,
            charisma=10,
        ),
        infusion_refs=KNOWN_LEVEL2,
        hp_progression=(8, 5),
    )


def _level(character_level: int) -> BuilderLevelChoice:
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=ARTIFICER_REF,
        hp_method=(
            BuilderHPMethod.FIRST_LEVEL
            if character_level == 1
            else BuilderHPMethod.FIXED_AVERAGE
        ),
        hp_base_gain=8 if character_level == 1 else 5,
    )


def test_level_up_without_known_infusion_delta_preserves_history_internally() -> None:
    base = _base_build()
    historical_choice_id = "level:2:artificer:infusions-known"
    now = datetime.now(UTC)
    draft = BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.LEVEL_UP,
        character_id=uuid4(),
        base_version_id=uuid4(),
        revision=1,
        draft_payload=BuilderDraftPayload(
            target_level=3,
            level_choices=(_level(1), _level(2), _level(3)),
            choice_selections={
                historical_choice_id: BuilderChoiceSelection(
                    choice_id=historical_choice_id,
                    source_ref="tce:feature:infuse-item",
                    selected_option_ids=KNOWN_LEVEL2,
                    provenance_path="build.infusion_refs",
                )
            },
        ),
        created_at=now,
        updated_at=now,
    )

    choices = build_artificer_infusion_choices(
        draft,
        load_default_content_registry(),
        base_build=base,
    )

    assert len(choices) == 1
    preserved = choices[0]
    assert preserved.choice_id == historical_choice_id
    assert preserved.option_source == "internal:preserved-artificer-infusions"
    assert preserved.disabled_reason is not None
    assert not any(choice.option_source == "content:infusion" for choice in choices)
    assert compile_artificer_infusion_refs(draft, choices, base_build=base) == KNOWN_LEVEL2
