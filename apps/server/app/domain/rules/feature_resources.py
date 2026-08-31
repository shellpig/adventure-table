from __future__ import annotations

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, ResourceCounter


def feature_resource_capacities(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> dict[str, int]:
    capacities: dict[str, int] = {}
    for feature_ref in build.feature_refs:
        feature = registry.get_optional(feature_ref)
        if feature is None:
            continue
        resource = feature.data.get("resource")
        if not isinstance(resource, dict):
            continue
        capacity = resource.get("capacity")
        if not isinstance(capacity, dict) or capacity.get("type") != "fixed":
            continue
        value = capacity.get("value")
        if not isinstance(value, int) or value < 0:
            continue
        capacities[f"feature:{feature_ref}"] = value
    return capacities


def initial_feature_resource_state(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> dict[str, ResourceCounter]:
    return {
        key: ResourceCounter(used=0, remaining=capacity)
        for key, capacity in feature_resource_capacities(build, registry).items()
    }
