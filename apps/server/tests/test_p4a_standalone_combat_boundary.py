from __future__ import annotations

import ast
from pathlib import Path
import sqlite3

import pytest

from app import launcher
from tests.m03e_support import loaded_standalone


SERVER_ROOT = Path(__file__).resolve().parents[1]
CHARACTER_DOMAIN_ROOTS = (
    SERVER_ROOT / "app" / "domain" / "character",
    SERVER_ROOT / "app" / "domain" / "character_builder",
)
FORBIDDEN_COMBAT_IMPORTS = (
    "app.domain.combat",
    "app.persistence.combat",
)
FORBIDDEN_STANDALONE_TABLES = {
    "monster_templates",
    "monster_instances",
}


def _import_targets(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            module = node.module or ""
            target = f"{prefix}{module}"
            if target:
                targets.add(target)
            targets.update(f"{target}.{alias.name}" for alias in node.names if target)

    return targets


def _is_combat_import(target: str) -> bool:
    normalized = target.lstrip(".")
    if normalized == "combat" or normalized.startswith("combat."):
        return True
    if normalized == "persistence.combat" or normalized.startswith("persistence.combat."):
        return True
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_COMBAT_IMPORTS
    )


def test_standalone_character_migration_does_not_create_p4a_combat_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "standalone.sqlite3"
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", str(db_path))

    launcher.upgrade_standalone_database()

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert "characters" in tables
    assert tables.isdisjoint(FORBIDDEN_STANDALONE_TABLES)


def test_standalone_exposes_no_combat_api_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        api_paths = set(standalone.app.openapi()["paths"])

    assert all("/combat" not in path for path in api_paths)
    assert all("/monster-instances" not in path for path in api_paths)


def test_character_core_does_not_import_combat_modules() -> None:
    violations: list[str] = []

    for root in CHARACTER_DOMAIN_ROOTS:
        assert root.is_dir()
        for path in root.rglob("*.py"):
            for target in _import_targets(path):
                if _is_combat_import(target):
                    violations.append(f"{path.relative_to(SERVER_ROOT)} -> {target}")

    assert violations == []
