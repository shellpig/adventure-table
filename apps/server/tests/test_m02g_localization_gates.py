from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.content import load_default_content_registry
from app.content.localization import (
    SUPPORTED_CONTENT_LOCALES,
    ContentLocalizationCatalog,
    LocalizableFieldPolicy,
    LocalizableFieldRule,
)
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import CONTENT_PACKS_ROOT, ContentValidationError


POLICY_PATH = CONTENT_PACKS_ROOT / "localization" / "localizable-fields.json"
M02_CLOSEOUT_PACKS = {"srd5.1", "phb2014", "scag", "gos"}


def _write_shard(root: Path, source: str, locale: str, name: str, entries: dict) -> None:
    path = root / source / "locales" / locale / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema_version": 1, "locale": locale, "entries": entries},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_enabled_pack_required_localization_is_complete() -> None:
    registry = load_default_content_registry()
    assert M02_CLOSEOUT_PACKS.issubset(set(registry.enabled_pack_ids))

    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)
    issues = catalog.completeness_issues(
        locales=SUPPORTED_CONTENT_LOCALES,
        sources=M02_CLOSEOUT_PACKS,
    )

    assert not issues, "\n".join(
        f"{issue.key} :: {issue.field_path} :: {issue.locale} :: {issue.reason}"
        for issue in issues
    )


def test_overlay_unknown_stable_key_is_rejected(tmp_path: Path) -> None:
    registry = load_default_content_registry()
    _write_shard(
        tmp_path,
        "srd5.1",
        "zh-TW",
        "orphan-key.json",
        {"srd5.1:spell:not-a-real-spell": {"name": "不存在的法術"}},
    )

    with pytest.raises(ContentValidationError, match="references unknown content key"):
        load_content_localization_catalog(registry, tmp_path, policy_path=POLICY_PATH)


def test_overlay_unknown_field_path_is_rejected(tmp_path: Path) -> None:
    registry = load_default_content_registry()
    entry = registry.list_kind("spell", source="srd5.1")[0]
    _write_shard(
        tmp_path,
        "srd5.1",
        "zh-TW",
        "bad-field.json",
        {entry.key: {"data.this_field_does_not_exist": "不存在"}},
    )

    with pytest.raises(ContentValidationError, match="references unknown field"):
        load_content_localization_catalog(registry, tmp_path, policy_path=POLICY_PATH)


def test_srd_acolyte_roleplay_orphan_is_not_exempted(tmp_path: Path) -> None:
    registry = load_default_content_registry()
    _write_shard(
        tmp_path,
        "srd5.1",
        "zh-TW",
        "bad-acolyte-roleplay.json",
        {
            "srd5.1:background:acolyte": {
                "data.roleplay_suggestions.personality_traits.0": "不應存在的舊譯文"
            }
        },
    )

    with pytest.raises(ContentValidationError, match="references unknown field"):
        load_content_localization_catalog(registry, tmp_path, policy_path=POLICY_PATH)


def test_duplicate_locale_key_field_definition_is_rejected_even_when_equal(tmp_path: Path) -> None:
    registry = load_default_content_registry()
    entry = registry.list_kind("spell", source="srd5.1")[0]
    fields = {entry.key: {"name": "測試譯名"}}
    _write_shard(tmp_path, "srd5.1", "zh-TW", "01.json", fields)
    _write_shard(tmp_path, "srd5.1", "zh-TW", "02.json", fields)

    with pytest.raises(ContentValidationError, match="duplicate locale overlay field"):
        load_content_localization_catalog(registry, tmp_path, policy_path=POLICY_PATH)


def test_unsupported_locale_artifact_is_rejected(tmp_path: Path) -> None:
    registry = load_default_content_registry()
    _write_shard(tmp_path, "srd5.1", "fr-FR", "core.json", {})

    with pytest.raises(ContentValidationError, match="unsupported locale artifact"):
        load_content_localization_catalog(registry, tmp_path, policy_path=POLICY_PATH)


def test_future_visibility_requires_every_supported_locale() -> None:
    registry = load_default_content_registry()
    item = next(entry for entry in registry.list_kind("item", source="srd5.1") if entry.data.get("desc"))
    field_path = "data.desc.0"
    policy = LocalizableFieldPolicy(
        (
            LocalizableFieldRule(
                pack="srd5.1",
                kind="item",
                field_path="data.desc.*",
                localizable=True,
                currently_user_visible=True,
                required_locales=SUPPORTED_CONTENT_LOCALES,
                surfaces=("future-fixture",),
                reason="Future-visible content must be bilingual before exposure.",
            ),
        )
    )

    english_only = ContentLocalizationCatalog(registry, policy)
    issues = english_only.completeness_issues(
        locales=SUPPORTED_CONTENT_LOCALES,
        sources={"srd5.1"},
        kinds={"item"},
    )
    assert any(
        issue.key == item.key and issue.field_path == field_path and issue.locale == "zh-TW"
        for issue in issues
    )

    zh_entries: dict[str, dict[str, str]] = {}
    for candidate in registry.list_kind("item", source="srd5.1"):
        descriptions = candidate.data.get("desc")
        if not isinstance(descriptions, list):
            continue
        zh_entries[candidate.key] = {
            f"data.desc.{index}": f"測試翻譯 {index + 1}"
            for index, _description in enumerate(descriptions)
        }

    translated = ContentLocalizationCatalog(
        registry,
        policy,
        {("srd5.1", "zh-TW"): zh_entries},
    )
    assert not translated.completeness_issues(
        locales=SUPPORTED_CONTENT_LOCALES,
        sources={"srd5.1"},
        kinds={"item"},
    )
