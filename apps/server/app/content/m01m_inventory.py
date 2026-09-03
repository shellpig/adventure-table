from __future__ import annotations

from functools import lru_cache
import json

from app.content.identity import parse_stable_key, reference_to_stable_key
from app.content.registry import CONTENT_PACKS_ROOT, ContentRegistry, ContentValidationError


INVENTORY_PATH = (
    CONTENT_PACKS_ROOT / "rules" / "dnd5e-2014" / "m01m-race-inventory.json"
)


@lru_cache(maxsize=1)
def _inventory() -> dict[str, object]:
    try:
        payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentValidationError(f"cannot read M01-M race inventory: {exc}") from exc
    if payload.get("phase") != "M01-M" or payload.get("ruleset") != "dnd5e-2014":
        raise ContentValidationError("M01-M race inventory has wrong phase/ruleset")
    return payload


def _parent_race_ref(entry: object) -> str | None:
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


def _variant_base_race_ref(entry: object) -> str | None:
    data = getattr(entry, "data", None)
    if not isinstance(data, dict):
        return None
    reference = data.get("base_race_ref")
    if not isinstance(reference, dict):
        return None
    try:
        return reference_to_stable_key(reference, kinds={"race"})
    except ValueError:
        return None


def validate_m01m_inventory(registry: ContentRegistry) -> ContentRegistry:
    """Fail default loading if the exact M01-M ancestry identity contract drifts."""

    payload = _inventory()
    planar_rows = payload.get("planar_rows")
    bloodlines = payload.get("tiefling_bloodlines")
    dependencies = payload.get("required_dependencies")
    scag_variant_key = payload.get("scag_tiefling_variant_key")
    if not isinstance(planar_rows, list) or len(planar_rows) != 7:
        raise ContentValidationError("M01-M inventory must contain exactly 7 planar rows")
    if not isinstance(bloodlines, list) or len(bloodlines) != 9:
        raise ContentValidationError("M01-M inventory must account for exactly 9 Tiefling bloodlines")
    if not isinstance(dependencies, list) or not isinstance(scag_variant_key, str):
        raise ContentValidationError("M01-M inventory dependency metadata is malformed")

    expected_mtf_races: set[str] = set()
    expected_mtf_subraces: set[str] = set()
    seen_planar_keys: set[str] = set()
    for row in planar_rows:
        if not isinstance(row, dict):
            raise ContentValidationError("M01-M planar inventory row must be an object")
        try:
            source = str(row["source"])
            kind = str(row["kind"])
            key = str(row["key"])
            name = str(row["name"])
            parent = row.get("parent_race_ref")
        except KeyError as exc:
            raise ContentValidationError(f"M01-M planar inventory row is missing {exc}") from exc
        if key in seen_planar_keys:
            raise ContentValidationError(f"M01-M duplicate planar inventory key: {key}")
        seen_planar_keys.add(key)
        parsed = parse_stable_key(key)
        if parsed.source != source or parsed.kind != kind or source != "mtf":
            raise ContentValidationError(f"M01-M planar inventory identity mismatch: {key}")
        entry = registry.get_optional(key)
        if entry is None or entry.name != name:
            raise ContentValidationError(f"M01-M planar runtime entry is missing or renamed: {key}")
        if kind == "race":
            if parent is not None:
                raise ContentValidationError(f"M01-M parent race cannot itself have a parent: {key}")
            expected_mtf_races.add(key)
        elif kind == "subrace":
            if not isinstance(parent, str) or _parent_race_ref(entry) != parent:
                raise ContentValidationError(f"M01-M subrace parent mismatch: {key}")
            expected_mtf_subraces.add(key)
        else:
            raise ContentValidationError(f"M01-M unsupported planar inventory kind: {kind}")

    if {entry.key for entry in registry.list_kind("race", source="mtf")} != expected_mtf_races:
        raise ContentValidationError("M01-M MTF race inventory drift")
    if {entry.key for entry in registry.list_kind("subrace", source="mtf")} != expected_mtf_subraces:
        raise ContentValidationError("M01-M MTF subrace inventory drift")

    expected_variants: set[str] = set()
    canonical_count = 0
    names: set[str] = set()
    for row in bloodlines:
        if not isinstance(row, dict):
            raise ContentValidationError("M01-M Tiefling inventory row must be an object")
        name = row.get("name")
        disposition = row.get("disposition")
        key = row.get("key")
        if not isinstance(name, str) or not isinstance(disposition, str) or not isinstance(key, str):
            raise ContentValidationError("M01-M Tiefling inventory row is malformed")
        if name in names:
            raise ContentValidationError(f"M01-M duplicate Tiefling bloodline name: {name}")
        names.add(name)
        entry = registry.get_optional(key)
        if entry is None:
            raise ContentValidationError(f"M01-M Tiefling identity is missing: {key}")
        if disposition == "canonical_mapping":
            canonical_count += 1
            if name != "Asmodeus" or key != "srd5.1:race:tiefling":
                raise ContentValidationError("M01-M Asmodeus must map to the existing SRD Tiefling")
        elif disposition == "implemented_variant":
            parsed = parse_stable_key(key)
            if parsed.source != "mtf" or parsed.kind != "race-variant":
                raise ContentValidationError(f"M01-M bloodline is not an MTF race variant: {key}")
            if _variant_base_race_ref(entry) != "srd5.1:race:tiefling":
                raise ContentValidationError(f"M01-M bloodline has wrong base race: {key}")
            expected_variants.add(key)
        else:
            raise ContentValidationError(f"M01-M unknown Tiefling disposition: {disposition}")
    if canonical_count != 1 or len(expected_variants) != 8:
        raise ContentValidationError("M01-M Tiefling accounting must be 1 canonical + 8 variants")
    if {entry.key for entry in registry.list_kind("race-variant", source="mtf")} != expected_variants:
        raise ContentValidationError("M01-M MTF Tiefling variant inventory drift")
    if any("asmodeus" in key for key in expected_variants):
        raise ContentValidationError("M01-M must not create a duplicate Asmodeus variant identity")

    scag_variant = registry.get_optional(scag_variant_key)
    if scag_variant is None or _variant_base_race_ref(scag_variant) != "srd5.1:race:tiefling":
        raise ContentValidationError("M01-M SCAG Tiefling composite variant is missing or mis-parented")

    for dependency in dependencies:
        if not isinstance(dependency, str) or registry.get_optional(dependency) is None:
            raise ContentValidationError(f"M01-M required content dependency is missing: {dependency}")
    return registry
