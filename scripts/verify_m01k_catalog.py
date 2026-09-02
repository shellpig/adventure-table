from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PHB_ROOT = ROOT / "data" / "phb2014"
SRD_ROOT = ROOT / "data" / "srd5.1"

EXPECTED_FEATS = frozenset(
    f"phb2014:feat:{index}"
    for index in (
        "actor",
        "alert",
        "athlete",
        "charger",
        "crossbow-expert",
        "defensive-duelist",
        "dual-wielder",
        "dungeon-delver",
        "durable",
        "elemental-adept",
        "great-weapon-master",
        "healer",
        "heavily-armored",
        "heavy-armor-master",
        "inspiring-leader",
        "keen-mind",
        "lightly-armored",
        "linguist",
        "lucky",
        "mage-slayer",
        "magic-initiate",
        "martial-adept",
        "medium-armor-master",
        "mobile",
        "moderately-armored",
        "mounted-combatant",
        "observant",
        "polearm-master",
        "resilient",
        "ritual-caster",
        "savage-attacker",
        "sentinel",
        "sharpshooter",
        "shield-master",
        "skilled",
        "skulker",
        "spell-sniper",
        "tavern-brawler",
        "tough",
        "war-caster",
        "weapon-master",
    )
)

EXPECTED_SPELLS = frozenset(
    f"phb2014:spell:{index}"
    for index in (
        "blade-ward",
        "friends",
        "thorn-whip",
        "armor-of-agathys",
        "arms-of-hadar",
        "chromatic-orb",
        "compelled-duel",
        "dissonant-whispers",
        "ensnaring-strike",
        "hail-of-thorns",
        "hex",
        "ray-of-sickness",
        "searing-smite",
        "thunderous-smite",
        "witch-bolt",
        "wrathful-smite",
        "beast-sense",
        "cloud-of-daggers",
        "cordon-of-arrows",
        "crown-of-madness",
        "phantasmal-force",
        "aura-of-vitality",
        "blinding-smite",
        "conjure-barrage",
        "crusaders-mantle",
        "elemental-weapon",
        "feign-death",
        "hunger-of-hadar",
        "lightning-arrow",
        "aura-of-life",
        "aura-of-purity",
        "grasping-vine",
        "staggering-smite",
        "banishing-smite",
        "circle-of-power",
        "conjure-volley",
        "destructive-wave",
        "swift-quiver",
        "arcane-gate",
        "telepathy",
        "tsunami",
        "power-word-heal",
    )
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_entries(kind: str) -> list[dict[str, Any]]:
    manifest = _load_json(PHB_ROOT / "manifest.json")
    result: list[dict[str, Any]] = []
    for category in manifest["categories"]:
        if category["kind"] != kind:
            continue
        path = PHB_ROOT / category["file"]
        payload = _load_json(path)
        if not isinstance(payload, list):
            raise AssertionError(f"{path}: manifest category must contain an array")
        if len(payload) != category["count"]:
            raise AssertionError(
                f"{path}: manifest count={category['count']} but file count={len(payload)}"
            )
        result.extend(payload)
    return result


def _require_nonblank(value: object, label: str, key: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AssertionError(f"{key}: missing {label}")


def _verify_unique_exact(entries: list[dict[str, Any]], expected: frozenset[str], kind: str) -> None:
    keys = [str(entry.get("key", "")) for entry in entries]
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicates:
        raise AssertionError(f"duplicate {kind} StableKeys: {duplicates}")
    actual = set(keys)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise AssertionError(
            f"M01-K {kind} inventory mismatch; missing={missing}, unexpected={unexpected}"
        )


def _verify_feat(entry: dict[str, Any]) -> None:
    key = str(entry.get("key", ""))
    data = entry.get("data")
    if not isinstance(data, dict):
        raise AssertionError(f"{key}: missing feat data")
    desc = data.get("desc")
    if not isinstance(desc, list) or not desc or not all(isinstance(row, str) and row.strip() for row in desc):
        raise AssertionError(f"{key}: missing rules description")
    if not isinstance(data.get("prerequisites"), list):
        raise AssertionError(f"{key}: prerequisites must be explicit")
    if not isinstance(data.get("repeatable"), bool):
        raise AssertionError(f"{key}: repeatable must be explicit")
    _require_nonblank(data.get("automation"), "automation classification", key)
    provenance = entry.get("provenance")
    if not isinstance(provenance, dict):
        raise AssertionError(f"{key}: missing provenance")
    _require_nonblank(provenance.get("rules_source"), "rules_source provenance", key)
    _require_nonblank(provenance.get("reference_doc"), "reference_doc provenance", key)


def _verify_spell(entry: dict[str, Any]) -> None:
    key = str(entry.get("key", ""))
    data = entry.get("data")
    if not isinstance(data, dict):
        raise AssertionError(f"{key}: missing spell data")
    level = data.get("level")
    if not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 9:
        raise AssertionError(f"{key}: invalid spell level")
    school = data.get("school")
    if not isinstance(school, dict) or not isinstance(school.get("key"), str):
        raise AssertionError(f"{key}: missing canonical school")
    _require_nonblank(data.get("casting_time"), "casting_time", key)
    _require_nonblank(data.get("range"), "range", key)
    _require_nonblank(data.get("duration"), "duration", key)
    components = data.get("components")
    if not isinstance(components, list) or not all(component in {"V", "S", "M"} for component in components):
        raise AssertionError(f"{key}: invalid components")
    if not isinstance(data.get("ritual"), bool):
        raise AssertionError(f"{key}: ritual must be explicit")
    if not isinstance(data.get("concentration"), bool):
        raise AssertionError(f"{key}: concentration must be explicit")
    classes = data.get("classes")
    if not isinstance(classes, list) or not classes:
        raise AssertionError(f"{key}: PHB class access must be explicit")
    desc = data.get("desc")
    if not isinstance(desc, list) or not desc or not all(isinstance(row, str) and row.strip() for row in desc):
        raise AssertionError(f"{key}: missing rules description")
    provenance = entry.get("provenance")
    if not isinstance(provenance, dict):
        raise AssertionError(f"{key}: missing provenance")
    _require_nonblank(provenance.get("rules_source"), "rules_source provenance", key)
    _require_nonblank(provenance.get("reference_doc"), "reference_doc provenance", key)


def _verify_srd_grappler_contract() -> None:
    entries = _load_json(SRD_ROOT / "feats.json")
    if not isinstance(entries, list):
        raise AssertionError("data/srd5.1/feats.json must contain an array")
    keys = {str(entry.get("key", "")) for entry in entries if isinstance(entry, dict)}
    if "srd5.1:feat:grappler" not in keys:
        raise AssertionError("SRD Grappler is required for the PHB 42 = SRD 1 + M01-K 41 contract")


def verify() -> None:
    feats = _manifest_entries("feat")
    spells = _manifest_entries("spell")
    _verify_unique_exact(feats, EXPECTED_FEATS, "feat")
    _verify_unique_exact(spells, EXPECTED_SPELLS, "spell")
    if len(EXPECTED_FEATS) != 41:
        raise AssertionError("M01-K expected feat inventory must remain exactly 41")
    if len(EXPECTED_SPELLS) != 42:
        raise AssertionError("M01-K expected spell inventory must remain exactly 42")
    _verify_srd_grappler_contract()
    for entry in feats:
        _verify_feat(entry)
    for entry in spells:
        _verify_spell(entry)
    print("M01-K catalog verified: 41 PHB non-SRD feats, 42 PHB non-SRD spells")


if __name__ == "__main__":
    verify()
