from __future__ import annotations

import ast
from pathlib import Path


BANNED_NAMES = {
    "REPOSITORY_ROOT",
    "CONTENT_PACKS_ROOT",
    "DEFAULT_CONTENT_ROOT",
    "DEFAULT_SRD_CONTENT_ROOT",
    "DEFAULT_CONTENT_PACKS",
    "RULES_PATH",
}
BANNED_REGISTRY_IMPORTS = BANNED_NAMES - {"RULES_PATH"}


def _server_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _production_python_files() -> tuple[Path, ...]:
    server_root = _server_root()
    files = list((server_root / "app").rglob("*.py"))
    files.append(server_root / "alembic" / "env.py")
    return tuple(sorted(files))


def _assigned_names(node: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    result: set[str] = set()
    for target in targets:
        if isinstance(target, ast.Name):
            result.add(target.id)
    return result


def _legacy_contract_failures(source: str, label: str) -> list[str]:
    tree = ast.parse(source, filename=label)
    failures: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            for name in _assigned_names(node) & BANNED_NAMES:
                failures.append(f"{label}: assigns banned {name}")
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "DEFAULT_CONTENT_PACKS":
                    failures.append(f"{label}: monkey-patches DEFAULT_CONTENT_PACKS")
        if isinstance(node, ast.ImportFrom) and node.module == "app.content.registry":
            imported = {alias.name for alias in node.names}
            for name in imported & BANNED_REGISTRY_IMPORTS:
                failures.append(f"{label}: imports banned registry constant {name}")
    return failures


def _parent_index_failures(source: str, label: str) -> list[str]:
    tree = ast.parse(source, filename=label)
    failures: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        value = node.value
        index = node.slice
        if (
            isinstance(value, ast.Attribute)
            and value.attr == "parents"
            and isinstance(index, ast.Constant)
            and isinstance(index.value, int)
            and index.value >= 3
        ):
            failures.append(
                f"{label}: indexed .parents[{index.value}] repo-root derivation at line {node.lineno}"
            )
    return failures


def test_legacy_path_constants_and_registry_imports_cannot_return() -> None:
    failures: list[str] = []
    for path in _production_python_files():
        failures.extend(_legacy_contract_failures(path.read_text(encoding="utf-8"), str(path)))
    assert failures == []


def test_repository_parent_index_derivation_is_confined_to_paths_module() -> None:
    failures: list[str] = []
    allowed = (_server_root() / "app" / "paths.py").resolve()
    for path in _production_python_files():
        if path.resolve() == allowed:
            continue
        failures.extend(_parent_index_failures(path.read_text(encoding="utf-8"), str(path)))
    assert failures == []


def test_content_package_keeps_model_installers_but_not_pack_monkey_patch() -> None:
    path = _server_root() / "app" / "content" / "__init__.py"
    source = path.read_text(encoding="utf-8")

    assert "install_m01l_content_models()" in source
    assert "install_m01m_content_models()" in source
    assert "_registry.DEFAULT_CONTENT_PACKS" not in source


def test_static_sweep_counterexample_detects_constant_import_and_monkey_patch() -> None:
    source = """
from app.content.registry import CONTENT_PACKS_ROOT
DEFAULT_CONTENT_ROOT = CONTENT_PACKS_ROOT / "srd5.1"
_registry.DEFAULT_CONTENT_PACKS = ("srd5.1",)
"""
    failures = _legacy_contract_failures(source, "counterexample.py")

    assert any("imports banned registry constant CONTENT_PACKS_ROOT" in item for item in failures)
    assert any("assigns banned DEFAULT_CONTENT_ROOT" in item for item in failures)
    assert any("monkey-patches DEFAULT_CONTENT_PACKS" in item for item in failures)


def test_static_sweep_counterexample_detects_repo_parent_derivation() -> None:
    source = "ROOT = Path(__file__).resolve().parents[3] / 'data'\n"

    failures = _parent_index_failures(source, "counterexample.py")
    assert failures == [
        "counterexample.py: indexed .parents[3] repo-root derivation at line 1"
    ]
