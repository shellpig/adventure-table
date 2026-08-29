from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.content.registry import (
    DEFAULT_CONTENT_ROOT,
    ContentNotFoundError,
    ContentRegistry,
    ContentValidationError,
)


EXPECTED_KINDS = {
    "ability",
    "alignment",
    "background",
    "class",
    "condition",
    "damage-type",
    "equipment-category",
    "equipment",
    "feat",
    "feature",
    "language",
    "level",
    "item",
    "magic-school",
    "proficiency",
    "race",
    "skill",
    "spell",
    "subclass",
    "subrace",
    "trait",
    "weapon-property",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def copy_content(tmp_path: Path) -> Path:
    target = tmp_path / "srd5.1"
    shutil.copytree(DEFAULT_CONTENT_ROOT, target)
    return target


def test_full_character_relevant_srd_loads() -> None:
    registry = ContentRegistry.from_directory(DEFAULT_CONTENT_ROOT)

    assert len(registry) == registry.manifest.total_entries
    assert set(category.kind for category in registry.manifest.categories) == EXPECTED_KINDS
    assert registry.manifest.scope_guard.deferred_to == "P4-A"
    assert {"monsters", "beasts"}.issubset(
        set(registry.manifest.scope_guard.excluded_categories)
    )
    assert not (DEFAULT_CONTENT_ROOT / "monsters.json").exists()
    assert not (DEFAULT_CONTENT_ROOT / "beasts.json").exists()


@pytest.mark.parametrize(
    ("key", "expected_name"),
    [
        ("srd5.1:race:human", "Human"),
        ("srd5.1:class:fighter", "Fighter"),
        ("srd5.1:spell:fireball", "Fireball"),
        ("srd5.1:equipment:chain-mail", "Chain Mail"),
        ("srd5.1:condition:poisoned", "Poisoned"),
        ("srd5.1:item:potion-of-healing", "Potion of Healing"),
    ],
)
def test_registry_resolves_baseline_entries(key: str, expected_name: str) -> None:
    registry = ContentRegistry.from_directory(DEFAULT_CONTENT_ROOT)

    assert registry.get(key).name == expected_name


def test_missing_key_is_explicit() -> None:
    registry = ContentRegistry.from_directory(DEFAULT_CONTENT_ROOT)

    with pytest.raises(ContentNotFoundError):
        registry.get("srd5.1:spell:not-a-real-spell")


def test_duplicate_key_fails(tmp_path: Path) -> None:
    root = copy_content(tmp_path)
    path = root / "conditions.json"
    entries = load_json(path)
    entries.append(entries[0])
    write_json(path, entries)

    manifest = load_json(root / "manifest.json")
    condition = next(c for c in manifest["categories"] if c["name"] == "conditions")
    condition["count"] += 1
    manifest["total_entries"] += 1
    write_json(root / "manifest.json", manifest)

    with pytest.raises(ContentValidationError, match="duplicate content key"):
        ContentRegistry.from_directory(root)


def test_missing_required_field_fails(tmp_path: Path) -> None:
    root = copy_content(tmp_path)
    path = root / "conditions.json"
    entries = load_json(path)
    entries[0].pop("name")
    write_json(path, entries)

    with pytest.raises(ContentValidationError, match="schema validation failed"):
        ContentRegistry.from_directory(root)


def test_malformed_spell_enum_fails(tmp_path: Path) -> None:
    root = copy_content(tmp_path)
    path = root / "spells.json"
    entries = load_json(path)
    entries[0]["data"]["level"] = 99
    write_json(path, entries)

    with pytest.raises(ContentValidationError, match="schema validation failed"):
        ContentRegistry.from_directory(root)


def test_dangling_reference_fails(tmp_path: Path) -> None:
    root = copy_content(tmp_path)
    path = root / "classes.json"
    entries = load_json(path)
    entries[0]["data"]["saving_throws"][0] = {
        "index": "missing-ability",
        "name": "Missing",
        "url": "/api/2014/ability-scores/missing-ability",
    }
    write_json(path, entries)

    with pytest.raises(ContentValidationError, match="dangling reference"):
        ContentRegistry.from_directory(root)


def test_monster_file_is_rejected_by_p0_scope_guard(tmp_path: Path) -> None:
    root = copy_content(tmp_path)
    write_json(root / "monsters.json", [])

    with pytest.raises(ContentValidationError, match="P0 scope violation"):
        ContentRegistry.from_directory(root)
