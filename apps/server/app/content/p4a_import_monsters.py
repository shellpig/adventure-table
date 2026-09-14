from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from app.content.p4a_inventory import (
    EXPECTED_SRD_BEAST_COUNT,
    EXPECTED_SRD_MONSTER_COUNT,
)

PINNED_UPSTREAM_REPOSITORY = "https://github.com/5e-bits/5e-database"
PINNED_UPSTREAM_COMMIT = "ce47a18dfeb3e41a1b2a2dfe00a25761c3c3a4f1"
PINNED_UPSTREAM_FILE = "src/2014/en/5e-SRD-Monsters.json"
PINNED_UPSTREAM_BLOB_SHA = "4193e12e8be65e3c97da4787f5591233c4333111"


class MonsterImportError(ValueError):
    pass


def git_blob_sha(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def verify_pinned_source(
    payload: bytes,
    *,
    expected_blob_sha: str = PINNED_UPSTREAM_BLOB_SHA,
) -> None:
    actual = git_blob_sha(payload)
    if actual != expected_blob_sha:
        raise MonsterImportError(
            "SRD Monster source blob mismatch: "
            f"expected {expected_blob_sha}, got {actual}. "
            f"Use {PINNED_UPSTREAM_REPOSITORY}@{PINNED_UPSTREAM_COMMIT}:"
            f"{PINNED_UPSTREAM_FILE}"
        )


def parse_monster_source(payload: bytes) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MonsterImportError(f"invalid SRD Monster JSON: {exc}") from exc
    if not isinstance(decoded, list):
        raise MonsterImportError("SRD Monster source must be a JSON array")
    monsters: list[dict[str, Any]] = []
    for position, raw in enumerate(decoded):
        if not isinstance(raw, dict):
            raise MonsterImportError(
                f"SRD Monster source item {position} must be a JSON object"
            )
        monsters.append(raw)
    return monsters


def validate_monster_inventory(
    monsters: Sequence[dict[str, Any]],
    *,
    expected_count: int = EXPECTED_SRD_MONSTER_COUNT,
    expected_beast_count: int = EXPECTED_SRD_BEAST_COUNT,
) -> None:
    if len(monsters) != expected_count:
        raise MonsterImportError(
            f"expected {expected_count} SRD monsters, got {len(monsters)}"
        )
    beast_count = sum(
        1
        for monster in monsters
        if isinstance(monster.get("type"), str)
        and monster["type"].casefold() == "beast"
    )
    if beast_count != expected_beast_count:
        raise MonsterImportError(
            f"expected {expected_beast_count} SRD beasts, got {beast_count}"
        )


def build_monster_entries(
    monsters: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_indexes: set[str] = set()
    for position, monster in enumerate(monsters):
        index = monster.get("index")
        name = monster.get("name")
        if not isinstance(index, str) or not index:
            raise MonsterImportError(
                f"SRD Monster source item {position} has invalid index"
            )
        if not isinstance(name, str) or not name:
            raise MonsterImportError(f"SRD Monster {index!r} has invalid name")
        if index in seen_indexes:
            raise MonsterImportError(f"duplicate SRD Monster index: {index}")
        seen_indexes.add(index)
        entries.append(
            {
                "key": f"srd5.1:monster:{index}",
                "index": index,
                "name": name,
                "source": "srd5.1",
                "ruleset": "dnd5e-2014",
                "license": "CC-BY-4.0",
                "data": monster,
            }
        )
    entries.sort(key=lambda entry: entry["index"])
    return entries


def render_monster_entries(entries: Sequence[dict[str, Any]]) -> str:
    return json.dumps(
        list(entries),
        ensure_ascii=False,
        indent=2,
        separators=(",", ": "),
    ) + "\n"


def import_pinned_monsters(source_path: Path, destination_path: Path) -> int:
    payload = source_path.read_bytes()
    verify_pinned_source(payload)
    monsters = parse_monster_source(payload)
    validate_monster_inventory(monsters)
    entries = build_monster_entries(monsters)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(render_monster_entries(entries), encoding="utf-8")
    return len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import the pinned SRD 5.1 Monster dataset into Adventure Table."
    )
    parser.add_argument("source", type=Path, help="Pinned 5e-database Monsters JSON")
    parser.add_argument("destination", type=Path, help="Output monsters.json")
    args = parser.parse_args()
    count = import_pinned_monsters(args.source, args.destination)
    print(f"wrote {count} monsters to {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
