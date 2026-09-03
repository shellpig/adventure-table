from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.content.schemas import (
    APIReference,
    AbilityName,
    DATA_MODELS,
    FeatureData,
    RaceData,
    RaceVariantMovementGrant,
    StrictModel,
    SubraceData,
)


MovementGrantData = RaceVariantMovementGrant
RestType = Literal["short_rest", "long_rest"]


class NaturalArmorData(StrictModel):
    base: int = Field(ge=1)
    ability: AbilityName
    requires_unarmored: bool = True


class RacialSpellRuntimeRestrictionData(StrictModel):
    kind: Literal["target_creature_type", "manual"]
    creature_type: str | None = Field(default=None, min_length=1, max_length=80)
    note: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def restriction_is_well_formed(self) -> "RacialSpellRuntimeRestrictionData":
        if self.kind == "target_creature_type" and self.creature_type is None:
            raise ValueError("target_creature_type restriction requires creature_type")
        if self.kind == "manual" and self.note is None:
            raise ValueError("manual racial spell restriction requires note")
        return self


class RacialSpellAccessData(StrictModel):
    spell: APIReference
    min_character_level: int = Field(default=1, ge=1, le=20)
    casting_ability: AbilityName | None = None
    uses_spell_slot: Literal[False] = False
    uses_per_rest: int | None = Field(default=None, ge=1)
    recharge_types: list[RestType] = Field(default_factory=list)
    # Backward-compatible authoring input used by M01-D/E data. New M01-L data
    # writes recharge_types instead; runtime compilation consumes only that view.
    rest_type: RestType | None = None
    runtime_restrictions: list[RacialSpellRuntimeRestrictionData] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_rest_type(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        legacy = payload.get("rest_type")
        recharge = payload.get("recharge_types")
        if legacy is not None:
            if recharge in (None, []):
                payload["recharge_types"] = [legacy]
            elif isinstance(recharge, list) and legacy not in recharge:
                raise ValueError("legacy rest_type conflicts with recharge_types")
        return payload

    @field_validator("recharge_types")
    @classmethod
    def recharge_types_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("racial spell recharge types must be unique")
        return value

    @model_validator(mode="after")
    def usage_metadata_is_consistent(self) -> "RacialSpellAccessData":
        if (self.uses_per_rest is None) != (len(self.recharge_types) == 0):
            raise ValueError(
                "racial spell limited use requires uses_per_rest and at least one recharge type"
            )
        return self


class M01LRaceData(RaceData):
    movement_grants: list[MovementGrantData] = Field(default_factory=list)


class M01LSubraceData(SubraceData):
    movement_grants: list[MovementGrantData] = Field(default_factory=list)


class M01LFeatureData(FeatureData):
    natural_armor: NaturalArmorData | None = None
    racial_spell_access: list[RacialSpellAccessData] = Field(default_factory=list)


def install_m01l_content_models() -> None:
    """Install the M01-L typed extensions before any default content is loaded.

    The underlying content envelope remains unchanged. This deliberately extends
    only the three existing kinds that M01-L needs instead of introducing an
    ancestry-specific effect language.
    """

    DATA_MODELS["race"] = M01LRaceData
    DATA_MODELS["subrace"] = M01LSubraceData
    DATA_MODELS["feature"] = M01LFeatureData
