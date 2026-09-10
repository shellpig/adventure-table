from __future__ import annotations

import ast
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = SERVER_ROOT / "app" / "mcp"
AI_TOOL_FACADE = SERVER_ROOT / "app" / "domain" / "rooms" / "ai_tools.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


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


def test_p3e_dependency_composition_reuses_existing_room_service_factory() -> None:
    dependencies = (MCP_ROOT / "dependencies.py").read_text(encoding="utf-8")
    tree = ast.parse(dependencies, filename=str(MCP_ROOT / "dependencies.py"))

    imported_from_room_dependencies = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.api.rooms.dependencies"
        for alias in node.names
    }

    assert "get_room_services" in imported_from_room_dependencies
    assert "RoomServices" in imported_from_room_dependencies
