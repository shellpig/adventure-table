from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PREFLIGHT_ROOT = REPO_ROOT / "tools" / "m04a-webchat-preflight"


def test_preflight_tool_does_not_import_app() -> None:
    violations: dict[str, list[str]] = {}
    assert PREFLIGHT_ROOT.is_dir(), f"missing M04-A preflight tool: {PREFLIGHT_ROOT}"

    for path in sorted(PREFLIGHT_ROOT.rglob("*.py")):
        imported: list[str] = []
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names if alias.name == "app" or alias.name.startswith("app."))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "app" or node.module.startswith("app."):
                    imported.append(node.module)
        if imported:
            violations[str(path.relative_to(REPO_ROOT))] = sorted(imported)

    assert violations == {}, f"M04-A preflight must remain independent from Adventure Table app modules: {violations}"
