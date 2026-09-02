"""Materialize M01-J subclass content into physical content-pack JSON.

M01-J originally generated its runtime entries by parsing the Chinese reference
documents under ``docs/暫用規則資訊`` at registry load. This script runs that
generator once, repairs the identities and names it produced, and writes the
result as ordinary pack data so the runtime can drop the parser.

Repairs applied here:

* StableKeys that captured Unicode escape residue instead of an English slug.
* StableKeys that fell back to a positional ``-option-<n>[-<level>]`` suffix.
* Canonical names left in Chinese, or carrying a ``（需要 N 級）`` level suffix.

Every English name used for a repair must come from ``name-overrides.json`` and
cite a supplied source; rows still marked ``NEEDS_SOURCE`` abort the build.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "server"))

from app.content import load_default_content_registry  # noqa: E402
from app.content.registry import (  # noqa: E402
    CONTENT_PACKS_ROOT,
    DEFAULT_CONTENT_PACKS,
    ContentRegistry,
)

OVERRIDES_PATH = Path(__file__).resolve().parent / "name-overrides.json"
PHASE = "M01-J"
KINDS = ("subclass", "feature", "level")
ENTRIES_PER_SHARD = 80
SHARD_STEMS = {"subclass": "subclasses", "feature": "features", "level": "levels"}

ESCAPE_RUN = re.compile(r"(?:-u[0-9a-f]{4})+$")
POSITIONAL = re.compile(r"-option-\d+(?:-\d+)?$")
LEVEL_SUFFIX = re.compile(r"（需要\s*(\d+)\s*級）\s*$")
CJK = re.compile(r"[㐀-鿿]")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise ValueError(f"cannot slugify {name!r}")
    return slug


def load_overrides(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    overrides = payload["overrides"]
    unsourced = sorted(
        key for key, row in overrides.items() if row.get("source") == "NEEDS_SOURCE"
    )
    if unsourced:
        raise SystemExit(
            "M01-J name overrides still need a supplied English name:\n  "
            + "\n  ".join(unsourced)
        )
    return overrides


def collect_entries(registry: Any) -> list[Any]:
    entries: list[Any] = []
    for kind in KINDS:
        for entry in registry.list_kind(kind):
            if (entry.provenance or {}).get("phase") == PHASE:
                entries.append(entry)
    return entries


def resolve_name(entry: Any, overrides: dict[str, dict[str, Any]]) -> str:
    """Return the repaired canonical English name for an entry."""

    override = overrides.get(entry.key)
    if override is not None:
        return override["name"]

    name = entry.name or ""
    stripped = LEVEL_SUFFIX.sub("", name).strip()
    if CJK.search(stripped):
        raise SystemExit(f"no supplied English name for {entry.key}: {name!r}")
    return stripped


def repaired_key(entry: Any, english_name: str) -> str:
    pack, kind, index = entry.key.split(":", 2)
    slug = slugify(english_name)
    if ESCAPE_RUN.search(index):
        index = f"{ESCAPE_RUN.sub('', index)}-{slug}"
    elif POSITIONAL.search(index):
        index = POSITIONAL.sub(f"-option-{slug}", index)
    else:
        return entry.key
    return f"{pack}:{kind}:{index}"


def rewrite(value: Any, renames: dict[str, str]) -> Any:
    if isinstance(value, str):
        return renames.get(value, value)
    if isinstance(value, (list, tuple)):
        return [rewrite(item, renames) for item in value]
    if isinstance(value, dict):
        return {
            renames.get(key, key) if isinstance(key, str) else key: rewrite(item, renames)
            for key, item in value.items()
        }
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="staging directory for generated pack data")
    parser.add_argument(
        "--overrides",
        default=str(OVERRIDES_PATH),
        help="name override table (defaults to the checked-in one)",
    )
    args = parser.parse_args()
    out_root = Path(args.out)

    overrides = load_overrides(Path(args.overrides))
    registry = load_default_content_registry()
    entries = collect_entries(registry)

    renames: dict[str, str] = {}
    names: dict[str, str] = {}

    for entry in entries:
        english = resolve_name(entry, overrides)
        names[entry.key] = english
        new_key = repaired_key(entry, english)
        if new_key != entry.key:
            renames[entry.key] = new_key

    existing = {entry.key for entry in entries}
    produced = list(renames.values())
    collisions = sorted(key for key in produced if key in existing)
    duplicates = sorted({key for key in produced if produced.count(key) > 1})
    if collisions or duplicates:
        raise SystemExit(
            f"key repair collision: collisions={collisions} duplicates={duplicates}"
        )

    generated_overlays = getattr(registry, "m01j_localization_overlays", {}) or {}

    by_file: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    locale_rows: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)

    for entry in sorted(entries, key=lambda item: item.key):
        payload = entry.model_dump(mode="python")
        key = renames.get(entry.key, entry.key)
        payload["key"] = key
        payload["index"] = key.split(":", 2)[2]
        payload["name"] = names[entry.key]
        data = rewrite(payload.get("data") or {}, renames)
        data["index"] = payload["index"]
        data["name"] = payload["name"]
        payload["data"] = data
        payload.pop("source_label", None)
        payload["provenance"] = {
            "type": "private-maintainer-normalization",
            "phase": PHASE,
            "reference": (entry.provenance or {}).get("reference_doc"),
        }
        by_file[(entry.source, entry.key.split(":", 2)[1])].append(payload)

    for (source, locale), rows in generated_overlays.items():
        if locale != "zh-TW":
            raise SystemExit(f"unexpected generated locale {locale}")
        for original_key, fields in rows.items():
            key = renames.get(original_key, original_key)
            merged = dict(fields)
            if "name" in merged:
                merged["name"] = LEVEL_SUFFIX.sub("", merged["name"]).strip()
            locale_rows[source][key] = merged

    written: list[str] = []
    for (source, kind), rows in sorted(by_file.items()):
        rows.sort(key=lambda item: item["key"])
        pack_dir = out_root / source
        pack_dir.mkdir(parents=True, exist_ok=True)
        stem = SHARD_STEMS[kind]
        shards = [
            (
                f"{stem}-m01j-{index // ENTRIES_PER_SHARD + 1:02d}.json",
                rows[index : index + ENTRIES_PER_SHARD],
            )
            for index in range(0, len(rows), ENTRIES_PER_SHARD)
        ]
        for filename, shard in shards:
            (pack_dir / filename).write_text(
                json.dumps(shard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            written.append(f"{source}/{filename} ({len(shard)})")

    for source, rows in sorted(locale_rows.items()):
        locale_dir = out_root / source / "locales" / "zh-TW"
        locale_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "locale": "zh-TW",
            "source": source,
            "review_status": "draft-human-review-required",
            "entries": {key: rows[key] for key in sorted(rows)},
        }
        (locale_dir / "m01j.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(f"{source}/locales/zh-TW/m01j.json ({len(rows)})")

    plain = ContentRegistry.from_root(CONTENT_PACKS_ROOT, DEFAULT_CONTENT_PACKS)
    patches: dict[str, dict[str, Any]] = {}
    for key in sorted(getattr(registry, "overrides", {})):
        before = plain.get_optional(key)
        after = registry.get_optional(key)
        if before is None or after is None:
            raise SystemExit(f"cannot diff M01-J override {key}")
        before_data = before.model_dump(mode="json")["data"]
        after_data = rewrite(after.model_dump(mode="json")["data"], renames)
        changed = {
            field: value
            for field, value in after_data.items()
            if before_data.get(field) != value
        }
        removed = sorted(set(before_data) - set(after_data))
        if removed:
            raise SystemExit(f"M01-J override {key} removes fields {removed}; unsupported")
        if changed:
            patches[key] = changed
    (out_root / "rules" / "dnd5e-2014").mkdir(parents=True, exist_ok=True)
    (out_root / "rules" / "dnd5e-2014" / "m01j-entry-overrides.json").write_text(
        json.dumps(
            {"schema_version": 1, "phase": PHASE, "ruleset": "dnd5e-2014", "patches": patches},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    written.append(f"rules/dnd5e-2014/m01j-entry-overrides.json ({len(patches)})")

    inventory_rows = getattr(registry, "m01j_inventory_rows", ())
    if not inventory_rows:
        raise SystemExit("generator did not expose an M01-J inventory")
    inventory = [
        {
            "source": row.source,
            "parent_class_ref": row.parent_class_ref,
            "subclass_key": row.subclass_key,
            "name": row.name,
            "zh_name": row.zh_name,
            "acquisition_class_level": row.acquisition_class_level,
            "progression_levels": list(row.progression_levels),
            "disposition": row.disposition,
            "canonical_key": row.canonical_key,
        }
        for row in sorted(inventory_rows, key=lambda item: item.subclass_key)
    ]
    rules_dir = out_root / "rules" / "dnd5e-2014"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "m01j-inventory.json").write_text(
        json.dumps(
            {"schema_version": 1, "phase": PHASE, "ruleset": "dnd5e-2014", "rows": inventory},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    written.append(f"rules/dnd5e-2014/m01j-inventory.json ({len(inventory)})")

    report = {
        "entries": len(entries),
        "renamed_keys": len(renames),
        "renames": dict(sorted(renames.items())),
        "locale_fields": sum(
            len(fields) for rows in locale_rows.values() for fields in rows.values()
        ),
        "files": written,
    }
    (out_root / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"entries={len(entries)} renamed={len(renames)} files={len(written)}")


if __name__ == "__main__":
    main()
