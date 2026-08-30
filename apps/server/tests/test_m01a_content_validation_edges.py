from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.content.identity import parse_stable_key
from app.content.registry import ContentRegistry, ContentValidationError
from app.domain.character.schemas import require_stable_key
from test_m01a_content_packs import feature, write_json, write_pack


def test_missing_manifest_category_file_fails_fast(tmp_path: Path) -> None:
    pack_root = write_pack(
        tmp_path,
        "pack-a",
        "Pack A",
        {"features": ("feature", [feature("pack-a", "one", "One")])},
    )
    (pack_root / "features.json").unlink()

    with pytest.raises(ContentValidationError, match="cannot load category features"):
        ContentRegistry.from_directory(pack_root)


def test_manifest_total_mismatch_fails_fast(tmp_path: Path) -> None:
    pack_root = write_pack(
        tmp_path,
        "pack-a",
        "Pack A",
        {"features": ("feature", [feature("pack-a", "one", "One")])},
    )
    manifest_path = pack_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["total_entries"] = 2
    write_json(manifest_path, manifest)

    with pytest.raises(ContentValidationError, match="invalid content manifest"):
        ContentRegistry.from_directory(pack_root)


@pytest.mark.parametrize(
    "value",
    (
        "pack-a:race",
        "pack-a:race:goblin:extra",
        ":race:goblin",
        "pack-a::goblin",
        "pack-a:race:",
        "Pack-A:race:goblin",
    ),
)
def test_malformed_stable_keys_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        parse_stable_key(value)


def test_character_reference_rejects_malformed_source() -> None:
    with pytest.raises(ValueError):
        require_stable_key("Pack-A:race:goblin", kinds={"race"})
