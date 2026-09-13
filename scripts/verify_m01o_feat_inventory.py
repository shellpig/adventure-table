from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SERVER_ROOT = ROOT / "apps" / "server"
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.content import load_default_content_registry  # noqa: E402
from app.content.localization_files import load_content_localization_catalog  # noqa: E402
from app.paths import resolve_content_root  # noqa: E402


EXPECTED = {
    "xge": {
        "bountiful-luck",
        "dragon-fear",
        "dragon-hide",
        "drow-high-magic",
        "dwarven-fortitude",
        "elven-accuracy",
        "fade-away",
        "fey-teleportation",
        "flames-of-phlegethos",
        "infernal-constitution",
        "orcish-fury",
        "prodigy",
        "second-chance",
        "squat-nimbleness",
        "wood-elf-magic",
    },
    "tce": {
        "artificer-initiate",
        "chef",
        "crusher",
        "eldritch-adept",
        "fey-touched",
        "fighting-initiate",
        "gunner",
        "metamagic-adept",
        "piercer",
        "poisoner",
        "shadow-touched",
        "skill-expert",
        "slasher",
        "telekinetic",
        "telepathic",
    },
}

ALLOWED_PREREQUISITES = {
    "ability",
    "any_of",
    "armor_proficiency",
    "ancestry",
    "feature",
    "lineage",
    "proficiency",
    "size",
    "spellcasting",
}
ALLOWED_AUTOMATION = {
    "full_structural",
    "static_derived",
    "structured_deferred_roll",
    "structured_deferred_reaction",
    "structured_deferred_combat",
    "structured_deferred_rest",
    "structured_deferred_inventory",
}
ALLOWED_CHOICE_KINDS = {
    "ability",
    "artisan_tool",
    "expertise",
    "fighting_style",
    "invocation",
    "language",
    "metamagic",
    "skill",
    "spell",
    "tool",
}
REFERENCE_DOC = "docs/暫用規則資訊/專長_TCE_XGE.md"


def _manifest_category(source: str) -> dict[str, Any]:
    manifest = json.loads((ROOT / "data" / source / "manifest.json").read_text(encoding="utf-8"))
    matches = [
        category
        for category in manifest["categories"]
        if category["name"] == "feats-m01o"
        and category["kind"] == "feat"
        and category["file"] == "feats-m01o.json"
    ]
    if len(matches) != 1:
        raise AssertionError(f"{source}: expected one feats-m01o manifest category")
    if sum(category["count"] for category in manifest["categories"]) != manifest["total_entries"]:
        raise AssertionError(f"{source}: manifest total_entries is out of sync")
    return matches[0]


def _m01o_entries(source: str) -> list[dict[str, Any]]:
    path = ROOT / "data" / source / "feats-m01o.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise AssertionError(f"{path}: expected JSON array")
    category = _manifest_category(source)
    if category["count"] != len(payload):
        raise AssertionError(f"{source}: manifest count {category['count']} != file count {len(payload)}")
    return payload


def _require_key(registry, key: object, *, kind: str | None = None, owner: str) -> str:
    if not isinstance(key, str) or not key:
        raise AssertionError(f"{owner}: expected non-empty StableKey")
    entry = registry.get_optional(key)
    if entry is None:
        raise AssertionError(f"{owner}: dangling ref {key}")
    if kind is not None and f":{kind}:" not in key:
        raise AssertionError(f"{owner}: expected {kind} ref, got {key}")
    return key


def _verify_prerequisite(owner: str, requirement: Any) -> None:
    if not isinstance(requirement, dict):
        raise AssertionError(f"{owner}: prerequisite must be an object")
    req_type = requirement.get("type")
    if req_type not in ALLOWED_PREREQUISITES:
        raise AssertionError(f"{owner}: unsupported prerequisite type {req_type!r}")
    if req_type == "any_of":
        options = requirement.get("options")
        if not isinstance(options, list) or not options:
            raise AssertionError(f"{owner}: any_of must contain options")
        for option in options:
            _verify_prerequisite(owner, option)


def _verify_choice(owner: str, choice: Any, registry) -> None:
    if not isinstance(choice, dict):
        raise AssertionError(f"{owner}: choice must be an object")
    choice_id = choice.get("id")
    kind = choice.get("kind")
    choose = choice.get("choose", 1)
    if not isinstance(choice_id, str) or not choice_id:
        raise AssertionError(f"{owner}: choice missing id")
    if kind not in ALLOWED_CHOICE_KINDS:
        raise AssertionError(f"{owner}: unsupported choice kind {kind!r}")
    if not isinstance(choose, int) or isinstance(choose, bool) or choose < 1:
        raise AssertionError(f"{owner}: invalid choose count for {choice_id}")
    for ref in choice.get("allowed_refs", ()):
        _require_key(registry, ref, owner=owner)
    source_class_ref = choice.get("source_class_ref")
    if source_class_ref is not None:
        _require_key(registry, source_class_ref, kind="class", owner=owner)
    if kind == "spell":
        # The selector must resolve at least one canonical spell at runtime.
        level = choice.get("level")
        schools = set(choice.get("schools", ()))
        candidates = []
        for spell in registry.list_kind("spell"):
            if isinstance(level, int) and spell.data.get("level") != level:
                continue
            if schools:
                school = spell.data.get("school")
                school_index = school.get("index") if isinstance(school, dict) else None
                if school_index not in schools:
                    continue
            candidates.append(spell.key)
        if not candidates:
            raise AssertionError(f"{owner}: spell choice {choice_id} resolves no spell candidates")


def _verify_entry(entry: dict[str, Any], registry, catalog) -> None:
    key = entry.get("key")
    source = entry.get("source")
    index = entry.get("index")
    owner = str(key)
    expected_key = f"{source}:feat:{index}"
    if key != expected_key:
        raise AssertionError(f"{owner}: key/source/index mismatch; expected {expected_key}")
    if source not in EXPECTED:
        raise AssertionError(f"{owner}: wrong source pack {source!r}")
    provenance = entry.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("reference_doc") != REFERENCE_DOC:
        raise AssertionError(f"{owner}: wrong M01-O provenance")
    data = entry.get("data")
    if not isinstance(data, dict):
        raise AssertionError(f"{owner}: missing data")
    if data.get("automation") not in ALLOWED_AUTOMATION:
        raise AssertionError(f"{owner}: invalid automation {data.get('automation')!r}")
    prerequisites = data.get("prerequisites")
    if not isinstance(prerequisites, list):
        raise AssertionError(f"{owner}: prerequisites must be explicit array")
    for requirement in prerequisites:
        _verify_prerequisite(owner, requirement)
    if "choices" in data:
        choice_ids = [choice.get("id") for choice in data["choices"] if isinstance(choice, dict)]
        if len(choice_ids) != len(set(choice_ids)):
            raise AssertionError(f"{owner}: duplicate choice ids")
        for choice in data["choices"]:
            _verify_choice(owner, choice, registry)
    for spell in data.get("spell_grants", ()):
        if not isinstance(spell, dict):
            raise AssertionError(f"{owner}: spell grant must be an object")
        _require_key(registry, spell.get("spell_ref"), kind="spell", owner=owner)
    for ref in data.get("language_grants", ()):
        _require_key(registry, ref, kind="language", owner=owner)
    for ref in data.get("proficiency_grants", ()):
        _require_key(registry, ref, kind="proficiency", owner=owner)
    for ref in data.get("feature_grants", ()):
        _require_key(registry, ref, kind="feature", owner=owner)
    for locale in ("en", "zh-TW"):
        name = catalog.resolve_name(owner, locale)
        desc = catalog.resolve_field(owner, "data.desc.0", locale)
        if not name.value or not desc.value:
            raise AssertionError(f"{owner}: missing {locale} name/description")
        # A missing overlay silently falls back to the canonical English text, so a
        # non-empty value alone would make the zh-TW check vacuous.
        if name.fallback_used or desc.fallback_used:
            raise AssertionError(f"{owner}: {locale} name/description falls back to another locale")


def main() -> int:
    registry = load_default_content_registry()
    catalog = load_content_localization_catalog(registry, resolve_content_root())
    entries = {source: _m01o_entries(source) for source in EXPECTED}
    all_keys = [entry["key"] for source_entries in entries.values() for entry in source_entries]
    duplicates = [key for key, count in Counter(all_keys).items() if count > 1]
    if duplicates:
        raise AssertionError(f"duplicate M01-O StableKeys: {duplicates}")
    for source, source_entries in entries.items():
        actual = {str(entry.get("index")) for entry in source_entries}
        if actual != EXPECTED[source]:
            raise AssertionError(f"{source}: missing={sorted(EXPECTED[source] - actual)}, unexpected={sorted(actual - EXPECTED[source])}")
        for entry in source_entries:
            _verify_entry(entry, registry, catalog)
    total = sum(len(source_entries) for source_entries in entries.values())
    if total != 30:
        raise AssertionError(f"M01-O total expected 30, got {total}")
    print("M01-O feat inventory verified: XGE 15 / TCE 15 / total 30")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
