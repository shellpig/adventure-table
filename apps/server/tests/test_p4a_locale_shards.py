from __future__ import annotations

from pathlib import Path

import pytest

from app.content.localization import ContentLocalizationCatalog, _merge_locale_overlay
from app.content.p4a_monsters import install_p4a_content_models
from app.content.registry import ContentRegistry, ContentValidationError


DATA_ROOT = Path(__file__).resolve().parents[3] / "data"


def test_catalog_loads_existing_zh_tw_locale_shards() -> None:
    install_p4a_content_models()
    registry = ContentRegistry.from_directory(DATA_ROOT / "srd5.1")
    catalog = ContentLocalizationCatalog.from_root(registry, DATA_ROOT)

    localized = catalog.resolve_name("srd5.1:class:fighter", "zh-TW")
    assert localized.value == "戰士"
    assert localized.source == "overlay"
    assert localized.fallback_used is False


def test_locale_shards_can_split_a_key_across_distinct_fields(tmp_path: Path) -> None:
    merged: dict[str, dict[str, object]] = {}
    key = "srd5.1:monster:fixture"

    _merge_locale_overlay(merged, {key: {"name": "測試怪物"}}, path=tmp_path / "a.json")
    _merge_locale_overlay(
        merged,
        {key: {"data.actions.0.name": "啃咬"}},
        path=tmp_path / "b.json",
    )

    assert merged[key] == {
        "name": "測試怪物",
        "data.actions.0.name": "啃咬",
    }


def test_locale_shards_reject_duplicate_field_ownership(tmp_path: Path) -> None:
    merged: dict[str, dict[str, object]] = {}
    key = "srd5.1:monster:fixture"

    _merge_locale_overlay(merged, {key: {"name": "甲"}}, path=tmp_path / "a.json")
    with pytest.raises(ContentValidationError, match="duplicates field"):
        _merge_locale_overlay(merged, {key: {"name": "乙"}}, path=tmp_path / "b.json")
