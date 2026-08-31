from __future__ import annotations

import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import pytest

from app.content import load_default_content_registry
from app.content.localization_files import (
    _read_overlay_file,
    load_content_localization_catalog,
)
from app.content.registry import CONTENT_PACKS_ROOT, ContentValidationError


POLICY_PATH = CONTENT_PACKS_ROOT / "localization" / "localizable-fields.json"


def _overlay_payload(entries: dict[str, dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "locale": "zh-TW",
        "review_status": "draft-human-review-required",
        "entries": entries,
    }


def _write_shard(root: Path, name: str, entries: dict[str, dict[str, object]]) -> None:
    path = root / "srd5.1" / "locales" / "zh-TW" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_overlay_payload(entries), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_monolith(root: Path, entries: dict[str, dict[str, object]]) -> None:
    path = root / "srd5.1" / "locales" / "zh-TW.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_overlay_payload(entries), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_runtime_merges_human_review_locale_shards() -> None:
    registry = load_default_content_registry()

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_shard(
            root,
            "classes.json",
            {"srd5.1:class:fighter": {"name": "戰士"}},
        )
        _write_shard(
            root,
            "spells.json",
            {"srd5.1:spell:fireball": {"name": "火球術"}},
        )

        catalog = load_content_localization_catalog(
            registry,
            root,
            policy_path=POLICY_PATH,
        )

    assert catalog.resolve_name("srd5.1:class:fighter", "zh-TW").value == "戰士"
    assert catalog.resolve_name("srd5.1:spell:fireball", "zh-TW").value == "火球術"


def test_human_review_shards_take_precedence_over_monolithic_candidate() -> None:
    registry = load_default_content_registry()

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_monolith(
            root,
            {"srd5.1:class:fighter": {"name": "Machine Draft Fighter"}},
        )
        _write_shard(
            root,
            "classes.json",
            {"srd5.1:class:fighter": {"name": "戰士"}},
        )

        catalog = load_content_localization_catalog(
            registry,
            root,
            policy_path=POLICY_PATH,
        )

    assert catalog.resolve_name("srd5.1:class:fighter", "zh-TW").value == "戰士"


def test_locale_shards_reject_only_structural_conflicts() -> None:
    registry = load_default_content_registry()

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_shard(
            root,
            "01.json",
            {"srd5.1:class:fighter": {"name": "戰士"}},
        )
        _write_shard(
            root,
            "02.json",
            {"srd5.1:class:fighter": {"name": "鬥士"}},
        )

        with pytest.raises(ContentValidationError, match="conflicting locale overlay field"):
            load_content_localization_catalog(
                registry,
                root,
                policy_path=POLICY_PATH,
            )


def test_locale_shards_allow_mixed_language_human_review_drafts() -> None:
    registry = load_default_content_registry()

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_shard(
            root,
            "equipment.json",
            {
                "srd5.1:equipment:quarterstaff": {"name": "Quarterstaff"},
                "srd5.1:equipment:shield": {"name": "盾牌"},
            },
        )
        catalog = load_content_localization_catalog(
            registry,
            root,
            policy_path=POLICY_PATH,
        )

    quarterstaff = catalog.resolve_name("srd5.1:equipment:quarterstaff", "zh-TW")
    shield = catalog.resolve_name("srd5.1:equipment:shield", "zh-TW")
    assert quarterstaff.value == "Quarterstaff"
    assert not quarterstaff.missing_required
    assert shield.value == "盾牌"


def test_committed_zh_tw_shard_names_are_not_left_in_source_language() -> None:
    """Dataset gate: a shipped zh-TW name must read as Traditional Chinese.

    The loader deliberately tolerates mixed-language review drafts, so
    completeness alone cannot distinguish a translated name from an English
    string copied into the zh-TW column. This gate is the dataset-level
    counterpart: every shipped name needs Han characters, and any Latin left
    inside it must be rules notation rather than an untranslated word.
    """

    registry = load_default_content_registry()
    han = re.compile(r"[㐀-鿿]")
    latin_word = re.compile(r"[A-Za-z][A-Za-z0-9]*")
    # Latin that is notation, not language: challenge rating, dice, feet, and
    # the multiplication marker used by carpet-of-flying dimensions.
    notation = re.compile(r"^(?:CR|d\d+|ft|x|X)$")

    findings: list[str] = []
    for pack in registry.enabled_pack_ids:
        shard_root = CONTENT_PACKS_ROOT / pack / "locales" / "zh-TW"
        for shard in sorted(shard_root.glob("*.json")):
            entries = _read_overlay_file(shard, "zh-TW")
            for key, fields in entries.items():
                name = fields.get("name")
                if not isinstance(name, str):
                    continue
                if not han.search(name):
                    findings.append(f"untranslated: {key} -> {name}")
                    continue
                leftovers = [
                    token
                    for token in latin_word.findall(name)
                    if not notation.match(token)
                ]
                if leftovers:
                    findings.append(f"mixed: {key} -> {name}")

    assert findings == [], "zh-TW shard names still carry source language: " + ", ".join(
        findings[:20]
    )
