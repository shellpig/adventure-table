from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.content.identity import reference_to_stable_key
from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, CharacterState, ResourceCounter
from app.domain.rules.artificer import (
    ARCANE_ARMOR_PARTS,
    ARMOR_MODEL_FEATURE_REF,
    ARMOR_MODELS,
    artificer_level,
    armor_modifications_metadata,
    attunement_capacity,
    attunement_requirement_exceptions,
    advanced_feature_resource_rules,
    infused_item_capacity,
    infusion_charge_capacity,
    known_infusion_count,
    spell_storing_item_capacity,
    subclass_runtime_metadata,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtificerKnownInfusionDTO(StrictModel):
    infusion_ref: str
    name: str
    minimum_artificer_level: int = Field(ge=2, le=20)
    requires_attunement: bool
    item_filters: tuple[str, ...]
    modifiers: tuple[dict[str, Any], ...] = ()
    charge_capacity: int | None = Field(default=None, ge=0)
    replicates_item_ref: str | None = None
    description: str
    manual_effects: tuple[str, ...] = ()


class ArtificerActiveInfusionDTO(StrictModel):
    inventory_entry_id: str
    inventory_item_ref: str
    inventory_item_name: str
    infusion_ref: str
    infusion_name: str
    resource: ResourceCounter | None = None
    arcane_armor_part: str | None = None
    manual_effects: tuple[str, ...] = ()


class ArtificerTrackedResourceDTO(StrictModel):
    resource_id: str
    feature_ref: str
    feature_name: str
    capacity: int = Field(ge=0)
    used: int = Field(ge=0)
    remaining: int = Field(ge=0)
    recharge: tuple[str, ...]
    resolution: Literal["manual"] = "manual"


class ArtificerSpellStoringItemDTO(StrictModel):
    inventory_entry_id: str
    inventory_item_ref: str
    inventory_item_name: str
    spell_ref: str
    spell_name: str
    remaining_uses: int = Field(ge=0)
    capacity: int = Field(ge=0)
    cast_resolution: Literal["manual"] = "manual"


class ArtificerManualFeatureDTO(StrictModel):
    feature_ref: str
    feature_name: str
    runtime_kind: str
    resolution: Literal["manual", "state_tracked_effect_manual"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtificerSummaryDTO(StrictModel):
    artificer_level: int = Field(ge=1, le=20)
    known_infusions: tuple[ArtificerKnownInfusionDTO, ...] = ()
    known_infusion_limit: int = Field(ge=0)
    active_infusions: tuple[ArtificerActiveInfusionDTO, ...] = ()
    active_infusion_count: int = Field(ge=0)
    active_infusion_base_capacity: int = Field(ge=0)
    active_infusion_capacity_bonus: int = Field(ge=0)
    active_infusion_capacity: int = Field(ge=0)
    armor_modification_parts: tuple[str, ...] = ()
    attunement_capacity: int = Field(ge=3)
    attunement_requirement_bypasses: tuple[str, ...] = ()
    tracked_resources: tuple[ArtificerTrackedResourceDTO, ...] = ()
    armor_model: str | None = None
    armor_model_options: tuple[str, ...] = ()
    spell_storing_item_capacity: int = Field(ge=0)
    spell_storing_item: ArtificerSpellStoringItemDTO | None = None
    manual_features: tuple[ArtificerManualFeatureDTO, ...] = ()


def _reference_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _known_infusions(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> tuple[ArtificerKnownInfusionDTO, ...]:
    result: list[ArtificerKnownInfusionDTO] = []
    for infusion_ref in build.infusion_refs:
        entry = registry.get(infusion_ref)
        data = entry.data
        item_filter = data.get("item_filter")
        filters = (
            _reference_tuple(item_filter.get("any_of"))
            if isinstance(item_filter, dict)
            else ()
        )
        raw_replicated = data.get("replicates_item")
        replicated_ref = None
        if isinstance(raw_replicated, dict):
            replicated_ref = reference_to_stable_key(raw_replicated, kinds={"item"})
        minimum = data.get("minimum_artificer_level")
        result.append(
            ArtificerKnownInfusionDTO(
                infusion_ref=entry.key,
                name=entry.name,
                minimum_artificer_level=minimum if isinstance(minimum, int) else 2,
                requires_attunement=bool(data.get("requires_attunement")),
                item_filters=filters,
                modifiers=tuple(
                    item for item in data.get("modifiers", []) if isinstance(item, dict)
                ),
                charge_capacity=infusion_charge_capacity(data, build),
                replicates_item_ref=replicated_ref,
                description=str(data.get("description") or ""),
                manual_effects=_reference_tuple(data.get("manual_effects")),
            )
        )
    return tuple(result)


def _active_infusions(
    build: CharacterBuild,
    state: CharacterState | None,
    registry: ContentRegistry,
) -> tuple[ArtificerActiveInfusionDTO, ...]:
    if state is None:
        return ()
    inventory = {entry.entry_id: entry for entry in state.inventory_state}
    result: list[ArtificerActiveInfusionDTO] = []
    for active in state.active_infusions:
        item = inventory.get(active.inventory_entry_id)
        infusion = registry.get_optional(active.infusion_ref)
        if item is None or infusion is None:
            # Authoritative validation prevents this for persisted state. Keep
            # presentation resilient when rendering a review preview.
            continue
        item_content = registry.get_optional(item.item_ref)
        manual = _reference_tuple(infusion.data.get("manual_effects"))
        result.append(
            ArtificerActiveInfusionDTO(
                inventory_entry_id=item.entry_id,
                inventory_item_ref=item.item_ref,
                inventory_item_name=item_content.name if item_content is not None else item.item_ref,
                infusion_ref=infusion.key,
                infusion_name=infusion.name,
                resource=active.resource,
                arcane_armor_part=active.arcane_armor_part,
                manual_effects=manual,
            )
        )
    return tuple(result)


def _tracked_resources(
    build: CharacterBuild,
    state: CharacterState | None,
    registry: ContentRegistry,
) -> tuple[ArtificerTrackedResourceDTO, ...]:
    result: list[ArtificerTrackedResourceDTO] = []
    for rule in advanced_feature_resource_rules(build):
        counter = state.resources.get(rule.resource_id) if state is not None else None
        used = counter.used if counter is not None else 0
        remaining = counter.remaining if counter is not None else rule.capacity
        feature = registry.get_optional(rule.feature_ref)
        result.append(
            ArtificerTrackedResourceDTO(
                resource_id=rule.resource_id,
                feature_ref=rule.feature_ref,
                feature_name=feature.name if feature is not None else rule.feature_ref,
                capacity=rule.capacity,
                used=used,
                remaining=remaining,
                recharge=rule.recharge,
            )
        )
    return tuple(result)


def _spell_storing_item(
    build: CharacterBuild,
    state: CharacterState | None,
    registry: ContentRegistry,
) -> ArtificerSpellStoringItemDTO | None:
    if state is None or state.spell_storing_item is None:
        return None
    stored = state.spell_storing_item
    inventory = {entry.entry_id: entry for entry in state.inventory_state}
    item = inventory.get(stored.inventory_entry_id)
    if item is None:
        return None
    item_content = registry.get_optional(item.item_ref)
    spell = registry.get_optional(stored.spell_ref)
    return ArtificerSpellStoringItemDTO(
        inventory_entry_id=stored.inventory_entry_id,
        inventory_item_ref=item.item_ref,
        inventory_item_name=item_content.name if item_content is not None else item.item_ref,
        spell_ref=stored.spell_ref,
        spell_name=spell.name if spell is not None else stored.spell_ref,
        remaining_uses=stored.remaining_uses,
        capacity=spell_storing_item_capacity(build),
    )


def _manual_features(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> tuple[ArtificerManualFeatureDTO, ...]:
    result: list[ArtificerManualFeatureDTO] = []
    seen: set[str] = set()
    runtime = subclass_runtime_metadata(build)
    runtime_ref = runtime.get("feature_ref")
    if isinstance(runtime_ref, str):
        feature = registry.get_optional(runtime_ref)
        result.append(
            ArtificerManualFeatureDTO(
                feature_ref=runtime_ref,
                feature_name=feature.name if feature is not None else runtime_ref,
                runtime_kind=str(runtime.get("runtime_kind") or "manual"),
                resolution=(
                    "state_tracked_effect_manual"
                    if runtime.get("runtime_kind") == "feature_mode"
                    else "manual"
                ),
                metadata=runtime,
            )
        )
        seen.add(runtime_ref)

    # These features have useful persistent counters/identity in M01-H, but
    # their roll, reaction, damage or combat-entity effects are intentionally
    # outside the current automation substrate.
    for feature_ref in (
        "tce:feature:flash-of-genius",
        "tce:feature:arcane-jolt",
        "tce:feature:spell-storing-item",
    ):
        if feature_ref in seen or feature_ref not in build.feature_refs:
            continue
        feature = registry.get_optional(feature_ref)
        result.append(
            ArtificerManualFeatureDTO(
                feature_ref=feature_ref,
                feature_name=feature.name if feature is not None else feature_ref,
                runtime_kind="tracked_resource_or_state",
                resolution="state_tracked_effect_manual",
                metadata={"effect_resolution": "manual"},
            )
        )
    return tuple(result)


def build_artificer_summary(
    build: CharacterBuild,
    state: CharacterState | None,
    registry: ContentRegistry,
) -> ArtificerSummaryDTO | None:
    level = artificer_level(build)
    if level <= 0:
        return None

    armor_metadata = armor_modifications_metadata(build)
    capacity_bonus = (
        int(armor_metadata.get("capacity_bonus", 0))
        if armor_metadata is not None
        else 0
    )
    bypasses = tuple(
        key.removeprefix("ignore_").removesuffix("_requirement")
        for key, enabled in attunement_requirement_exceptions(build).items()
        if enabled
    )
    active = _active_infusions(build, state, registry)
    armor_options = ARMOR_MODELS if ARMOR_MODEL_FEATURE_REF in build.feature_refs else ()
    return ArtificerSummaryDTO(
        artificer_level=level,
        known_infusions=_known_infusions(build, registry),
        known_infusion_limit=known_infusion_count(level),
        active_infusions=active,
        active_infusion_count=len(active),
        active_infusion_base_capacity=infused_item_capacity(level),
        active_infusion_capacity_bonus=capacity_bonus,
        active_infusion_capacity=infused_item_capacity(level) + capacity_bonus,
        armor_modification_parts=ARCANE_ARMOR_PARTS if armor_metadata is not None else (),
        attunement_capacity=attunement_capacity(build),
        attunement_requirement_bypasses=bypasses,
        tracked_resources=_tracked_resources(build, state, registry),
        armor_model=(state.feature_modes.get(ARMOR_MODEL_FEATURE_REF) if state is not None else None),
        armor_model_options=armor_options,
        spell_storing_item_capacity=spell_storing_item_capacity(build),
        spell_storing_item=_spell_storing_item(build, state, registry),
        manual_features=_manual_features(build, registry),
    )
