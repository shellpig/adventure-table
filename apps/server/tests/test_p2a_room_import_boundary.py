from __future__ import annotations

from pathlib import Path

from test_m03_import_boundary import (
    _forbidden_violations,
    _module_index,
    _reachable_import_graph,
)


def test_p2a_boundary_fixture_detects_actual_rooms_package_spellings(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    for package in (
        app_root,
        app_root / "api",
        app_root / "api" / "rooms",
        app_root / "domain",
        app_root / "domain" / "rooms",
        app_root / "domain" / "character",
        app_root / "content",
    ):
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("", encoding="utf-8")

    (app_root / "api" / "rooms" / "characters.py").write_text("VALUE = 1\n", encoding="utf-8")
    (app_root / "domain" / "rooms" / "sessions.py").write_text("VALUE = 2\n", encoding="utf-8")
    (app_root / "content" / "roommate.py").write_text("VALUE = 3\n", encoding="utf-8")
    (app_root / "domain" / "character" / "fixture.py").write_text(
        "import app.api.rooms.characters\n"
        "import app.domain.rooms.sessions\n"
        "import app.content.roommate\n",
        encoding="utf-8",
    )

    index = _module_index(app_root)
    graph = _reachable_import_graph(index, {"app.domain.character.fixture"})
    violations = _forbidden_violations(graph)
    flagged = {imported for _, imported in violations}

    assert "app.api.rooms.characters" in flagged
    assert "app.domain.rooms.sessions" in flagged
    assert "app.content.roommate" not in flagged


def test_production_standalone_graph_does_not_reach_p2a_rooms_modules() -> None:
    index = _module_index()
    graph = _reachable_import_graph(index, {"app.standalone"})
    reached = {
        imported
        for imported_modules in graph.values()
        for imported in imported_modules
        if imported.startswith("app.") and ".rooms" in imported
    }
    assert not reached, sorted(reached)
