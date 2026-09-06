from __future__ import annotations

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_ROOT = REPO_ROOT / ".github" / "workflows"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
SERVER_TESTS_ROOT = REPO_ROOT / "apps" / "server" / "tests"

_AMBIGUOUS_UPGRADE = re.compile(r"\balembic\s+upgrade\s+head\b")


def _files(root: Path, suffixes: set[str]) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes
    )


def _ambiguous_cli_uses(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _AMBIGUOUS_UPGRADE.search(line):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line.strip()}")
    return violations


def _is_len_heads_equals_one(node: ast.Compare) -> bool:
    if not (
        isinstance(node.left, ast.Call)
        and isinstance(node.left.func, ast.Name)
        and node.left.func.id == "len"
        and len(node.left.args) == 1
        and isinstance(node.left.args[0], ast.Name)
        and node.left.args[0].id == "heads"
    ):
        return False
    return any(
        isinstance(comparator, ast.Constant) and comparator.value == 1
        for comparator in node.comparators
    )


def _python_single_head_assumptions(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "get_current_head":
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: get_current_head()"
                    )
                if node.func.attr == "upgrade" and any(
                    isinstance(argument, ast.Constant) and argument.value == "head"
                    for argument in node.args
                ):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{node.lineno}: upgrade(..., 'head')"
                    )
            if isinstance(node, ast.Compare) and _is_len_heads_equals_one(node):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: len(heads) == 1"
                )
    return violations


def test_current_web_migration_commands_use_all_heads() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "alembic upgrade heads" in compose
    assert "alembic upgrade heads" in readme
    assert "alembic upgrade head\n" not in readme
    assert "alembic upgrade head`" not in readme


def test_standalone_launcher_uses_character_head_only() -> None:
    launcher = (REPO_ROOT / "apps/server/app/launcher.py").read_text(encoding="utf-8")

    assert 'command.upgrade(config, "character@head")' in launcher
    assert 'command.upgrade(config, "heads")' not in launcher


def test_active_workflows_and_scripts_do_not_use_ambiguous_upgrade_head() -> None:
    operational_files = _files(WORKFLOW_ROOT, {".yml", ".yaml"}) + _files(
        SCRIPTS_ROOT,
        {".py", ".cmd", ".ps1", ".sh"},
    )

    assert _ambiguous_cli_uses(operational_files) == []


def test_python_operational_paths_do_not_assume_single_repository_head() -> None:
    python_files = _files(SCRIPTS_ROOT, {".py"}) + _files(SERVER_TESTS_ROOT, {".py"})

    assert _python_single_head_assumptions(python_files) == []
