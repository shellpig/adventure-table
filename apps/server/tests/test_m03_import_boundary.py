from __future__ import annotations

import ast
from collections import deque
from pathlib import Path
import re


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN_MODULE_RE = re.compile(
    r"(?:^|\.)(?:rooms?|sessions?|seats?|campaigns?|party_rosters?)(?:\.|$)",
    re.IGNORECASE,
)

EXACT_PROTECTED_MODULES = {
    "app.persistence.characters",
    "app.persistence.builder_drafts",
    "app.persistence.state_mutations",
    "app.api.characters",
    "app.api.character_builder",
    "app.api.reference",
    "app.api.content_presentation",
    "app.api.meta",
    "app.api.error_handlers",
    "app.standalone",
}


def _module_name(path: Path, app_root: Path = APP_ROOT) -> str:
    relative = path.relative_to(app_root)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("app", *parts))


def _module_index(app_root: Path = APP_ROOT) -> dict[str, Path]:
    return {_module_name(path, app_root): path for path in app_root.rglob("*.py")}


def _protected_seeds(index: dict[str, Path]) -> set[str]:
    seeds = set(EXACT_PROTECTED_MODULES)
    seeds.update(name for name in index if name == "app.content" or name.startswith("app.content."))
    seeds.update(name for name in index if name.startswith("app.domain.character"))
    missing = sorted(seeds - index.keys())
    assert not missing, f"M03-F protected module(s) missing from source tree: {missing}"
    return seeds


def _import_base(importer: str, *, is_package: bool, level: int, module: str | None) -> str:
    if level == 0:
        return module or ""
    package_parts = importer.split(".") if is_package else importer.split(".")[:-1]
    keep = len(package_parts) - (level - 1)
    if keep < 1:
        return ""
    parts = package_parts[:keep]
    if module:
        parts.extend(module.split("."))
    return ".".join(parts)


def _imports_for(module: str, path: Path, index: dict[str, Path]) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_modules: set[str] = set()
    local_targets: set[str] = set()
    is_package = path.name == "__init__.py"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
                if alias.name in index:
                    local_targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _import_base(
                module,
                is_package=is_package,
                level=node.level,
                module=node.module,
            )
            if base:
                imported_modules.add(base)
                if base in index:
                    local_targets.add(base)
            for alias in node.names:
                if alias.name == "*" or not base:
                    continue
                candidate = f"{base}.{alias.name}"
                # ``from app.foo import CampaignThing`` imports a symbol, not a
                # module.  Only treat the candidate as a module when it really
                # exists in the local source index; the base module is already
                # recorded above and remains subject to the forbidden-name gate.
                if candidate in index:
                    imported_modules.add(candidate)
                    local_targets.add(candidate)

    return imported_modules, local_targets


def _reachable_import_graph(index: dict[str, Path], seeds: set[str]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    queue = deque(sorted(seeds))
    visited: set[str] = set()

    while queue:
        module = queue.popleft()
        if module in visited:
            continue
        visited.add(module)
        imported_modules, local_targets = _imports_for(module, index[module], index)
        graph[module] = imported_modules
        queue.extend(sorted(local_targets - visited))

    return graph


def _forbidden_violations(graph: dict[str, set[str]]) -> list[tuple[str, str]]:
    return sorted(
        (source, imported)
        for source, imported_modules in graph.items()
        for imported in imported_modules
        if imported.startswith("app.") and FORBIDDEN_MODULE_RE.search(imported)
    )


def test_character_distribution_import_graph_has_no_multiplayer_dependencies() -> None:
    index = _module_index()
    seeds = _protected_seeds(index)
    graph = _reachable_import_graph(index, seeds)
    violations = _forbidden_violations(graph)

    assert not violations, (
        "M03-F import boundary violation: standalone character/content code must remain "
        f"independent from Room/Session/Seat/Campaign modules: {violations}"
    )


def test_standalone_import_graph_never_reaches_web_entrypoint() -> None:
    index = _module_index()
    graph = _reachable_import_graph(index, {"app.standalone"})

    offenders = sorted(
        (source, imported)
        for source, imported_modules in graph.items()
        for imported in imported_modules
        if imported == "app.main" or imported.startswith("app.main.")
    )

    assert not offenders, f"app.standalone must not import or reach app.main: {offenders}"


def test_import_boundary_fixture_detects_multiplayer_module(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    (app_root / "domain").mkdir(parents=True)
    (app_root / "room").mkdir(parents=True)
    (app_root / "api").mkdir(parents=True)
    (app_root / "__init__.py").write_text("", encoding="utf-8")
    (app_root / "domain" / "__init__.py").write_text("", encoding="utf-8")
    (app_root / "room" / "__init__.py").write_text("", encoding="utf-8")
    (app_root / "room" / "fake.py").write_text("VALUE = 1\n", encoding="utf-8")
    (app_root / "api" / "__init__.py").write_text("", encoding="utf-8")
    # Plural resource module names are the likelier P2 spelling, so the gate has
    # to catch ``rooms`` as well as ``room``.
    (app_root / "api" / "rooms.py").write_text("VALUE = 2\n", encoding="utf-8")
    (app_root / "domain" / "character_fixture.py").write_text(
        "from app.room import fake\nimport app.api.rooms\n\nVALUE = fake.VALUE\n",
        encoding="utf-8",
    )

    index = _module_index(app_root)
    graph = _reachable_import_graph(index, {"app.domain.character_fixture"})
    violations = _forbidden_violations(graph)
    flagged = {imported for _, imported in violations}

    assert violations, "negative fixture must prove the M03-F boundary gate can fail"
    assert flagged & {"app.room", "app.room.fake"}
    assert "app.api.rooms" in flagged


def test_forbidden_regex_matches_module_segments_not_substrings() -> None:
    assert FORBIDDEN_MODULE_RE.search("app.room.api")
    assert FORBIDDEN_MODULE_RE.search("app.feature.session")
    assert FORBIDDEN_MODULE_RE.search("app.party_roster")
    assert FORBIDDEN_MODULE_RE.search("app.domain.session_scope") is None
    assert FORBIDDEN_MODULE_RE.search("app.content.roommate") is None


def test_forbidden_regex_matches_plural_resource_module_names() -> None:
    assert FORBIDDEN_MODULE_RE.search("app.api.rooms")
    assert FORBIDDEN_MODULE_RE.search("app.persistence.sessions")
    assert FORBIDDEN_MODULE_RE.search("app.api.seats")
    assert FORBIDDEN_MODULE_RE.search("app.domain.campaigns")
    assert FORBIDDEN_MODULE_RE.search("app.domain.party_rosters")
    assert FORBIDDEN_MODULE_RE.search("app.content.roomservice") is None
