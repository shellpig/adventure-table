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


def test_legacy_path_constants_and_registry_imports_cannot_return() -> None:
    failures: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                for name in _assigned_names(node) & BANNED_NAMES:
                    failures.append(f"{path}: assigns banned {name}")
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Attribute) and target.attr == "DEFAULT_CONTENT_PACKS":
                        failures.append(f"{path}: monkey-patches DEFAULT_CONTENT_PACKS")
            if isinstance(node, ast.ImportFrom) and node.module == "app.content.registry":
                imported = {alias.name for alias in node.names}
                for name in imported & BANNED_REGISTRY_IMPORTS:
                    failures.append(f"{path}: imports banned registry constant {name}")

    assert failures == []


def test_repository_parent_index_derivation_is_confined_to_paths_module() -> None:
    failures: list[str] = []
    allowed = (_server_root() / "app" / "paths.py").resolve()
    for path in _production_python_files():
        if path.resolve() == allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "parents":
                failures.append(
                    f"{path}: indexed .parents path derivation outside app.paths at line {node.lineno}"
                )

    assert failures == []


def test_content_package_keeps_model_installers_but_not_pack_monkey_patch() -> None:
    path = _server_root() / "app" / "content" / "__init__.py"
    source = path.read_text(encoding="utf-8")

    assert "install_m01l_content_models()" in source
    assert "install_m01m_content_models()" in source
    assert "_registry.DEFAULT_CONTENT_PACKS" not in source
