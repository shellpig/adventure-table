from __future__ import annotations

from app.content.registry import ContentRegistry, ContentValidationError


EXPECTED_SRD_MONSTER_COUNT = 334
EXPECTED_SRD_BEAST_COUNT = 87


def validate_p4a_monster_inventory(registry: ContentRegistry) -> ContentRegistry:
    """Fail when the checked-in SRD Monster inventory drifts from P4-A scope."""

    monsters = registry.list_kind("monster", source="srd5.1")
    # M03-A lets a deployment disable the srd5.1 pack. With no SRD monsters
    # loaded there is no corpus to gate; any partially loaded corpus still
    # fails the exact-count checks below.
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
