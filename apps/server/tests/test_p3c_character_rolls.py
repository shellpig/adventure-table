from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.domain.character.schemas import AbilityScores, CharacterBuild, NumericOverride
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.rolls import RollInputInvalidError, RollRequestType


STEALTH = "srd5.1:skill:stealth"


class StaticCharacterRepository:
    def __init__(self, build: CharacterBuild) -> None:
        self.build = build
        self.loaded_ids: list[UUID] = []

    def load_character(self, character_id: UUID):
        self.loaded_ids.append(character_id)
        return SimpleNamespace(build=self.build)


class StaticRegistry:
    def get(self, key: str):
        if key != STEALTH:
            raise KeyError(key)
        return SimpleNamespace(
            index="stealth",
            key=STEALTH,
            data={"ability_score": {"index": "dex"}},
        )


def _build() -> CharacterBuild:
    return CharacterBuild(
        race_ref="srd5.1:race:human",
        character_level=5,
        class_progression=("srd5.1:class:fighter",) * 5,
        ability_scores=AbilityScores(
            strength=18,
            dexterity=14,
            constitution=14,
            intelligence=10,
            wisdom=12,
            charisma=8,
        ),
        saving_throw_proficiencies=("srd5.1:ability:str",),
        skill_choices=(STEALTH,),
        skill_expertise_refs=(STEALTH,),
        hp_progression=(10, 7, 7, 7, 7),
        numeric_overrides=(NumericOverride(key="ability:strength", value=20),),
    )


def _resolver() -> tuple[CharacterRollModifierResolver, StaticCharacterRepository]:
    repository = StaticCharacterRepository(_build())
    resolver = CharacterRollModifierResolver(
        repository,  # type: ignore[arg-type]
        StaticRegistry(),  # type: ignore[arg-type]
    )
    return resolver, repository


def test_ability_modifier_uses_effective_character_score_override() -> None:
    resolver, repository = _resolver()
    character_id = uuid4()

    modifier = resolver.modifier_for(
        character_id=character_id,
        request_type=RollRequestType.ABILITY,
        ability_ref="srd5.1:ability:str",
        skill_ref=None,
    )

    assert modifier == 5
    assert repository.loaded_ids == [character_id]


def test_skill_modifier_reuses_character_proficiency_and_expertise_rules() -> None:
    resolver, _repository = _resolver()

    modifier = resolver.modifier_for(
        character_id=uuid4(),
        request_type=RollRequestType.SKILL,
        ability_ref=None,
        skill_ref=STEALTH,
    )

    # Level 5 proficiency +3, expertise doubles it, DEX 14 contributes +2.
    assert modifier == 8


def test_saving_throw_modifier_reuses_character_save_proficiency() -> None:
    resolver, _repository = _resolver()

    modifier = resolver.modifier_for(
        character_id=uuid4(),
        request_type=RollRequestType.SAVING_THROW,
        ability_ref="srd5.1:ability:str",
        skill_ref=None,
    )

    # Effective STR 20 contributes +5 and Fighter save proficiency adds +3.
    assert modifier == 8


def test_other_formal_roll_has_no_hidden_character_modifier() -> None:
    resolver, repository = _resolver()
    character_id = uuid4()

    modifier = resolver.modifier_for(
        character_id=character_id,
        request_type=RollRequestType.OTHER,
        ability_ref=None,
        skill_ref=None,
    )

    assert modifier == 0
    assert repository.loaded_ids == [character_id]


def test_invalid_ability_ref_is_reported_as_roll_input_error() -> None:
    resolver, _repository = _resolver()

    with pytest.raises(RollInputInvalidError):
        resolver.modifier_for(
            character_id=uuid4(),
            request_type=RollRequestType.ABILITY,
            ability_ref="srd5.1:ability:not-real",
            skill_ref=None,
        )
