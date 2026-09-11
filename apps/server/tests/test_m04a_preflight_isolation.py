from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = REPO_ROOT / "apps" / "server" / "app"
PREFLIGHT_ROOT = REPO_ROOT / "tools" / "m04a-webchat-preflight"
PREFLIGHT_PATH_MARKERS = (
    "tools.m04a-webchat-preflight",
    "tools.m04a_webchat_preflight",
    "m04a-webchat-preflight",
    "m04a_webchat_preflight",
)


def _imports(path: Path) -> list[str]:
    imported: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    return imported


def test_preflight_tool_does_not_import_app() -> None:
    violations: dict[str, list[str]] = {}
    assert PREFLIGHT_ROOT.is_dir(), f"missing M04-A preflight tool: {PREFLIGHT_ROOT}"

    for path in sorted(PREFLIGHT_ROOT.rglob("*.py")):
        imported = sorted(
            module for module in _imports(path) if module == "app" or module.startswith("app.")
        )
        if imported:
            violations[str(path.relative_to(REPO_ROOT))] = imported

    assert violations == {}, f"M04-A preflight must remain independent from Adventure Table app modules: {violations}"


def test_adventure_table_app_does_not_import_preflight_tool() -> None:
    violations: dict[str, list[str]] = {}
    assert APP_ROOT.is_dir(), f"missing Adventure Table app root: {APP_ROOT}"

    for path in sorted(APP_ROOT.rglob("*.py")):
        imported = sorted(
            module
            for module in _imports(path)
            if any(marker in module for marker in PREFLIGHT_PATH_MARKERS)
        )
        text = path.read_text(encoding="utf-8")
        path_references = sorted(marker for marker in PREFLIGHT_PATH_MARKERS if marker in text)
        offenders = sorted(set(imported + path_references))
        if offenders:
            violations[str(path.relative_to(REPO_ROOT))] = offenders

    assert violations == {}, (
        "Adventure Table app modules must not import or reference the standalone M04-A preflight tool: "
        f"{violations}"
    )
