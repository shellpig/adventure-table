from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.content.m01l_models import (
    M01LFeatureData,
    M01LRaceData,
    M01LSubraceData,
    RacialSpellAccessData,
)
from app.content.schemas import (
    AbilityName,
    DATA_MODELS,
    RaceVariantData,
    RaceVariantReplacementGroup,
    RaceVariantReplacementOption,
    StrictModel,
)


SpellComponent = Literal["V", "S", "M"]
CastingModifier = Literal["enlarge_effect_only", "mage_hand_invisible"]


class RaceVariantAbilityBonus(StrictModel):
    ability: AbilityName
    bonus: int = Field(ge=-2, le=2)


class MovementConditionData(StrictModel):
    kind: Literal["not_wearing_armor_category"]
    armor_category: Literal["heavy"]


class ConditionalMovementGrantData(StrictModel):
    mode: Literal["walk", "swim", "climb", "fly"]
    speed: int = Field(gt=0)
    condition: MovementConditionData | None = None


class M01MRacialSpellAccessData(RacialSpellAccessData):
    # Static casting facts required by MTF/SCAG racial psionics. They stay on
    # canonical content and are re-resolvable from SpellAccessEntry.source_key;
    # no spell/combat engine is introduced here.
    cast_at_level: int | None = Field(default=None, ge=1, le=9)
    waive_components: tuple[SpellComponent, ...] = ()
    # Closed, locale-neutral modifiers that change how the referenced spell is
    # used without requiring a general spell-effect language.
    casting_modifiers: tuple[CastingModifier, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def normalize_closed_restriction_tokens(cls, value: object) -> object:
        """Accept M01-M closed authoring tokens through the existing M01-L shape.

        M01-L already owns the generic runtime-restriction transport as typed
        objects. MTF needs two non-executable restrictions (self-only and direct
        sunlight), so normalize their compact checked-in tokens into the existing
        manual restriction form instead of creating a second runtime-state model.
        """

        if not isinstance(value, dict):
            return value
        payload = dict(value)
        raw = payload.get("runtime_restrictions")
        if not isinstance(raw, list):
            return payload
        normalized: list[object] = []
        for restriction in raw:
            if restriction == "self_only":
                normalized.append(
                    {
                        "kind": "manual",
                        "note": "This racial casting can target only the caster.",
                    }
                )
            elif restriction == "cannot_cast_in_direct_sunlight":
                normalized.append(
                    {
                        "kind": "manual",
                        "note": "This racial casting cannot be used while the caster is in direct sunlight.",
                    }
                )
            else:
                normalized.append(restriction)
        payload["runtime_restrictions"] = normalized
        return payload

    @field_validator("waive_components", "casting_modifiers")
    @classmethod
    def closed_casting_lists_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("racial casting modifier/component lists must be unique")
        return value


class FeatureModeData(StrictModel):
    mode_key: str = Field(min_length=1, max_length=120)
    options: tuple[str, ...] = Field(min_length=1)
    default: str = Field(min_length=1, max_length=120)
    change_timing: Literal["manual", "manual_after_long_rest"] = "manual"

    @model_validator(mode="after")
    def mode_contract_is_well_formed(self) -> "FeatureModeData":
        if len(self.options) != len(set(self.options)):
            raise ValueError("feature mode options must be unique")
        if self.default not in self.options:
            raise ValueError("feature mode default must be one of options")
        return self


class M01MRaceVariantReplacementOption(RaceVariantReplacementOption):
    movement: list[ConditionalMovementGrantData] = Field(default_factory=list)
    replacement_ability_bonuses: list[RaceVariantAbilityBonus] | None = None

    @field_validator("replacement_ability_bonuses")
    @classmethod
    def replacement_abilities_are_unique(
        cls, value: list[RaceVariantAbilityBonus] | None
    ) -> list[RaceVariantAbilityBonus] | None:
        if value is None:
            return value
        abilities = [item.ability for item in value]
        if len(abilities) != len(set(abilities)):
            raise ValueError("replacement ability bonuses must target unique abilities")
        return value


class M01MRaceVariantReplacementGroup(RaceVariantReplacementGroup):
    options: list[M01MRaceVariantReplacementOption] = Field(min_length=1)


class M01MRaceVariantData(RaceVariantData):
    replacement_groups: list[M01MRaceVariantReplacementGroup] = Field(min_length=1)


class M01MRaceData(M01LRaceData):
    pass


class M01MSubraceData(M01LSubraceData):
    feature_mode: FeatureModeData | None = None


class M01MFeatureData(M01LFeatureData):
    racial_spell_access: list[M01MRacialSpellAccessData] = Field(default_factory=list)
    conditional_movement: list[ConditionalMovementGrantData] = Field(default_factory=list)
    feature_mode: FeatureModeData | None = None


def install_m01m_content_models() -> None:
    """Extend M01-L ancestry primitives with only the M01-M shapes.

    Race/subrace/feature remain ordinary content kinds. Tiefling bloodlines and
    SCAG variants continue to use the existing race-variant kind; M01-M merely
    types multi-group replacement ability packages and conditional movement.
    """

    DATA_MODELS["race"] = M01MRaceData
    DATA_MODELS["subrace"] = M01MSubraceData
    DATA_MODELS["feature"] = M01MFeatureData
    DATA_MODELS["race-variant"] = M01MRaceVariantData
