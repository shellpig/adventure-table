from __future__ import annotations

from app.paths import resolve_content_root

CONTENT_PACKS_ROOT = resolve_content_root()

"""Canonical content must stay locale-neutral.

M01-J was authored from Chinese-first reference documents. Where a heading
carried no English title the generator fell back to the Chinese one, which then
surfaced as the ``en`` presentation because canonical values *are* the ``en``
presentation. The M02 completeness gate did not catch it: that gate only checks
whether a value is present, not which language it is in.
"""


import re

import pytest

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog


CJK = re.compile(r"[㐀-鿿　-〿＀-￯]")

# reference_text_zh parks the Chinese rules text of an M01-J feature until an
# English source exists for data.desc.*; it is not a presentation field and is
# deliberately excluded here.
PARKED_FIELDS = frozenset({"reference_text_zh", "reference_heading_zh"})


@pytest.fixture(scope="module")
def registry():
    return load_default_content_registry()


def test_canonical_names_contain_no_cjk(registry) -> None:
    offenders = [
        f"{entry.key} => {entry.name}"
        for kind in ("subclass", "feature", "level")
        for entry in registry.list_kind(kind)
        if entry.name and CJK.search(entry.name)
    ]
    assert offenders == [], (
        "canonical name is the en presentation and must be locale-neutral: "
        + "; ".join(offenders[:10])
    )


def test_canonical_descriptions_contain_no_cjk(registry) -> None:
    offenders: list[str] = []
    for kind in ("subclass", "feature", "level"):
        for entry in registry.list_kind(kind):
            desc = entry.data.get("desc")
            if desc is None:
                continue
            values = desc if isinstance(desc, list) else [desc]
            for value in values:
                if isinstance(value, str) and CJK.search(value):
                    offenders.append(f"{entry.key}: {value[:40]}")
                    break
    assert offenders == [], "canonical desc must be locale-neutral: " + "; ".join(offenders[:10])


def test_stable_keys_carry_no_escape_or_positional_residue(registry) -> None:
    escape = re.compile(r"-u[0-9a-f]{4}")
    positional = re.compile(r"-option-\d+(?:-\d+)?$")
    offenders = [
        entry.key
        for kind in ("subclass", "feature", "level")
        for entry in registry.list_kind(kind)
        if escape.search(entry.key) or positional.search(entry.key)
    ]
    assert offenders == [], "StableKey must be a readable slug: " + "; ".join(offenders[:10])


def test_english_presentation_is_english(registry) -> None:
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)
    offenders: list[str] = []
    for kind in ("subclass", "feature"):
        for entry in registry.list_kind(kind):
            resolved = catalog.resolve_name(entry.key, "en")
            value = getattr(resolved, "value", None)
            if isinstance(value, str) and CJK.search(value):
                offenders.append(f"{entry.key} => {value}")
    assert offenders == [], (
        "en presentation resolved to Chinese: " + "; ".join(offenders[:10])
    )


def test_parked_chinese_rules_text_is_not_a_presentation_field(registry) -> None:
    """The parked Chinese text must not be exposed as a localizable field."""

    from app.content.localization import LocalizableFieldPolicy

    policy = LocalizableFieldPolicy.from_path(
        CONTENT_PACKS_ROOT / "localization" / "localizable-fields.json"
    )
    for pack in ("phb2014", "scag", "xge", "tce"):
        for field in PARKED_FIELDS:
            assert policy.rule_for(pack, "feature", f"data.{field}") is None
