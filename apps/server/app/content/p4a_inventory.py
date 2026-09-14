from __future__ import annotations

from app.content.registry import ContentRegistry, ContentValidationError


EXPECTED_SRD_MONSTER_COUNT = 334
EXPECTED_SRD_BEAST_COUNT = 87


def validate_p4a_monster_inventory(registry: ContentRegistry) -> ContentRegistry:
    """Fail when the checked-in SRD Monster inventory drifts from P4-A scope."""

    monsters = registry.list_kind("monster", source="srd5.1")
    # This validator is installed before the large canonical Monster dataset is
    # checked in so the foundation commit can remain independently loadable.
    # Once the manifest exposes the monster category, category count validation
    # guarantees that an empty result is no longer possible.
    if not monsters:
        return registry

    if len(monsters) != EXPECTED_SRD_MONSTER_COUNT:
        raise ContentValidationError(
            f"P4-A expected {EXPECTED_SRD_MONSTER_COUNT} SRD monsters, got {len(monsters)}"
        )

    beast_count = sum(
        1
        for entry in monsters
        if isinstance(entry.data.get("type"), str)
        and entry.data["type"].casefold() == "beast"
    )
    if beast_count != EXPECTED_SRD_BEAST_COUNT:
        raise ContentValidationError(
            f"P4-A expected {EXPECTED_SRD_BEAST_COUNT} SRD beasts, got {beast_count}"
        )

    return registry
