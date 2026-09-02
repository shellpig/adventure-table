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

ALLOWED_FEAT_AUTOMATION = frozenset(
    {
        "full",
        "static_derived",
        "deferred_roll",
        "deferred_combat",
        "deferred_reaction",
        "deferred_rest",
        "deferred_equipment_conditional",
    }
)
ALLOWED_STATIC_MODIFIER_TARGETS = frozenset(
    {"max_hp", "passive_perception", "passive_investigation"}
)
ALLOWED_RESOURCE_RECHARGE = frozenset({"short_rest", "long_rest"})
ALLOWED_RESOURCE_STACKING = frozenset({"separate", "aggregate-superiority-dice"})


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


def _verify_feat_choice_shape(key: str, raw: object) -> None:
    if not isinstance(raw, list):
        raise AssertionError(f"{key}: choices must be an array")
    ids: list[str] = []
    for index, choice in enumerate(raw):
        if not isinstance(choice, dict):
            raise AssertionError(f"{key}: choice {index} must be an object")
        choice_id = choice.get("id")
        kind = choice.get("kind")
        choose = choice.get("choose", 1)
        _require_nonblank(choice_id, f"choice {index} id", key)
        _require_nonblank(kind, f"choice {index} kind", key)
        if not isinstance(choose, int) or isinstance(choose, bool) or choose < 1:
            raise AssertionError(f"{key}: choice {choice_id} has invalid choose count")
        if "distinct" in choice and not isinstance(choice["distinct"], bool):
            raise AssertionError(f"{key}: choice {choice_id} distinct must be boolean")
        if "distinct_across_acquisitions" in choice and not isinstance(
            choice["distinct_across_acquisitions"], bool
        ):
            raise AssertionError(
                f"{key}: choice {choice_id} distinct_across_acquisitions must be boolean"
            )
        if "attack_roll" in choice and not isinstance(choice["attack_roll"], bool):
            raise AssertionError(f"{key}: choice {choice_id} attack_roll must be boolean")
        ids.append(str(choice_id))
    if len(ids) != len(set(ids)):
        raise AssertionError(f"{key}: duplicate feat choice ids")


def _verify_feat_resource(key: str, raw: object) -> None:
    if not isinstance(raw, dict):
        raise AssertionError(f"{key}: resource must be an object")
    _require_nonblank(raw.get("resource_id"), "resource_id", key)
    capacity = raw.get("capacity")
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
        raise AssertionError(f"{key}: invalid resource capacity")
    die_size = raw.get("die_size")
    if die_size is not None and (
        not isinstance(die_size, int) or isinstance(die_size, bool) or die_size < 2
    ):
        raise AssertionError(f"{key}: invalid resource die_size")
    recharge = raw.get("recharge", [])
    if (
        not isinstance(recharge, list)
        or len(recharge) != len(set(recharge))
        or any(item not in ALLOWED_RESOURCE_RECHARGE for item in recharge)
    ):
        raise AssertionError(f"{key}: invalid resource recharge metadata")
    stacking = raw.get("stacking", "separate")
    if stacking not in ALLOWED_RESOURCE_STACKING:
        raise AssertionError(f"{key}: invalid resource stacking metadata")


def _verify_static_modifiers(key: str, raw: object) -> None:
    if not isinstance(raw, list) or not raw:
        raise AssertionError(f"{key}: static_modifiers must be a non-empty array")
    for index, modifier in enumerate(raw):
        if not isinstance(modifier, dict):
            raise AssertionError(f"{key}: static modifier {index} must be an object")
        if modifier.get("target") not in ALLOWED_STATIC_MODIFIER_TARGETS:
            raise AssertionError(f"{key}: static modifier {index} has unsupported target")
        value = modifier.get("value")
        if not isinstance(value, int) or isinstance(value, bool):
            raise AssertionError(f"{key}: static modifier {index} value must be an integer")
        if not isinstance(modifier.get("per_level", False), bool):
            raise AssertionError(f"{key}: static modifier {index} per_level must be boolean")


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
    automation = data.get("automation")
    _require_nonblank(automation, "automation classification", key)
    if automation not in ALLOWED_FEAT_AUTOMATION:
        raise AssertionError(f"{key}: unsupported automation classification {automation!r}")
    if "choices" in data:
        _verify_feat_choice_shape(key, data["choices"])
    if "resource" in data:
        _verify_feat_resource(key, data["resource"])
    if "static_modifiers" in data:
        _verify_static_modifiers(key, data["static_modifiers"])
    if automation == "static_derived" and "static_modifiers" not in data:
        raise AssertionError(f"{key}: static_derived feat requires static_modifiers")
    provenance = entry.get("provenance")
    if not isinstance(provenance, dict):
        raise AssertionError(f"{key}: missing provenance")
    _require_nonblank(provenance.get("rules_source"), "rules_source provenance", key)
    _require_nonblank(provenance.get("reference_doc"), "reference_doc provenance", key)


def _choice_by_id(data: dict[str, Any], choice_id: str) -> dict[str, Any]:
    choices = data.get("choices")
    if not isinstance(choices, list):
        raise AssertionError(f"missing choices while looking for {choice_id}")
    for choice in choices:
        if isinstance(choice, dict) and choice.get("id") == choice_id:
            return choice
    raise AssertionError(f"missing feat choice {choice_id}")


def _verify_representative_feat_contracts(entries: list[dict[str, Any]]) -> None:
    by_key = {str(entry.get("key", "")): entry for entry in entries}

    elemental = by_key["phb2014:feat:elemental-adept"]["data"]
    if elemental.get("repeatable") is not True:
        raise AssertionError("Elemental Adept must remain repeatable")
    elemental_choice = _choice_by_id(elemental, "element")
    if elemental_choice.get("distinct_across_acquisitions") is not True:
        raise AssertionError("Elemental Adept repeated damage type must remain distinct")

    lucky = by_key["phb2014:feat:lucky"]["data"]
    lucky_resource = lucky.get("resource")
    if not isinstance(lucky_resource, dict) or lucky_resource.get("capacity") != 3:
        raise AssertionError("Lucky must materialize three luck points")
    if lucky_resource.get("recharge") != ["long_rest"]:
        raise AssertionError("Lucky luck points must recharge on long rest")

    martial = by_key["phb2014:feat:martial-adept"]["data"]
    maneuvers = _choice_by_id(martial, "maneuvers")
    if maneuvers.get("choose") != 2 or maneuvers.get("distinct") is not True:
        raise AssertionError("Martial Adept must choose two distinct maneuvers")
    martial_resource = martial.get("resource")
    if not isinstance(martial_resource, dict):
        raise AssertionError("Martial Adept must materialize superiority-die resource metadata")
    if (
        martial_resource.get("capacity") != 1
        or martial_resource.get("die_size") != 6
        or martial_resource.get("stacking") != "aggregate-superiority-dice"
        or set(martial_resource.get("recharge", [])) != {"short_rest", "long_rest"}
    ):
        raise AssertionError("Martial Adept superiority-die contract changed")

    tough = by_key["phb2014:feat:tough"]["data"]
    tough_modifiers = tough.get("static_modifiers")
    if tough_modifiers != [{"target": "max_hp", "value": 2, "per_level": True}]:
        raise AssertionError("Tough must remain +2 max HP per character level")

    observant = by_key["phb2014:feat:observant"]["data"]
    observant_modifiers = observant.get("static_modifiers")
    expected_observant = {
        ("passive_perception", 5, False),
        ("passive_investigation", 5, False),
    }
    actual_observant = {
        (row.get("target"), row.get("value"), row.get("per_level", False))
        for row in observant_modifiers
        if isinstance(row, dict)
    } if isinstance(observant_modifiers, list) else set()
    if actual_observant != expected_observant:
        raise AssertionError("Observant passive-score static modifiers changed")

    spell_sniper = by_key["phb2014:feat:spell-sniper"]["data"]
    sniper_cantrip = _choice_by_id(spell_sniper, "cantrip")
    if sniper_cantrip.get("level") != 0 or sniper_cantrip.get("attack_roll") is not True:
        raise AssertionError("Spell Sniper must remain limited to attack-roll cantrips")


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
    if (
        not isinstance(components, list)
        or not components
        or len(components) != len(set(components))
        or not all(component in {"V", "S", "M"} for component in components)
    ):
        raise AssertionError(f"{key}: invalid components")
    if "M" in components:
        _require_nonblank(data.get("material"), "material component metadata", key)
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
    _verify_representative_feat_contracts(feats)
    for entry in spells:
        _verify_spell(entry)
    print("M01-K catalog verified: 41 PHB non-SRD feats, 42 PHB non-SRD spells")


if __name__ == "__main__":
    verify()
