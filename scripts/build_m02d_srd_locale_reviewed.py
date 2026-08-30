"""Finish the M02-D SRD zh-TW overlay with reviewed external-name references.

The base generator remains the source of project terminology and deterministic
compositional translations. This authoring-only pass may consume a checkout of
an explicitly pinned Traditional Chinese community reference to improve whole
visible names by exact English-name matches. Runtime never reads the reference
checkout; it only reads the committed data/srd5.1/locales/zh-TW.json.

Translation priority for names is deliberately strict:
1. project-owned StableKey/exact glossary entries;
2. structural name rules whose ordinal carries meaning;
3. unambiguous whole-name matches from the pinned Traditional Chinese reference;
4. reviewed deterministic token composition as the final fallback.

The reviewed pass also closes policy-visible short-name kinds not covered by the
older base generator. This keeps completeness driven by localizable-fields.json
rather than by a hand-maintained UI list.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import unicodedata
from typing import Any

import build_m02d_srd_locale as base

HAN_RE = re.compile(r"[\u3400-\u9fff]")
UNTRANSLATED_RE = re.compile(r"〔未譯:([^〕]+)〕")
ASCII_SUFFIX_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9 A-Za-z'’/().,:+\-×&]*[A-Za-z0-9)])\s*$"
)
SPELL_SCROLL_KEY_RE = re.compile(r"^srd5\.1:item:spell-scroll-(\d+)(?:st|nd|rd|th)$")
MYSTIC_ARCANUM_KEY_RE = re.compile(
    r"^srd5\.1:feature:mystic-arcanum-(\d+)(?:st|nd|rd|th)-level$"
)

ADDITIONAL_SHORT_NAME_KIND_FILES: dict[str, str] = {
    "damage-type": "damage-types.json",
    "equipment-category": "equipment-categories.json",
}
ALL_KIND_FILES = {**base.CATEGORY_BY_KIND, **ADDITIONAL_SHORT_NAME_KIND_FILES}

# Canonical English labels are not globally unique, and some short names need a
# reviewed term rather than word composition. StableKey-specific translations
# are the authoritative project terminology for those cases.
PROJECT_EXACT_BY_KEY: dict[str, str] = {
    "srd5.1:race:halfling": "半身人",
    "srd5.1:language:halfling": "半身人語",
    "srd5.1:subclass:draconic": "龍族血脈",
    "srd5.1:language:draconic": "龍語",
    # Damage types currently visible in Inventory short rule summaries.
    "srd5.1:damage-type:acid": "強酸",
    "srd5.1:damage-type:bludgeoning": "鈍擊",
    "srd5.1:damage-type:cold": "寒冷",
    "srd5.1:damage-type:fire": "火焰",
    "srd5.1:damage-type:force": "力場",
    "srd5.1:damage-type:lightning": "閃電",
    "srd5.1:damage-type:necrotic": "黯蝕",
    "srd5.1:damage-type:piercing": "穿刺",
    "srd5.1:damage-type:poison": "毒素",
    "srd5.1:damage-type:psychic": "心靈",
    "srd5.1:damage-type:radiant": "光耀",
    "srd5.1:damage-type:slashing": "揮砍",
    "srd5.1:damage-type:thunder": "雷鳴",
    # Equipment categories currently visible in Inventory selectors/summaries.
    "srd5.1:equipment-category:weapon": "武器",
    "srd5.1:equipment-category:armor": "護甲",
    "srd5.1:equipment-category:adventuring-gear": "冒險裝備",
    "srd5.1:equipment-category:ammunition": "彈藥",
    "srd5.1:equipment-category:tools": "工具",
    "srd5.1:equipment-category:mounts-and-vehicles": "坐騎與載具",
    "srd5.1:equipment-category:simple-weapons": "簡易武器",
    "srd5.1:equipment-category:martial-weapons": "軍用武器",
    "srd5.1:equipment-category:melee-weapons": "近戰武器",
    "srd5.1:equipment-category:ranged-weapons": "遠程武器",
    "srd5.1:equipment-category:simple-melee-weapons": "簡易近戰武器",
    "srd5.1:equipment-category:simple-ranged-weapons": "簡易遠程武器",
    "srd5.1:equipment-category:martial-melee-weapons": "軍用近戰武器",
    "srd5.1:equipment-category:martial-ranged-weapons": "軍用遠程武器",
    "srd5.1:equipment-category:light-armor": "輕甲",
    "srd5.1:equipment-category:medium-armor": "中甲",
    "srd5.1:equipment-category:heavy-armor": "重甲",
    "srd5.1:equipment-category:shields": "盾牌",
    "srd5.1:equipment-category:standard-gear": "一般裝備",
    "srd5.1:equipment-category:kits": "工具組",
    "srd5.1:equipment-category:equipment-packs": "裝備套組",
    "srd5.1:equipment-category:artisans-tools": "工匠工具",
    "srd5.1:equipment-category:gaming-sets": "博弈用具",
    "srd5.1:equipment-category:musical-instruments": "樂器",
    "srd5.1:equipment-category:other-tools": "其他工具",
    "srd5.1:equipment-category:mounts-and-other-animals": "坐騎與其他動物",
    "srd5.1:equipment-category:tack-harness-and-drawn-vehicles": "鞍具、挽具與牽引載具",
    "srd5.1:equipment-category:land-vehicles": "陸上載具",
    "srd5.1:equipment-category:waterborne-vehicles": "水上載具",
    "srd5.1:equipment-category:arcane-foci": "祕法法器",
    "srd5.1:equipment-category:druidic-foci": "德魯伊法器",
    "srd5.1:equipment-category:holy-symbols": "聖徽",
    "srd5.1:equipment-category:wondrous-items": "奇物",
    "srd5.1:equipment-category:rod": "權杖",
    "srd5.1:equipment-category:potion": "藥水",
    "srd5.1:equipment-category:ring": "戒指",
    "srd5.1:equipment-category:scroll": "卷軸",
    "srd5.1:equipment-category:staff": "法杖",
    "srd5.1:equipment-category:wand": "魔杖",
}

# Conservative characters that are Simplified-Chinese-only for the current
# D&D presentation vocabulary. Do not include ambiguous forms such as 「里」,
# which is valid Traditional Chinese in names such as 「里拉琴」.
SIMPLIFIED_ONLY_RE = re.compile(r"[术体龙剑药发门书风灵护战类这为与云气团阴圣师兽见觉听说话语骑标]")

# CR and dice notation are language-neutral rules notation. Imperial distance
# is user-facing prose and is normalized to Taiwan Traditional Chinese instead.
PASSTHROUGH_TOKENS = {"CR", "d"}
BUILTIN_TOKEN_OVERRIDES = {"ft": "呎"}


def _normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("’", "'").lower()
    value = value.replace("×", "x")
    value = re.sub(r"\b(\d+)(st|nd|rd|th)\b", r"\1", value)
    value = re.sub(r"[^a-z0-9+]+", " ", value)
    return " ".join(value.split())


def _reference_pair(display_name: str) -> tuple[str, str] | None:
    """Return (normalized English source name, Traditional Chinese display)."""
    if not HAN_RE.search(display_name):
        return None
    match = ASCII_SUFFIX_RE.search(display_name)
    if not match:
        return None
    english = match.group(1).strip()
    zh = display_name[: match.start()].strip(" ·-–—:：()[]")
    if not zh or not HAN_RE.search(zh):
        return None
    return _normalize_name(english), zh


def load_reference_names(root: Path) -> dict[str, str]:
    """Load only unambiguous English-name -> Traditional-Chinese-name pairs."""
    names: dict[str, str] = {}
    conflicts: set[str] = set()
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        display_name = payload.get("name")
        if not isinstance(display_name, str):
            continue
        pair = _reference_pair(display_name)
        if not pair:
            continue
        normalized, zh = pair
        previous = names.get(normalized)
        if previous is not None and previous != zh:
            conflicts.add(normalized)
            continue
        names[normalized] = zh
    for normalized in conflicts:
        names.pop(normalized, None)
    return names


def _read_rows(filename: str) -> list[dict[str, Any]]:
    payload = json.loads((base.SRD_ROOT / filename).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("entries"), list):
        rows = payload["entries"]
    else:
        raise ValueError(f"unexpected SRD category shape: {filename}")
    return [row for row in rows if isinstance(row, dict)]


def _required_policy_name_kinds() -> set[str]:
    policy = json.loads(base.POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or not isinstance(policy.get("rules"), list):
        raise ValueError("invalid localizable-fields policy")
    return {
        str(rule["kind"])
        for rule in policy["rules"]
        if isinstance(rule, dict)
        and rule.get("field_path") == "name"
        and rule.get("localizable")
        and rule.get("currently_user_visible")
        and "zh-TW" in rule.get("required_locales", [])
        and rule.get("pack") in {"*", "srd5.1"}
    }


def _add_policy_required_name_entries(
    overlay: dict[str, Any],
    report: dict[str, Any],
) -> int:
    """Add policy-required name kinds that the older base generator omits."""
    required_kinds = _required_policy_name_kinds()
    unknown_kinds = sorted(required_kinds - set(ALL_KIND_FILES))
    if unknown_kinds:
        raise ValueError(f"M02-D has no dataset mapping for required name kinds: {unknown_kinds}")

    added_fields = 0
    for kind in sorted(required_kinds - set(base.REQUIRED_KINDS)):
        filename = ALL_KIND_FILES[kind]
        rows = _read_rows(filename)
        for row in rows:
            key = row.get("key")
            name = row.get("name")
            if not isinstance(key, str) or not isinstance(name, str):
                raise ValueError(f"{filename}: required name entry missing key/name")
            # Seed with the canonical name. The StableKey exact/reference/token
            # priority below performs the actual zh-TW authoring resolution.
            overlay["entries"].setdefault(key, {})["name"] = name
            added_fields += 1
        report["categories"][kind] = {
            "entry_count": len(rows),
            "required_field_count": len(rows),
        }

    report["localized_entry_count"] = len(overlay["entries"])
    report["required_field_count"] += added_fields
    return added_fields


def _canonical_names() -> dict[str, str]:
    """Read canonical SRD names for every StableKey covered by M02-D."""
    names: dict[str, str] = {}
    for filename in sorted(set(ALL_KIND_FILES.values())):
        for raw in _read_rows(filename):
            key = raw.get("key")
            name = raw.get("name")
            if isinstance(key, str) and isinstance(name, str):
                names[key] = name
    return names


def _structured_name_override(key: str) -> str | None:
    """Translate name patterns whose ordinal suffix carries structural meaning."""
    match = SPELL_SCROLL_KEY_RE.match(key)
    if match:
        return f"{match.group(1)}環法術卷軸"
    match = MYSTIC_ARCANUM_KEY_RE.match(key)
    if match:
        return f"神祕奧秘：{match.group(1)}級"
    return None


def _token_candidates(token: str) -> tuple[str, ...]:
    """Recover possessive spellings lost by the base tokenizer."""
    lower = token.lower()
    candidates = [token, lower]
    if lower.endswith("s") and len(lower) > 1:
        candidates.append(f"{lower[:-1]}'s")
        candidates.append(f"{lower}'")
    return tuple(dict.fromkeys(candidates))


def _replace_markers(value: Any, token_overrides: dict[str, str]) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            token = match.group(1)
            if token in PASSTHROUGH_TOKENS:
                return token
            for candidate in _token_candidates(token):
                translated = token_overrides.get(candidate)
                if translated is not None:
                    return translated
            translated = BUILTIN_TOKEN_OVERRIDES.get(token.lower())
            return translated if translated is not None else match.group(0)

        return UNTRANSLATED_RE.sub(replace, value)
    if isinstance(value, list):
        return [_replace_markers(item, token_overrides) for item in value]
    if isinstance(value, dict):
        return {key: _replace_markers(item, token_overrides) for key, item in value.items()}
    return value


def _remaining_markers(overlay: dict[str, Any]) -> list[dict[str, str]]:
    remaining: list[dict[str, str]] = []
    for key, fields in overlay["entries"].items():
        for field_path, value in fields.items():
            if not isinstance(value, str):
                continue
            for token in UNTRANSLATED_RE.findall(value):
                remaining.append(
                    {
                        "key": key,
                        "field_path": field_path,
                        "token": token,
                        "value": value,
                    }
                )
    return remaining


def _simplified_residues(overlay: dict[str, Any]) -> list[dict[str, str]]:
    residues: list[dict[str, str]] = []
    for key, fields in overlay["entries"].items():
        for field_path, value in fields.items():
            if not isinstance(value, str):
                continue
            found = sorted(set(SIMPLIFIED_ONLY_RE.findall(value)))
            if found:
                residues.append(
                    {
                        "key": key,
                        "field_path": field_path,
                        "characters": "".join(found),
                        "value": value,
                    }
                )
    return residues


def build_reviewed_overlay(
    reference_root: Path | None,
    token_overrides: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    overlay, report = base.build_overlay()
    added_policy_name_fields = _add_policy_required_name_entries(overlay, report)
    reference_names = load_reference_names(reference_root) if reference_root else {}
    canonical_names = _canonical_names()

    exact_reference_hits = 0
    structured_name_hits = 0
    project_exact_name_hits = 0

    # Whole-name quality must be decided before unresolved-token replacement.
    # Otherwise a mechanically complete token composition such as
    # "Light Hammer" -> "光明錘" would contain no marker and could never be
    # corrected by the reviewed whole-name reference.
    for key, fields in overlay["entries"].items():
        if not isinstance(fields, dict) or "name" not in fields:
            continue
        canonical = canonical_names.get(key)
        if canonical is None:
            continue

        stable_exact = PROJECT_EXACT_BY_KEY.get(key)
        if stable_exact is not None:
            fields["name"] = stable_exact
            project_exact_name_hits += 1
            continue

        # Project-owned exact terminology always wins over external authoring
        # references. StableKey-specific collisions were handled above.
        if canonical in base.EXACT:
            fields["name"] = base.EXACT[canonical]
            project_exact_name_hits += 1
            continue

        structured = _structured_name_override(key)
        if structured is not None:
            fields["name"] = structured
            structured_name_hits += 1
            continue

        referenced = reference_names.get(_normalize_name(canonical))
        if referenced is not None:
            fields["name"] = referenced
            exact_reference_hits += 1

    overlay = _replace_markers(overlay, token_overrides)
    remaining = _remaining_markers(overlay)
    simplified = _simplified_residues(overlay)
    report = {
        **report,
        "base_unknown_count": report["unknown_count"],
        "added_policy_name_field_count": added_policy_name_fields,
        "reference_name_count": len(reference_names),
        "project_exact_name_hits": project_exact_name_hits,
        "exact_reference_hits": exact_reference_hits,
        "structured_name_hits": structured_name_hits,
        "reviewed_token_override_count": len(token_overrides),
        "unknown_count": len(remaining),
        "unknowns": remaining,
        "simplified_residue_count": len(simplified),
        "simplified_residues": simplified,
    }
    return overlay, report


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=base.SRD_ROOT / "locales" / "zh-TW.json")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--token-overrides", type=Path)
    parser.add_argument(
        "--check-against",
        type=Path,
        help="fail if the generated overlay differs from this committed overlay",
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    if args.strict and (args.reference_root is None or not args.reference_root.is_dir()):
        parser.error("--strict requires an existing --reference-root")

    token_overrides: dict[str, str] = {}
    if args.token_overrides:
        raw = _load_json_object(args.token_overrides)
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in raw.items()):
            raise ValueError("token overrides must be a JSON string-to-string object")
        token_overrides = raw

    overlay, report = build_reviewed_overlay(args.reference_root, token_overrides)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        "M02-D reviewed SRD zh-TW candidate: "
        f"{report['localized_entry_count']} entries / "
        f"{report['required_field_count']} required fields / "
        f"{report['project_exact_name_hits']} project exact names / "
        f"{report['exact_reference_hits']} exact reference hits / "
        f"{report['structured_name_hits']} structured names / "
        f"{report['unknown_count']} unknown markers / "
        f"{report['simplified_residue_count']} simplified residues"
    )

    failed = False
    if args.strict and report["reference_name_count"] == 0:
        print("REFERENCE no unambiguous Traditional Chinese names were loaded")
        failed = True
    if report["unknown_count"]:
        for item in report["unknowns"]:
            print(f"UNKNOWN {item['token']!r}: {item['value']} [{item['key']}::{item['field_path']}]")
        failed = True
    if report["simplified_residue_count"]:
        for item in report["simplified_residues"]:
            print(
                "SIMPLIFIED "
                f"{item['characters']!r}: {item['value']} [{item['key']}::{item['field_path']}]"
            )
        failed = True

    if args.check_against:
        committed = _load_json_object(args.check_against)
        if committed != overlay:
            print(f"DRIFT generated overlay differs from {args.check_against}")
            failed = True

    if args.strict and failed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
