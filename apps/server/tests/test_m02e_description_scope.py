from __future__ import annotations

from collections import Counter
import json
import re
from pathlib import Path

from app.content.localization import LocalizableFieldPolicy
from app.content.registry import CONTENT_PACKS_ROOT, DEFAULT_CONTENT_ROOT


POLICY_PATH = CONTENT_PACKS_ROOT / "localization" / "localizable-fields.json"
LOCALE_ROOT = DEFAULT_CONTENT_ROOT / "locales" / "zh-TW"

# M02-E deliberately authors the rule text that is most likely to surface while
# building and playing a character. This is broader than today's field-policy
# shipping requirement, but it does not make hidden fields user-visible.
M02E_AUTHORED_DESCRIPTION_KINDS = {
    "spell": "spells.json",
    "feature": "features.json",
    "condition": "conditions.json",
}

# Item descriptions remain explicitly deferred by the field policy. Pulling the
# whole item long-text corpus into M02-E would recreate the scope contradiction
# that the field-level policy was introduced to prevent.
M02E_DEFERRED_LONG_FORM_RULES = {
    ("background", "data.feature.desc"),
    ("item", "data.desc.*"),
}

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z]{3,}")
_DICE_RE = re.compile(r"(?<![A-Za-z0-9])\d+d\d+(?![A-Za-z0-9])", re.IGNORECASE)
_SIGNED_RE = re.compile(r"(?<![\w.])[+-]\d+(?!\w)")
_NUMBER_RE = re.compile(r"(?<![\w])\d[\d,]*(?:\.\d+)?(?!\w)")


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_zh_tw_overlay_fields() -> dict[str, dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    field_sources: dict[tuple[str, str], Path] = {}

    for path in sorted(LOCALE_ROOT.glob("*.json")):
        payload = _read_json(path)
        assert isinstance(payload, dict), path
        assert payload.get("schema_version") == 1, path
        assert payload.get("locale") == "zh-TW", path
        entries = payload.get("entries")
        assert isinstance(entries, dict), path

        for stable_key, raw_fields in entries.items():
            assert isinstance(stable_key, str), path
            assert isinstance(raw_fields, dict), (path, stable_key)
            target = merged.setdefault(stable_key, {})
            for field_path, value in raw_fields.items():
                assert isinstance(field_path, str), (path, stable_key)
                identity = (stable_key, field_path)
                if field_path in target:
                    assert target[field_path] == value, (
                        "conflicting zh-TW field",
                        stable_key,
                        field_path,
                        field_sources[identity],
                        path,
                    )
                target[field_path] = value
                field_sources[identity] = path

    return merged


def _canonical_description_fields(kind: str, filename: str) -> dict[tuple[str, str], str]:
    payload = _read_json(DEFAULT_CONTENT_ROOT / filename)
    assert isinstance(payload, list), filename

    result: dict[tuple[str, str], str] = {}
    for entry in payload:
        assert isinstance(entry, dict), filename
        stable_key = entry.get("key")
        data = entry.get("data")
        assert isinstance(stable_key, str), entry
        assert isinstance(data, dict), stable_key
        desc = data.get("desc")
        if desc is None:
            continue
        assert isinstance(desc, list), stable_key
        for index, text in enumerate(desc):
            assert isinstance(text, str), (stable_key, index)
            result[(stable_key, f"data.desc.{index}")] = text

    assert result, kind
    return result


def _mechanics_tokens(text: str) -> Counter[str]:
    # Dice and signed modifiers are removed from the generic-number pass so
    # tokens such as 2d8 are not accidentally treated as unrelated 2 / 8.
    dice = [token.lower() for token in _DICE_RE.findall(text)]
    without_dice = _DICE_RE.sub(" ", text)
    signed = _SIGNED_RE.findall(without_dice)
    without_signed = _SIGNED_RE.sub(" ", without_dice)
    numbers = [token.replace(",", "") for token in _NUMBER_RE.findall(without_signed)]
    return Counter([*(f"dice:{token}" for token in dice), *(f"signed:{token}" for token in signed), *(f"num:{token}" for token in numbers)])


def _is_markdown_table_row(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def test_m02e_policy_keeps_non_surface_item_and_background_long_text_deferred() -> None:
    policy = LocalizableFieldPolicy.from_path(POLICY_PATH)
    policy_rules = {
        (rule.kind, rule.field_path): rule
        for rule in policy.rules
        if rule.pack in {"*", "srd5.1"}
    }

    assert M02E_DEFERRED_LONG_FORM_RULES.issubset(policy_rules)
    for identity in M02E_DEFERRED_LONG_FORM_RULES:
        rule = policy_rules[identity]
        assert rule.localizable
        assert not rule.currently_user_visible
        assert rule.required_locales == ()


def test_m02e_all_authored_srd_descriptions_have_exact_zh_tw_field_coverage() -> None:
    overlay = _load_zh_tw_overlay_fields()

    missing: list[str] = []
    unexpected_empty: list[str] = []
    covered = 0

    for kind, filename in M02E_AUTHORED_DESCRIPTION_KINDS.items():
        canonical = _canonical_description_fields(kind, filename)
        for (stable_key, field_path), source_text in canonical.items():
            translated = overlay.get(stable_key, {}).get(field_path)
            if not isinstance(translated, str):
                missing.append(f"{stable_key}::{field_path}")
                continue
            covered += 1
            if source_text.strip() and not translated.strip():
                unexpected_empty.append(f"{stable_key}::{field_path}")

    assert not missing, "missing M02-E zh-TW description fields:\n" + "\n".join(missing[:100])
    assert not unexpected_empty, "non-empty canonical fields translated as empty:\n" + "\n".join(unexpected_empty[:100])
    assert covered > 0


def test_m02e_human_language_descriptions_do_not_ship_as_unchanged_english() -> None:
    overlay = _load_zh_tw_overlay_fields()
    leaked: list[str] = []

    for kind, filename in M02E_AUTHORED_DESCRIPTION_KINDS.items():
        canonical = _canonical_description_fields(kind, filename)
        for (stable_key, field_path), source_text in canonical.items():
            if not _WORD_RE.search(source_text):
                # Empty strings and markdown separator rows carry no language.
                continue
            translated = overlay.get(stable_key, {}).get(field_path)
            if not isinstance(translated, str):
                continue  # Coverage test reports this with the clearer error.
            if translated.strip() == source_text.strip() or not _CJK_RE.search(translated):
                leaked.append(f"{stable_key}::{field_path}")

    assert not leaked, "unchanged/non-Chinese M02-E descriptions:\n" + "\n".join(leaked[:100])


def test_m02e_description_mechanics_tokens_and_table_shapes_are_preserved() -> None:
    overlay = _load_zh_tw_overlay_fields()
    token_mismatches: list[str] = []
    table_mismatches: list[str] = []

    for kind, filename in M02E_AUTHORED_DESCRIPTION_KINDS.items():
        canonical = _canonical_description_fields(kind, filename)
        for (stable_key, field_path), source_text in canonical.items():
            translated = overlay.get(stable_key, {}).get(field_path)
            if not isinstance(translated, str):
                continue

            source_tokens = _mechanics_tokens(source_text)
            translated_tokens = _mechanics_tokens(translated)
            missing_tokens = source_tokens - translated_tokens
            if missing_tokens:
                token_mismatches.append(
                    f"{stable_key}::{field_path} missing {dict(missing_tokens)}"
                )

            if _is_markdown_table_row(source_text):
                if not _is_markdown_table_row(translated) or source_text.count("|") != translated.count("|"):
                    table_mismatches.append(f"{stable_key}::{field_path}")

    assert not token_mismatches, "mechanics-sensitive tokens changed/lost:\n" + "\n".join(token_mismatches[:100])
    assert not table_mismatches, "markdown table shape changed:\n" + "\n".join(table_mismatches[:100])
