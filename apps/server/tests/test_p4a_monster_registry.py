from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.content.p4a_inventory import (
    EXPECTED_SRD_BEAST_COUNT,
    EXPECTED_SRD_MONSTER_COUNT,
    validate_p4a_monster_inventory,
)
from app.content.p4a_monsters import MonsterData, install_p4a_content_models
from app.content.registry import ContentRegistry, ContentValidationError
from app.content.schemas import ContentManifest, DATA_MODELS


class _FakeRegistry:
    def __init__(self, monsters: tuple[object, ...]) -> None:
        self.monsters = monsters

    def list_kind(self, kind: str, *, source: str | None = None) -> tuple[object, ...]:
        assert kind == "monster"
        assert source == "srd5.1"
        return self.monsters


def _monster_data(index: str = "test-beast", monster_type: str = "beast") -> dict[str, object]:
    return {
        "index": index,
        "name": "Test Beast",
        "size": "Medium",
        "type": monster_type,
        "alignment": "unaligned",
        "armor_class": [{"type": "natural", "value": 12}],
        "hit_points": 7,
        "hit_dice": "2d6",
        "hit_points_roll": "2d6",
        "speed": {"walk": "30 ft."},
        "strength": 10,
        "dexterity": 10,
        "constitution": 10,
        "intelligence": 2,
        "wisdom": 10,
        "charisma": 5,
        "proficiencies": [],
        "damage_vulnerabilities": [],
        "damage_resistances": [],
        "damage_immunities": [],
        "condition_immunities": [],
        "senses": {"passive_perception": 10},
        "languages": "",
        "challenge_rating": 0.125,
        "xp": 25,
        "url": f"/api/2014/monsters/{index}",
    }


def _srd_manifest(*, count: int) -> dict[str, object]:
    return {
        "id": "srd5.1",
        "name": "System Reference Document 5.1",
        "ruleset": "dnd5e-2014",
        "version": "1.0.0",
        "license": {
            "spdx": "CC-BY-4.0",
            "source": "https://example.invalid/srd",
            "license_url": "https://example.invalid/license",
            "attribution": "SRD test fixture",
        },
        "extraction": {
            "repository": "https://github.com/5e-bits/5e-database",
            "commit": "0" * 40,
            "license": "MIT",
            "license_url": "https://example.invalid/mit",
        },
        "categories": [
            {
                "name": "monsters",
                "kind": "monster",
                "file": "monsters.json",
                "upstream_file": "5e-SRD-Monsters.json",
                "count": count,
            }
        ],
        "total_entries": count,
    }


def test_p4a_registers_monster_kind() -> None:
    install_p4a_content_models()
    assert DATA_MODELS["monster"] is MonsterData


def test_srd_manifest_accepts_monsters_without_legacy_scope_guard() -> None:
    manifest = ContentManifest.model_validate(_srd_manifest(count=1))
    assert manifest.categories[0].kind == "monster"
    assert manifest.scope_guard is None


def test_registry_loads_srd_monster_category(tmp_path) -> None:
    install_p4a_content_models()
    root = tmp_path / "srd5.1"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(_srd_manifest(count=1)), encoding="utf-8"
    )
    data = _monster_data()
    (root / "monsters.json").write_text(
        json.dumps(
            [
                {
                    "key": "srd5.1:monster:test-beast",
                    "index": "test-beast",
                    "name": "Test Beast",
                    "source": "srd5.1",
                    "ruleset": "dnd5e-2014",
                    "data": data,
                }
            ]
        ),
        encoding="utf-8",
    )

    registry = ContentRegistry.from_directory(root)
    assert registry.resolve("monster", "test-beast").data["type"] == "beast"


def test_p4a_inventory_accepts_334_monsters_with_87_beasts() -> None:
    monsters = tuple(
        SimpleNamespace(data={"type": "beast" if index < EXPECTED_SRD_BEAST_COUNT else "dragon"})
        for index in range(EXPECTED_SRD_MONSTER_COUNT)
    )
    registry = _FakeRegistry(monsters)
    assert validate_p4a_monster_inventory(registry) is registry


@pytest.mark.parametrize(
    ("monster_count", "beast_count", "message"),
    [
        (EXPECTED_SRD_MONSTER_COUNT - 1, EXPECTED_SRD_BEAST_COUNT, "expected 334 SRD monsters"),
        (EXPECTED_SRD_MONSTER_COUNT, EXPECTED_SRD_BEAST_COUNT - 1, "expected 87 SRD beasts"),
    ],
)
def test_p4a_inventory_rejects_drift(
    monster_count: int,
    beast_count: int,
    message: str,
) -> None:
    monsters = tuple(
        SimpleNamespace(data={"type": "beast" if index < beast_count else "dragon"})
        for index in range(monster_count)
    )
    with pytest.raises(ContentValidationError, match=message):
        validate_p4a_monster_inventory(_FakeRegistry(monsters))
