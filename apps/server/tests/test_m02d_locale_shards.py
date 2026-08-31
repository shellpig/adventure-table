from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import CONTENT_PACKS_ROOT, ContentValidationError


POLICY_PATH = CONTENT_PACKS_ROOT / "localization" / "localizable-fields.json"


def _write_shard(root: Path, name: str, entries: dict[str, dict[str, object]]) -> None:
    path = root / "srd5.1" / "locales" / "zh-TW" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "locale": "zh-TW",
                "review_status": "draft-human-review-required",
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_runtime_merges_human_review_locale_shards() -> None:
    registry = load_default_content_registry()

    with pytest.MonkeyPatch.context():
        pass

    from tempfile import TemporaryDirectory

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


def test_locale_shards_reject_only_structural_conflicts() -> None:
    registry = load_default_content_registry()

    from tempfile import TemporaryDirectory

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

    from tempfile import TemporaryDirectory

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
