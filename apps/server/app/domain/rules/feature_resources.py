from __future__ import annotations

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild, ResourceCounter


def spell_access_resource_key(source_key: str, spell_key: str) -> str:
    """Stable live-state identity for Build-granted limited-use spell access."""

    return f"spell-access:{source_key}:{spell_key}"


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

    # Some ancestry/feature spell grants do not consume normal spell slots but
    # instead have their own per-rest uses (for example SCAG Half-Elf Drow
    # Magic). Keep those counters in generic Current State resources so they
    # participate in the same creation and Build-version reconciliation flow as
    # other Build-derived resources without polluting class spell-slot pools.
    for access in build.spell_access_entries:
        if access.uses_per_rest is None:
            continue
        capacities[
            spell_access_resource_key(access.source_key, access.spell_key)
        ] = access.uses_per_rest

    return capacities


def initial_feature_resource_state(
    build: CharacterBuild,
    registry: ContentRegistry,
) -> dict[str, ResourceCounter]:
    return {
        key: ResourceCounter(used=0, remaining=capacity)
        for key, capacity in feature_resource_capacities(build, registry).items()
    }
