from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.content import load_default_content_registry
from app.domain.character.schemas import AbilityScores, CharacterBuild, SubclassSelection
from app.domain.character.validation import CharacterValidationError, validate_build_references
from app.domain.character_builder.m01j_expertise import apply_m01j_skill_expertise
from app.domain.character_builder.m01j_subclasses import m01j_choice_id
from app.domain.character_builder.schemas import (
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderMode,
)
from app.domain.rules.skills import skill_modifier


CLERIC_REF = "srd5.1:class:cleric"
FIGHTER_REF = "srd5.1:class:fighter"
ROGUE_REF = "srd5.1:class:rogue"
WIZARD_REF = "srd5.1:class:wizard"
KNOWLEDGE_REF = "phb2014:subclass:knowledge"
SCOUT_REF = "xge:subclass:scout"
PURPLE_DRAGON_KNIGHT_REF = "scag:subclass:purple-dragon-knight"
ARCANA_REF = "srd5.1:skill:arcana"
HISTORY_REF = "srd5.1:skill:history"
NATURE_REF = "srd5.1:skill:nature"
SURVIVAL_REF = "srd5.1:skill:survival"
PERSUASION_REF = "srd5.1:skill:persuasion"


def _draft(selections: dict[str, BuilderChoiceSelection] | None = None) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=BuilderDraftPayload(choice_selections=selections or {}),
        created_at=now,
        updated_at=now,
    )


def _build(
    class_ref: str,
    subclass_ref: str,
    *,
    level: int,
    skills: tuple[str, ...],
) -> CharacterBuild:
    return CharacterBuild(
        race_ref="srd5.1:race:human",
        character_level=level,
        class_progression=(class_ref,) * level,
        subclasses=(SubclassSelection(class_ref=class_ref, subclass_ref=subclass_ref),),
        ability_scores=AbilityScores(
            strength=10,
            dexterity=10,
            constitution=10,
            intelligence=14,
            wisdom=14,
            charisma=14,
        ),
        skill_choices=skills,
        hp_progression=(8,) + (5,) * (level - 1),
    )


def _multiclass_build(
    progression: tuple[str, ...],
    subclasses: tuple[tuple[str, str], ...],
    *,
    skills: tuple[str, ...],
) -> CharacterBuild:
    level = len(progression)
    return CharacterBuild(
        race_ref="srd5.1:race:human",
        character_level=level,
        class_progression=progression,
        subclasses=tuple(
            SubclassSelection(class_ref=class_ref, subclass_ref=subclass_ref)
            for class_ref, subclass_ref in subclasses
        ),
        ability_scores=AbilityScores(
            strength=10,
            dexterity=10,
            constitution=10,
            intelligence=14,
            wisdom=14,
            charisma=14,
        ),
        skill_choices=skills,
        hp_progression=(8,) + (5,) * (level - 1),
    )


def test_knowledge_domain_expertise_tracks_exact_selected_skills() -> None:
    choice_id = m01j_choice_id(KNOWLEDGE_REF, "knowledge-domain-skills")
    draft = _draft(
        {
            choice_id: BuilderChoiceSelection(
                choice_id=choice_id,
                source_ref=KNOWLEDGE_REF,
                selected_option_ids=(ARCANA_REF, HISTORY_REF),
            )
        }
    )
    build = _build(
        CLERIC_REF,
        KNOWLEDGE_REF,
        level=5,
        skills=(ARCANA_REF, HISTORY_REF),
    )
    result = apply_m01j_skill_expertise(build, draft)
    assert result.skill_expertise_refs == (ARCANA_REF, HISTORY_REF)


def test_scout_expertise_is_nature_and_survival() -> None:
    build = _build(
        ROGUE_REF,
        SCOUT_REF,
        level=3,
        skills=(NATURE_REF, SURVIVAL_REF),
    )
    result = apply_m01j_skill_expertise(build, _draft())
    assert result.skill_expertise_refs == (NATURE_REF, SURVIVAL_REF)


def test_royal_envoy_expertise_stays_on_persuasion() -> None:
    build = _build(
        FIGHTER_REF,
        PURPLE_DRAGON_KNIGHT_REF,
        level=7,
        skills=(PERSUASION_REF, "srd5.1:skill:insight"),
    )
    result = apply_m01j_skill_expertise(build, _draft())
    assert result.skill_expertise_refs == (PERSUASION_REF,)


@pytest.mark.parametrize("fighter_level", [3, 4, 5, 6])
def test_royal_envoy_expertise_waits_for_fighter_7(fighter_level: int) -> None:
    """Royal Envoy is a 7th-level feature; choosing the oath at 3 grants nothing."""

    build = _build(
        FIGHTER_REF,
        PURPLE_DRAGON_KNIGHT_REF,
        level=fighter_level,
        skills=(PERSUASION_REF,),
    )
    result = apply_m01j_skill_expertise(build, _draft())
    assert result.skill_expertise_refs == ()


def test_royal_envoy_expertise_uses_class_level_not_character_level() -> None:
    """Fighter 3 / Wizard 9 is character level 12 but only Fighter 3."""

    build = _multiclass_build(
        (FIGHTER_REF,) * 3 + (WIZARD_REF,) * 9,
        ((FIGHTER_REF, PURPLE_DRAGON_KNIGHT_REF),),
        skills=(PERSUASION_REF,),
    )
    assert build.character_level == 12
    assert apply_m01j_skill_expertise(build, _draft()).skill_expertise_refs == ()

    build = _multiclass_build(
        (FIGHTER_REF,) * 7 + (WIZARD_REF,) * 5,
        ((FIGHTER_REF, PURPLE_DRAGON_KNIGHT_REF),),
        skills=(PERSUASION_REF,),
    )
    assert apply_m01j_skill_expertise(build, _draft()).skill_expertise_refs == (PERSUASION_REF,)


def test_scout_expertise_uses_rogue_level_not_character_level() -> None:
    """Survivalist is a 3rd-level Scout feature and must track the rogue level."""

    build = _multiclass_build(
        (ROGUE_REF,) * 2 + (FIGHTER_REF,) * 8,
        ((ROGUE_REF, SCOUT_REF),),
        skills=(NATURE_REF, SURVIVAL_REF),
    )
    assert apply_m01j_skill_expertise(build, _draft()).skill_expertise_refs == ()


def test_expertise_skill_modifier_adds_proficiency_bonus_twice() -> None:
    registry = load_default_content_registry()
    build = _build(
        CLERIC_REF,
        KNOWLEDGE_REF,
        level=5,
        skills=(ARCANA_REF,),
    ).model_copy(update={"skill_expertise_refs": (ARCANA_REF,)})
    # INT 14 => +2, character level 5 => PB +3, expertise => another +3.
    assert skill_modifier(build, ARCANA_REF, registry) == 8


def test_character_build_rejects_expertise_without_proficiency() -> None:
    with pytest.raises(ValidationError):
        CharacterBuild(
            race_ref="srd5.1:race:human",
            character_level=1,
            class_progression=(CLERIC_REF,),
            ability_scores=AbilityScores(
                strength=10,
                dexterity=10,
                constitution=10,
                intelligence=10,
                wisdom=10,
                charisma=10,
            ),
            skill_expertise_refs=(ARCANA_REF,),
            hp_progression=(8,),
        )


def test_build_reference_validation_rejects_unknown_expertise_skill() -> None:
    registry = load_default_content_registry()
    unknown = "srd5.1:skill:not-a-real-skill"
    build = _build(
        CLERIC_REF,
        KNOWLEDGE_REF,
        level=1,
        skills=(unknown,),
    ).model_copy(update={"skill_expertise_refs": (unknown,)})
    with pytest.raises(CharacterValidationError, match="unknown content reference"):
        validate_build_references(build, registry)
