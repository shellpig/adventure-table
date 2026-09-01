from __future__ import annotations

import json
from pathlib import Path


def _entries(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def main() -> None:
    installed_indices: dict[str, list[str]] = {}
    for path in Path("data").glob("*/*.json"):
        if path.name == "manifest.json":
            continue
        for entry in _entries(path):
            key = entry.get("key")
            index = entry.get("index")
            if not isinstance(key, str) or not isinstance(index, str):
                continue
            parts = key.split(":", 2)
            if len(parts) != 3 or parts[1] != "spell":
                continue
            installed_indices.setdefault(index, []).append(key)

    requested_by_feature: dict[str, set[str]] = {}
    for path in Path("data/tce").glob("optional-class-features-*.json"):
        for entry in _entries(path):
            key = entry.get("key")
            data = entry.get("data")
            if not isinstance(key, str) or not isinstance(data, dict):
                continue
            optional = data.get("optional_class_feature")
            if not isinstance(optional, dict):
                continue
            spell_access = optional.get("spell_access")
            if not isinstance(spell_access, dict):
                continue
            raw_indices = spell_access.get("spell_indices")
            if not isinstance(raw_indices, list):
                continue
            for index in raw_indices:
                if isinstance(index, str):
                    requested_by_feature.setdefault(key, set()).add(index)

    missing_by_feature: dict[str, list[str]] = {}
    ambiguous_by_feature: dict[str, dict[str, list[str]]] = {}
    for feature_ref, indices in sorted(requested_by_feature.items()):
        for index in sorted(indices):
            matches = installed_indices.get(index, [])
            if not matches:
                missing_by_feature.setdefault(feature_ref, []).append(index)
            elif len(matches) > 1:
                ambiguous_by_feature.setdefault(feature_ref, {})[index] = sorted(matches)

    all_missing = sorted({item for items in missing_by_feature.values() for item in items})
    print("M01_I_EXPANDED_SPELL_MISSING_COUNT", len(all_missing))
    print("M01_I_EXPANDED_SPELL_MISSING", json.dumps(all_missing, ensure_ascii=False))
    print("M01_I_EXPANDED_SPELL_MISSING_BY_FEATURE", json.dumps(missing_by_feature, ensure_ascii=False, sort_keys=True))
    print("M01_I_EXPANDED_SPELL_AMBIGUOUS", json.dumps(ambiguous_by_feature, ensure_ascii=False, sort_keys=True))
    if all_missing or ambiguous_by_feature:
        raise SystemExit("M01-I expanded spell inventory is incomplete or ambiguous")


if __name__ == "__main__":
    main()
