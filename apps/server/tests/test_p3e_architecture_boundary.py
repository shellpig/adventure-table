from __future__ import annotations

import ast
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = SERVER_ROOT / "app" / "mcp"
AI_TOOL_FACADE = SERVER_ROOT / "app" / "domain" / "rooms" / "ai_tools.py"
WEB_ACTIONS = SERVER_ROOT / "app" / "api" / "rooms" / "exploration.py"
WEB_ROLLS = SERVER_ROOT / "app" / "api" / "rooms" / "p3c_rolls.py"
ROOM_DEPENDENCIES_MODULE = "app.api.rooms.dependencies"


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _imported_names(path: Path, module: str) -> set[str]:
    return {
        alias.name
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
    }


def test_p3e_transport_and_ai_facade_do_not_import_persistence() -> None:
    files = sorted(MCP_ROOT.glob("*.py")) + [AI_TOOL_FACADE]
    violations: dict[str, list[str]] = {}

    for path in files:
        forbidden = sorted(
            module
            for module in _imports(path)
            if module == "app.persistence" or module.startswith("app.persistence.")
        )
        if forbidden:
            violations[str(path.relative_to(SERVER_ROOT))] = forbidden

    assert violations == {}, (
        "P3-E MCP transport/application facade must delegate through existing "
        f"application/domain services instead of importing persistence: {violations}"
    )


def test_p3e_composition_reuses_same_action_roll_and_event_factories_as_web_routes() -> None:
    mcp_dependencies = _imported_names(MCP_ROOT / "dependencies.py", ROOM_DEPENDENCIES_MODULE)
    web_action_dependencies = _imported_names(WEB_ACTIONS, ROOM_DEPENDENCIES_MODULE)
    web_roll_dependencies = _imported_names(WEB_ROLLS, ROOM_DEPENDENCIES_MODULE)

    shared_action = {"get_exploration_action_service", "get_table_event_service"}
    shared_roll = {"get_roll_service", "get_table_event_service"}

    assert shared_action <= web_action_dependencies
    assert shared_action <= mcp_dependencies
    assert shared_roll <= web_roll_dependencies
    assert shared_roll <= mcp_dependencies
