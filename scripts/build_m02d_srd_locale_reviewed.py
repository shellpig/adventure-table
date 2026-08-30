"""Finish the M02-D SRD zh-TW overlay with reviewed external-name references.

The base generator remains the source of project terminology and deterministic
compositional translations. This authoring-only pass may consume a checkout of
an explicitly pinned Traditional Chinese community reference to improve whole
visible names by exact English-name matches. Runtime never reads the reference
checkout; it only reads the committed data/srd5.1/locales/zh-TW.json.

Translation priority for names is deliberately strict:
1. project-owned exact glossary entries;
2. structural name rules whose ordinal carries meaning;
3. unambiguous whole-name matches from the pinned Traditional Chinese reference;
4. reviewed deterministic token composition as the final fallback.
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


def _canonical_names() -> dict[str, str]:
    """Read canonical SRD names for every StableKey covered by M02-D."""
    names: dict[str, str] = {}
    for filename in sorted(set(base.CATEGORY_BY_KIND.values())):
        payload = json.loads((base.SRD_ROOT / filename).read_text(encoding="utf-8"))
        for raw in payload.get("entries", []):
            if not isinstance(raw, dict):
                continue
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
    """Recover possessive spellings lost by the base tokenizer.

    SRD names such as ``Alchemist's Supplies`` and ``Hunter's Prey`` are
    tokenized as ``Alchemists`` / ``Hunters`` before the unresolved marker is
    emitted. Keep the reviewed dictionary canonical and try the normalized
    possessive spellings here instead of duplicating dozens of aliases.
    """
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


def build_reviewed_overlay(
    reference_root: Path | None,
    token_overrides: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    overlay, report = base.build_overlay()
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

        # Project-owned exact terminology always wins over external authoring
        # references. This keeps the M02 glossary the final terminology SSOT.
        if canonical in base.EXACT:
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
    report = {
        **report,
        "base_unknown_count": report["unknown_count"],
        "reference_name_count": len(reference_names),
        "project_exact_name_hits": project_exact_name_hits,
        "exact_reference_hits": exact_reference_hits,
        "structured_name_hits": structured_name_hits,
        "reviewed_token_override_count": len(token_overrides),
        "unknown_count": len(remaining),
        "unknowns": remaining,
    }
    return overlay, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=base.SRD_ROOT / "locales" / "zh-TW.json")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--token-overrides", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    token_overrides: dict[str, str] = {}
    if args.token_overrides:
        raw = json.loads(args.token_overrides.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in raw.items()
        ):
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
        f"{report['unknown_count']} unknown markers"
    )
    if report["unknown_count"]:
        for item in report["unknowns"]:
            print(f"UNKNOWN {item['token']!r}: {item['value']} [{item['key']}::{item['field_path']}]")
        if args.strict:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
