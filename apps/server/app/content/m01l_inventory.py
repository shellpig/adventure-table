from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.registry import ContentRegistry, ContentValidationError
from app.paths import resolve_rules_root


@dataclass(frozen=True)
class M01LInventoryRow:
    source: str
    kind: str
    key: str
    name: str
    parent_race_ref: str | None
    disposition: str


@dataclass(frozen=True)
class M01LInventory:
    rows: tuple[M01LInventoryRow, ...]
    legacy_vgm_race_keys: tuple[str, ...]
    required_dependencies: tuple[str, ...]


@lru_cache(maxsize=8)
def _load_m01l_reference_inventory(path: Path) -> M01LInventory:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentValidationError(f"cannot read M01-L race inventory: {exc}") from exc

    if payload.get("phase") != "M01-L" or payload.get("ruleset") != "dnd5e-2014":
        raise ContentValidationError("M01-L race inventory has wrong phase/ruleset")
    rows = payload.get("rows")
    legacy = payload.get("legacy_vgm_race_keys")
    dependencies = payload.get("required_dependencies")
    if not isinstance(rows, list) or not rows:
        raise ContentValidationError("M01-L race inventory must contain rows")
    if not isinstance(legacy, list) or not isinstance(dependencies, list):
        raise ContentValidationError("M01-L race inventory dependency lists are malformed")

    try:
        parsed_rows = tuple(
            M01LInventoryRow(
                source=str(row["source"]),
                kind=str(row["kind"]),
                key=str(row["key"]),
                name=str(row["name"]),
                parent_race_ref=(
                    str(row["parent_race_ref"])
                    if row.get("parent_race_ref") is not None
                    else None
                ),
                disposition=str(row["disposition"]),
            )
            for row in rows
        )
    except (KeyError, TypeError) as exc:
        raise ContentValidationError(f"invalid M01-L race inventory row: {exc}") from exc
    return M01LInventory(
        rows=parsed_rows,
        legacy_vgm_race_keys=tuple(str(value) for value in legacy),
        required_dependencies=tuple(str(value) for value in dependencies),
    )


def m01l_reference_inventory() -> M01LInventory:
    path = (resolve_rules_root() / "m01l-race-inventory.json").resolve()
    return _load_m01l_reference_inventory(path)


m01l_reference_inventory.cache_clear = _load_m01l_reference_inventory.cache_clear  # type: ignore[attr-defined]


def _subrace_parent_ref(entry: object) -> str | None:
    data = getattr(entry, "data", None)
    if not isinstance(data, dict):
        return None
    reference = data.get("race")
    if not isinstance(reference, dict):
        return None
    try:
        return reference_to_stable_key(reference, kinds={"race"})
    except ValueError:
        return None


def validate_m01l_inventory(registry: ContentRegistry) -> ContentRegistry:
    """Fail default content loading if the M01-L 10+2 identity set drifts."""

    inventory = m01l_reference_inventory()
    if len(inventory.rows) != 12:
        raise ContentValidationError(
            f"M01-L expected exactly 12 inventory rows, got {len(inventory.rows)}"
        )
    row_keys = [row.key for row in inventory.rows]
    if len(row_keys) != len(set(row_keys)):
        raise ContentValidationError("M01-L race inventory contains duplicate keys")

    vgm_new_races: set[str] = set()
    scag_subraces: set[str] = set()
    for row in inventory.rows:
        if row.disposition != "implemented":
            raise ContentValidationError(
                f"M01-L incomplete inventory disposition for {row.key}: {row.disposition}"
            )
        parsed = parse_stable_key(row.key)
        if parsed.source != row.source or parsed.kind != row.kind:
            raise ContentValidationError(f"M01-L inventory identity mismatch: {row.key}")
        entry = registry.get_optional(row.key)
        if entry is None:
            raise ContentValidationError(f"M01-L runtime entry is missing: {row.key}")
        if entry.name != row.name:
            raise ContentValidationError(
                f"M01-L inventory name mismatch for {row.key}: {entry.name!r} != {row.name!r}"
            )

        if row.kind == "race":
            if row.source != "vgm" or row.parent_race_ref is not None:
                raise ContentValidationError(f"M01-L invalid race inventory row: {row.key}")
            vgm_new_races.add(row.key)
        elif row.kind == "subrace":
            if row.source != "scag" or row.parent_race_ref is None:
                raise ContentValidationError(f"M01-L invalid subrace inventory row: {row.key}")
            if _subrace_parent_ref(entry) != row.parent_race_ref:
                raise ContentValidationError(f"M01-L subrace parent mismatch: {row.key}")
            scag_subraces.add(row.key)
        else:
            raise ContentValidationError(f"M01-L unsupported inventory kind: {row.kind}")

    expected_vgm_races = set(inventory.legacy_vgm_race_keys) | vgm_new_races
    actual_vgm_races = {
        entry.key for entry in registry.list_kind("race", source="vgm")
    }
    if actual_vgm_races != expected_vgm_races:
        raise ContentValidationError(
            "M01-L VGM race inventory drift: "
            f"missing={sorted(expected_vgm_races - actual_vgm_races)}, "
            f"extra={sorted(actual_vgm_races - expected_vgm_races)}"
        )

    actual_scag_subraces = {
        entry.key for entry in registry.list_kind("subrace", source="scag")
    }
    if actual_scag_subraces != scag_subraces:
        raise ContentValidationError(
            "M01-L SCAG subrace inventory drift: "
            f"missing={sorted(scag_subraces - actual_scag_subraces)}, "
            f"extra={sorted(actual_scag_subraces - scag_subraces)}"
        )

    for dependency in inventory.required_dependencies:
        if registry.get_optional(dependency) is None:
            raise ContentValidationError(
                f"M01-L required content dependency is missing: {dependency}"
            )
    return registry
