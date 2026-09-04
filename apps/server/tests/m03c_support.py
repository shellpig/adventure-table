from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.content.registry import ContentRegistry
from app.interop.character_import import CharacterImportService
from app.paths import resolve_content_root
from app.persistence.builder_drafts import character_build_drafts
from app.persistence.character_imports import character_import_records
from app.persistence.characters import characters, character_states, character_versions
from sqlalchemy import func, select
from test_p1f_character_creation import _seed


FIXTURE_ROOT = Path(__file__).parent / "data" / "m03"


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def document(name: str = "fixture_low_level_srd.json") -> dict[str, Any]:
    return copy.deepcopy(fixture(name))


def seeded_import(*, disabled_pack: str | None = None):
    client, engine = _seed()
    registry = client.app.state.content_registry
    if disabled_pack is not None:
        enabled = tuple(
            pack for pack in registry.enabled_pack_ids if pack != disabled_pack
        )
        registry = ContentRegistry.from_root(resolve_content_root(), enabled)
    client.app.state.content_registry = registry
    client.app.state.character_import_service = CharacterImportService(engine, registry)
    return client, engine, registry


def post_document(client, payload: dict[str, Any], *, dry_run: bool = False):
    suffix = "?dry_run=true" if dry_run else ""
    return client.post(
        f"/api/characters/import{suffix}",
        content=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )


def table_counts(engine) -> dict[str, int]:
    tables = {
        "characters": characters,
        "character_versions": character_versions,
        "character_states": character_states,
        "character_import_records": character_import_records,
        "character_build_drafts": character_build_drafts,
    }
    with engine.connect() as connection:
        return {
            name: int(connection.scalar(select(func.count(table.c.id))) or 0)
            if "id" in table.c
            else int(connection.scalar(select(func.count()).select_from(table)) or 0)
            for name, table in tables.items()
        }
