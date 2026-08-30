from __future__ import annotations

import json
from pathlib import Path

from app.content.identity import reference_to_stable_key
from app.content.registry import ContentRegistry
from app.content.schemas import ContentEntry
from app.domain.character_builder.multiclass import multiclass_prerequisites
from app.domain.character_builder.progression import _level_features
from app.domain.character_builder.structural import asi_occurrences_at_class_level


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _entry(
    source: str,
    kind: str,
    index: str,
    name: str,
    data: dict[str, object],
) -> dict[str, object]:
    return {
        "key": f"{source}:{kind}:{index}",
        "index": index,
        "name": name,
        "source": source,
        "ruleset": "dnd5e-2014",
        "data": {"index": index, "name": name, **data},
    }


def test_class_level_and_feature_lookup_stay_in_class_source(tmp_path: Path) -> None:
    root = tmp_path / "pack-class"
    root.mkdir()

    class_ref = "pack-class:class:test-class"
    feature_ref = "pack-class:feature:test-feature"
    class_entry = _entry(
        "pack-class",
        "class",
        "test-class",
        "Test Class",
        {
            "hit_die": 8,
            "saving_throws": [],
            "subclasses": [],
        },
    )
    feature_entry = _entry(
        "pack-class",
        "feature",
        "test-feature",
        "Test Feature",
        {},
    )
    level_entry = _entry(
        "pack-class",
        "level",
        "test-class-1",
        "Test Class 1",
        {
            "level": 1,
            "prof_bonus": 2,
            "ability_score_bonuses": 0,
            "features": [{"key": feature_ref, "name": "Test Feature"}],
            "class": {"key": class_ref, "name": "Test Class"},
        },
    )

    _write_json(root / "classes.json", [class_entry])
    _write_json(root / "features.json", [feature_entry])
    _write_json(root / "levels.json", [level_entry])
    _write_json(
        root / "manifest.json",
        {
            "id": "pack-class",
            "name": "Fixture Class Pack",
            "ruleset": "dnd5e-2014",
            "categories": [
                {"name": "classes", "kind": "class", "file": "classes.json", "count": 1},
                {"name": "features", "kind": "feature", "file": "features.json", "count": 1},
                {"name": "levels", "kind": "level", "file": "levels.json", "count": 1},
            ],
            "total_entries": 3,
        },
    )

    registry = ContentRegistry.from_directory(root)

    assert _level_features(registry, class_ref, 1) == (feature_ref,)
    assert asi_occurrences_at_class_level(registry, class_ref, 1) == 0


def test_multiclass_prerequisite_accepts_explicit_non_srd_ability_key() -> None:
    class_entry = ContentEntry.model_validate(
        _entry(
            "pack-class",
            "class",
            "test-class",
            "Test Class",
            {
                "hit_die": 8,
                "saving_throws": [],
                "subclasses": [],
                "multi_classing": {
                    "prerequisites": [
                        {
                            "ability_score": {
                                "key": "pack-class:ability:int",
                                "name": "INT",
                            },
                            "minimum_score": 13,
                        }
                    ]
                },
            },
        )
    )

    prerequisites = multiclass_prerequisites(class_entry)

    assert len(prerequisites) == 1
    assert prerequisites[0].ability == "intelligence"
    assert prerequisites[0].minimum_score == 13


def test_nested_legacy_api_endpoint_is_not_misclassified_as_content_reference() -> None:
    assert (
        reference_to_stable_key(
            {
                "index": "cleric-1",
                "name": "Cleric Level 1",
                "url": "/api/2014/classes/cleric/levels/1",
            }
        )
        is None
    )
