from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.content.identity import reference_to_stable_key
from app.content.registry import ContentRegistry, ContentValidationError
from app.content.schemas import APIReference, ContentEntry


class _PermissiveModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class BuilderChoiceRuleData(_PermissiveModel):
    desc: str | None = None
    choose: int = Field(ge=0)
    type: str
    from_: dict[str, Any] = Field(alias="from")


class BuilderStartingEquipmentData(_PermissiveModel):
    equipment: APIReference
    quantity: int = Field(ge=1)


class BuilderMulticlassPrerequisiteData(_PermissiveModel):
    ability_score: APIReference
    minimum_score: int = Field(ge=1, le=30)


class BuilderMulticlassData(_PermissiveModel):
    prerequisites: list[BuilderMulticlassPrerequisiteData] = Field(default_factory=list)
    prerequisite_options: dict[str, Any] | None = None
    proficiencies: list[APIReference] = Field(default_factory=list)
    proficiency_choices: list[BuilderChoiceRuleData] = Field(default_factory=list)


class BuilderSpellcastingIdentityData(_PermissiveModel):
    level: int = Field(ge=1, le=20)
    spellcasting_ability: APIReference
    ritual_casting: bool | None = None
    focus_requirement: dict[str, Any] | None = None
    info: list[dict[str, Any]] = Field(default_factory=list)


class BuilderClassData(_PermissiveModel):
    index: str
    name: str
    hit_die: int
    proficiency_choices: list[BuilderChoiceRuleData] = Field(default_factory=list)
    proficiencies: list[APIReference] = Field(default_factory=list)
    saving_throws: list[APIReference]
    starting_equipment: list[BuilderStartingEquipmentData] = Field(default_factory=list)
    starting_equipment_options: list[BuilderChoiceRuleData] = Field(default_factory=list)
    multi_classing: BuilderMulticlassData | None = None
    subclasses: list[APIReference]
    spellcasting: BuilderSpellcastingIdentityData | None = None
    spell_list: list[APIReference] = Field(default_factory=list)


def _reference_payload(reference: APIReference) -> dict[str, Any]:
    return reference.model_dump(exclude_none=True, by_alias=True)


def _validate_spell_relation(
    registry: ContentRegistry,
    owner: ContentEntry,
    references: list[APIReference],
    field: str,
) -> None:
    for reference in references:
        try:
            key = reference_to_stable_key(_reference_payload(reference), kinds={"spell"})
        except ValueError as exc:
            raise ContentValidationError(
                f"{owner.key}.{field} contains an invalid spell reference"
            ) from exc
        if key is None or registry.get_optional(key) is None:
            raise ContentValidationError(f"{owner.key}.{field} has dangling spell reference: {key}")


def validate_builder_content(registry: ContentRegistry) -> ContentRegistry:
    """Validate Builder-dependent class fields and cross-pack spell relations.

    Core content schemas intentionally remain permissive for imported source
    payloads. This boundary model types the fields the Character Builder relies
    on without forcing an all-at-once rewrite of every content schema.
    """

    for class_entry in registry.list_kind("class"):
        try:
            parsed = BuilderClassData.model_validate(class_entry.data)
        except ValidationError as exc:
            raise ContentValidationError(
                f"invalid Character Builder class data for {class_entry.key}: {exc}"
            ) from exc
        _validate_spell_relation(registry, class_entry, parsed.spell_list, "spell_list")

    for subclass_entry in registry.list_kind("subclass"):
        raw_spells = subclass_entry.data.get("spells")
        if raw_spells is None:
            continue
        if not isinstance(raw_spells, list):
            raise ContentValidationError(f"{subclass_entry.key}.spells must be a list")
        references: list[APIReference] = []
        for index, row in enumerate(raw_spells):
            if not isinstance(row, dict) or not isinstance(row.get("spell"), dict):
                raise ContentValidationError(
                    f"{subclass_entry.key}.spells[{index}] is missing a spell reference"
                )
            try:
                references.append(APIReference.model_validate(row["spell"]))
            except ValidationError as exc:
                raise ContentValidationError(
                    f"{subclass_entry.key}.spells[{index}] has invalid spell identity"
                ) from exc
        _validate_spell_relation(registry, subclass_entry, references, "spells")

    return registry
