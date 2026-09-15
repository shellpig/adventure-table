from __future__ import annotations

import json

import pytest

from app.content.p4a_import_monsters import (
    MonsterImportError,
    build_monster_entries,
    git_blob_sha,
    parse_monster_source,
    render_monster_entries,
    validate_monster_inventory,
    verify_pinned_source,
)


def _monster(index: str, monster_type: str = "dragon") -> dict[str, object]:
    return {
        "index": index,
        "name": index.replace("-", " ").title(),
        "type": monster_type,
        "url": f"/api/2014/monsters/{index}",
    }


def test_git_blob_sha_matches_git_object_format() -> None:
    assert git_blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


def test_pinned_source_rejects_wrong_blob() -> None:
    with pytest.raises(MonsterImportError, match="source blob mismatch"):
        verify_pinned_source(b"not-the-pinned-monster-file")


def test_parse_source_requires_json_array_of_objects() -> None:
    assert parse_monster_source(json.dumps([_monster("wolf")]).encode()) == [
        _monster("wolf")
    ]
    with pytest.raises(MonsterImportError, match="JSON array"):
        parse_monster_source(b'{"index":"wolf"}')
    with pytest.raises(MonsterImportError, match="must be a JSON object"):
        parse_monster_source(b'["wolf"]')


def test_build_entries_is_sorted_and_preserves_raw_monster_data() -> None:
    source = [_monster("young-red-dragon"), _monster("ape", "beast")]
    entries = build_monster_entries(source)

    assert [entry["index"] for entry in entries] == ["ape", "young-red-dragon"]
    assert entries[0] == {
        "key": "srd5.1:monster:ape",
        "index": "ape",
        "name": "Ape",
        "source": "srd5.1",
        "ruleset": "dnd5e-2014",
        "license": "CC-BY-4.0",
        "data": source[1],
    }
    assert render_monster_entries(entries) == render_monster_entries(
        build_monster_entries(source)
    )


def test_build_entries_rejects_duplicate_index() -> None:
    with pytest.raises(MonsterImportError, match="duplicate SRD Monster index"):
        build_monster_entries([_monster("ape"), _monster("ape")])


def test_inventory_requires_exact_p4a_counts() -> None:
    monsters = [
        _monster(str(index), "beast" if index < 87 else "dragon")
        for index in range(334)
    ]
    validate_monster_inventory(monsters)

    with pytest.raises(MonsterImportError, match="expected 334 SRD monsters"):
        validate_monster_inventory(monsters[:-1])

    monsters[86] = _monster("86", "dragon")
    with pytest.raises(MonsterImportError, match="expected 87 SRD beasts"):
        validate_monster_inventory(monsters)
