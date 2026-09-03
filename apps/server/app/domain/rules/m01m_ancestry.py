from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from app.content.m01m_models import (
    ConditionalMovementGrantData,
    FeatureModeData,
    M01MRacialSpellAccessData,
)
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, CharacterState, SpellAccessEntry


@dataclass(frozen=True)
class EffectiveMovement:
    walk: int
    swim: int | None
    climb: int | None
    fly: int | None


@dataclass(frozen=True)
class FeatureModeDefinition:
    key: str
    source_feature_ref: str
    options: tuple[str, ...]
    default: str
    change_timing: str


@dataclass(frozen=True)
class RacialSpellRuntimeMetadata:
    cast_at_level: int | None
    waive_components: tuple[str, ...]
    uses_spell_slot: bool


def _equipped_heavy_armor(
    state: CharacterState,
    registry: ContentRegistry,
) -> bool:
    for inventory_entry in state.inventory_state:
        if not inventory_entry.equipped:
            continue
        content = registry.get_optional(inventory_entry.item_ref)
        if content is None:
            continue
        equipment_category = content.data.get("equipment_category")
        if not isinstance(equipment_category, dict):
            continue
        if equipment_category.get("index") != "armor":
            continue
        if content.data.get("armor_category") == "Heavy":
            return True
    return False


def _movement_condition_is_met(
    grant: ConditionalMovementGrantData,
    *,
    heavy_armor_equipped: bool,
) -> bool:
    condition = grant.condition
    if condition is None:
        return True
    if condition.kind == "not_wearing_armor_category" and condition.armor_category == "heavy":
        return not heavy_armor_equipped
    return False


def effective_movement(
    build: CharacterBuild,
    state: CharacterState,
    registry: ContentRegistry,
) -> EffectiveMovement:
    """Resolve live equipment-dependent movement without mutating the Build.

    The immutable Build stores ancestry capability. M01-M conditions are then
    evaluated against Current State so equipping or unequipping heavy armor can
    change Winged Tiefling flight immediately without a new Build version.
    """

    race = registry.get(build.race_ref)
    race_speed = race.data.get("speed")
    if not isinstance(race_speed, int) or race_speed <= 0:
        raise ValueError(f"race {build.race_ref} has invalid walking speed")

    speeds: dict[str, int | None] = {
        "walk": build.walking_speed if build.walking_speed is not None else race_speed,
        "swim": build.swim_speed,
        "climb": build.climb_speed,
        "fly": build.fly_speed,
    }
    heavy_armor_equipped = _equipped_heavy_armor(state, registry)

    for feature_ref in build.feature_refs:
        feature = registry.get_optional(feature_ref)
        if feature is None:
            continue
        raw_grants = feature.data.get("conditional_movement")
        if not isinstance(raw_grants, list):
            continue
        for raw in raw_grants:
            try:
                grant = ConditionalMovementGrantData.model_validate(raw)
            except (ValidationError, ValueError):
                continue
            if _movement_condition_is_met(
                grant,
                heavy_armor_equipped=heavy_armor_equipped,
            ):
                speeds[grant.mode] = grant.speed
            elif grant.mode != "walk":
                speeds[grant.mode] = None

    return EffectiveMovement(
        walk=int(speeds["walk"] or race_speed),
        swim=speeds["swim"],
        climb=speeds["climb"],
        fly=speeds["fly"],
    )


def feature_mode_definitions(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> tuple[FeatureModeDefinition, ...]:
    definitions: list[FeatureModeDefinition] = []
    seen_keys: set[str] = set()
    for feature_ref in build.feature_refs:
        feature = registry.get_optional(feature_ref)
        if feature is None:
            continue
        raw = feature.data.get("feature_mode")
        if not isinstance(raw, dict):
            continue
        try:
            mode = FeatureModeData.model_validate(raw)
        except (ValidationError, ValueError):
            continue
        if mode.mode_key in seen_keys:
            raise ValueError(f"duplicate feature mode key in Build: {mode.mode_key}")
        seen_keys.add(mode.mode_key)
        definitions.append(
            FeatureModeDefinition(
                key=mode.mode_key,
                source_feature_ref=feature_ref,
                options=tuple(mode.options),
                default=mode.default,
                change_timing=mode.change_timing,
            )
        )
    return tuple(definitions)


def effective_feature_modes(
    build: CharacterBuild,
    state: CharacterState,
    registry: ContentRegistry,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for definition in feature_mode_definitions(build, registry):
        selected = state.feature_modes.get(definition.key, definition.default)
        if selected not in definition.options:
            raise ValueError(
                f"invalid feature mode {selected!r} for {definition.key}; "
                f"expected one of {definition.options}"
            )
        result[definition.key] = selected
    return result


def validate_feature_modes(
    build: CharacterBuild,
    state: CharacterState,
    registry: ContentRegistry,
) -> None:
    definitions = {
        definition.key: definition
        for definition in feature_mode_definitions(build, registry)
    }
    for key, selected in state.feature_modes.items():
        definition = definitions.get(key)
        if definition is None:
            raise ValueError(f"feature mode is not granted by Build: {key}")
        if selected not in definition.options:
            raise ValueError(f"invalid feature mode {selected!r} for {key}")


def racial_spell_runtime_metadata(
    access_entry: SpellAccessEntry,
    registry: ContentRegistry,
) -> RacialSpellRuntimeMetadata | None:
    if access_entry.source_type != "race":
        return None
    feature = registry.get_optional(access_entry.source_key)
    if feature is None:
        return None
    raw_access = feature.data.get("racial_spell_access")
    if not isinstance(raw_access, list):
        return None
    for raw in raw_access:
        try:
            access = M01MRacialSpellAccessData.model_validate(raw)
        except (ValidationError, ValueError):
            continue
        spell = access.spell
        reference = spell.key or (
            f"srd5.1:spell:{spell.index}" if spell.index is not None else None
        )
        if reference != access_entry.spell_key:
            continue
        return RacialSpellRuntimeMetadata(
            cast_at_level=access.cast_at_level,
            waive_components=tuple(access.waive_components),
            uses_spell_slot=bool(access.uses_spell_slot),
        )
    return None
