"""Vendor the pinned D&D 5e 2014 SRD dataset into normalized Adventure Table files.

This is a maintainer tool, not a runtime dependency. The generated files are committed
so application startup never needs network access.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

UPSTREAM_COMMIT = "ce47a18dfeb3e41a1b2a2dfe00a25761c3c3a4f1"
UPSTREAM_REPOSITORY = "https://github.com/5e-bits/5e-database"
RAW_BASE = (
    "https://raw.githubusercontent.com/5e-bits/5e-database/"
    f"{UPSTREAM_COMMIT}/src/2014/en"
)
OUTPUT_ROOT = Path(__file__).resolve().parents[1] / "data" / "srd5.1"

CATEGORIES = (
    ("abilities", "ability", "5e-SRD-Ability-Scores.json"),
    ("alignments", "alignment", "5e-SRD-Alignments.json"),
    ("backgrounds", "background", "5e-SRD-Backgrounds.json"),
    ("classes", "class", "5e-SRD-Classes.json"),
    ("conditions", "condition", "5e-SRD-Conditions.json"),
    ("damage-types", "damage-type", "5e-SRD-Damage-Types.json"),
    ("equipment-categories", "equipment-category", "5e-SRD-Equipment-Categories.json"),
    ("equipment", "equipment", "5e-SRD-Equipment.json"),
    ("feats", "feat", "5e-SRD-Feats.json"),
    ("features", "feature", "5e-SRD-Features.json"),
    ("languages", "language", "5e-SRD-Languages.json"),
    ("levels", "level", "5e-SRD-Levels.json"),
    ("items", "item", "5e-SRD-Magic-Items.json"),
    ("magic-schools", "magic-school", "5e-SRD-Magic-Schools.json"),
    ("proficiencies", "proficiency", "5e-SRD-Proficiencies.json"),
    ("races", "race", "5e-SRD-Races.json"),
    ("skills", "skill", "5e-SRD-Skills.json"),
    ("spells", "spell", "5e-SRD-Spells.json"),
    ("subclasses", "subclass", "5e-SRD-Subclasses.json"),
    ("subraces", "subrace", "5e-SRD-Subraces.json"),
    ("traits", "trait", "5e-SRD-Traits.json"),
    ("weapon-properties", "weapon-property", "5e-SRD-Weapon-Properties.json"),
)

ATTRIBUTION = (
    'Contains material from the System Reference Document 5.1 ("SRD 5.1") '
    "by Wizards of the Coast LLC. SRD 5.1 is used under CC BY 4.0."
)


def fetch_json(filename: str) -> list[dict]:
    request = Request(
        f"{RAW_BASE}/{filename}",
        headers={"User-Agent": "Adventure-Table-SRD-Vendor/1.0"},
    )
    with urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise TypeError(f"{filename} must contain a JSON array")
    return payload


def entry_name(raw: dict) -> str:
    name = raw.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    class_ref = raw.get("class")
    level = raw.get("level")
    if isinstance(class_ref, dict) and class_ref.get("name") and isinstance(level, int):
        return f"{class_ref['name']} Level {level}"
    raise ValueError(f"entry {raw.get('index')!r} has no usable name")


def normalize(kind: str, raw: dict) -> dict:
    index = raw.get("index")
    if not isinstance(index, str) or not index.strip():
        raise ValueError(f"{kind} entry missing non-empty index")
    index = index.strip()
    return {
        "key": f"srd5.1:{kind}:{index}",
        "index": index,
        "name": entry_name(raw),
        "source": "srd5.1",
        "ruleset": "dnd5e-2014",
        "license": "CC-BY-4.0",
        "data": raw,
    }


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    category_manifest = []
    total_entries = 0

    for filename, kind, upstream_filename in CATEGORIES:
        raw_entries = fetch_json(upstream_filename)
        normalized = [normalize(kind, raw) for raw in raw_entries]
        write_json(OUTPUT_ROOT / f"{filename}.json", normalized)
        total_entries += len(normalized)
        category_manifest.append(
            {
                "name": filename,
                "kind": kind,
                "file": f"{filename}.json",
                "upstream_file": upstream_filename,
                "count": len(normalized),
            }
        )

    manifest = {
        "id": "srd5.1",
        "name": "System Reference Document 5.1",
        "ruleset": "dnd5e-2014",
        "license": {
            "spdx": "CC-BY-4.0",
            "source": "https://www.dndbeyond.com/srd",
            "license_url": "https://creativecommons.org/licenses/by/4.0/legalcode",
            "attribution": ATTRIBUTION,
        },
        "extraction": {
            "repository": UPSTREAM_REPOSITORY,
            "commit": UPSTREAM_COMMIT,
            "license": "MIT",
            "license_url": f"{UPSTREAM_REPOSITORY}/blob/{UPSTREAM_COMMIT}/LICENSE.md",
        },
        "categories": category_manifest,
        "total_entries": total_entries,
        "scope_guard": {
            "excluded_categories": ["monsters", "beasts"],
            "deferred_to": "P4-A",
        },
    }
    write_json(OUTPUT_ROOT / "manifest.json", manifest)

    notice = (
        "# SRD 5.1 attribution\n\n"
        f"{ATTRIBUTION}\n\n"
        "- SRD source: https://www.dndbeyond.com/srd\n"
        "- CC BY 4.0: https://creativecommons.org/licenses/by/4.0/legalcode\n"
        f"- Structured extraction source: {UPSTREAM_REPOSITORY} @ {UPSTREAM_COMMIT}\n"
        "- Extraction project license: MIT. Copyright 2018-2020 Adrian Padua, Christopher Ward.\n"
        f"- Extraction license text: {UPSTREAM_REPOSITORY}/blob/{UPSTREAM_COMMIT}/LICENSE.md\n\n"
        "The Adventure Table normalization adds stable keys and source metadata. "
        "Monster and Beast stat blocks are intentionally not vendored in P0.\n"
    )
    (OUTPUT_ROOT / "NOTICE.md").write_text(notice, encoding="utf-8")

    print(f"Vendored {total_entries} entries across {len(CATEGORIES)} categories.")


if __name__ == "__main__":
    main()
