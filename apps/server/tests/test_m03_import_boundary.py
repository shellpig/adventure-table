from __future__ import annotations

import ast
from collections import deque
from pathlib import Path
import re


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN_MODULE_RE = re.compile(r"(room|session|seat|campaign|party_roster)", re.IGNORECASE)

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


def _module_name(path: Path) -> str:
    relative = path.relative_to(APP_ROOT)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("app", *parts))


def _module_index() -> dict[str, Path]:
    return {_module_name(path): path for path in APP_ROOT.rglob("*.py")}


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


def test_character_distribution_import_graph_has_no_multiplayer_dependencies() -> None:
    index = _module_index()
    seeds = _protected_seeds(index)
    graph = _reachable_import_graph(index, seeds)

    violations = sorted(
        (source, imported)
        for source, imported_modules in graph.items()
        for imported in imported_modules
        if imported.startswith("app.") and FORBIDDEN_MODULE_RE.search(imported)
    )

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
