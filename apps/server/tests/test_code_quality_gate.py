from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# Patterns the worker prompts used to forbid by hand. New occurrences fail here
# instead; existing debt is frozen per file in BASELINE and may only go down.
GETATTR_DEFAULT = "getattr-with-default"
ANY_TYPE = "bare-Any-annotation"
SWALLOWED_EXCEPT = "except-without-raise"

REASONS = {
    GETATTR_DEFAULT: "use the real type instead of probing attributes with getattr(obj, name, default)",
    ANY_TYPE: "annotate the parameter/return/variable with the real type instead of bare Any",
    SWALLOWED_EXCEPT: "a bare/broad except must re-raise (map to a domain error) instead of swallowing",
}

BROAD_EXCEPTIONS = {"Exception", "BaseException"}

# {relative path: {pattern: count}} — regenerate a single entry with
# `python -m tests.test_code_quality_gate <relative path>` after paying down debt.
BASELINE: dict[str, dict[str, int]] = {
    "app/api/character_export.py": {"getattr-with-default": 1},
    "app/api/character_import.py": {"bare-Any-annotation": 1},
    "app/api/content_presentation.py": {"bare-Any-annotation": 1},
    "app/api/dependencies.py": {"getattr-with-default": 5},
    "app/api/rooms/access.py": {"getattr-with-default": 2},
    "app/api/rooms/ai_controllers.py": {"getattr-with-default": 1},
    "app/api/rooms/ai_oauth.py": {"getattr-with-default": 1},
    "app/api/rooms/dependencies.py": {"bare-Any-annotation": 2, "getattr-with-default": 24},
    "app/content/identity.py": {"bare-Any-annotation": 3},
    "app/content/localization.py": {"bare-Any-annotation": 4},
    "app/content/localization_files.py": {"bare-Any-annotation": 1},
    "app/content/localization_paths.py": {"bare-Any-annotation": 2},
    "app/content/m01j_closeout_validation.py": {"bare-Any-annotation": 4},
    "app/content/m01j_inventory.py": {"getattr-with-default": 8},
    "app/content/m01j_spell_closeout_validation.py": {"bare-Any-annotation": 2},
    "app/content/m01l_inventory.py": {"getattr-with-default": 1},
    "app/content/m01m_inventory.py": {"getattr-with-default": 2},
    "app/content/registry.py": {"bare-Any-annotation": 1},
    "app/domain/character/validation.py": {"getattr-with-default": 1},
    "app/domain/character_builder/__init__.py": {"bare-Any-annotation": 1},
    "app/domain/character_builder/equipment.py": {"bare-Any-annotation": 1},
    "app/domain/character_builder/m01j_extension.py": {"bare-Any-annotation": 5},
    "app/domain/character_builder/m01j_runtime.py": {"bare-Any-annotation": 2},
    "app/domain/character_builder/race_variants.py": {"getattr-with-default": 2},
    "app/domain/combat/ai_tools.py": {"bare-Any-annotation": 1},
    "app/domain/combat/spell_content_adapter.py": {"bare-Any-annotation": 1},
    "app/domain/rooms/__init__.py": {"bare-Any-annotation": 1},
    "app/domain/rooms/session_resume.py": {"bare-Any-annotation": 1, "getattr-with-default": 1},
    "app/domain/rules/artificer.py": {"bare-Any-annotation": 1, "getattr-with-default": 3},
    "app/interop/content_ref_walker.py": {"getattr-with-default": 1},
    "app/interop/json_schema.py": {"bare-Any-annotation": 1},
    "app/launcher.py": {"getattr-with-default": 4},
    "app/mcp/dependencies.py": {"getattr-with-default": 1},
    "app/mcp/oauth.py": {"except-without-raise": 1},
    "app/mcp/protocol.py": {"bare-Any-annotation": 4},
    "app/mcp/server.py": {"bare-Any-annotation": 1, "except-without-raise": 1},
    "app/mcp/tools.py": {"bare-Any-annotation": 1},
    "app/paths.py": {"getattr-with-default": 2},
    "app/persistence/combat/attacks.py": {"bare-Any-annotation": 2},
    "app/persistence/combat/monster_bookkeeping.py": {"bare-Any-annotation": 1},
    "app/persistence/combat/repository.py": {"bare-Any-annotation": 2},
    "app/persistence/combat/resolution.py": {"bare-Any-annotation": 1},
    "app/persistence/combat/special_attacks.py": {"bare-Any-annotation": 24},
    "app/persistence/combat/spells.py": {"bare-Any-annotation": 2},
}


def _handler_is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(name, ast.Name) and name.id in BROAD_EXCEPTIONS for name in names)


def _body_raises(body: list[ast.stmt]) -> bool:
    return any(isinstance(node, ast.Raise) for stmt in body for node in ast.walk(stmt))


def _all_args(args: ast.arguments) -> list[ast.arg]:
    extra = [arg for arg in (args.vararg, args.kwarg) if arg is not None]
    return [*args.posonlyargs, *args.args, *args.kwonlyargs, *extra]


def _is_bare_any(annotation: ast.expr | None) -> bool:
    # `dict[str, Any]` for JSON payloads is the codebase idiom; only a whole
    # annotation of `Any` hides the real type (same scope as ruff ANN401).
    if isinstance(annotation, ast.Name):
        return annotation.id == "Any"
    return isinstance(annotation, ast.Attribute) and annotation.attr == "Any"


def _violations(source: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "getattr" and len(node.args) == 3:
                found.append((node.lineno, GETATTR_DEFAULT))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations = [arg.annotation for arg in _all_args(node.args)] + [node.returns]
            found.extend((node.lineno, ANY_TYPE) for ann in annotations if _is_bare_any(ann))
        elif isinstance(node, ast.AnnAssign) and _is_bare_any(node.annotation):
            found.append((node.lineno, ANY_TYPE))
        elif isinstance(node, ast.ExceptHandler) and _handler_is_broad(node):
            if not _body_raises(node.body):
                found.append((node.lineno, SWALLOWED_EXCEPT))
    return found


def _scan(app_root: Path = APP_ROOT) -> dict[str, list[tuple[int, str]]]:
    return {
        path.relative_to(app_root.parent).as_posix(): _violations(path.read_text(encoding="utf-8"))
        for path in sorted(app_root.rglob("*.py"))
    }


def test_no_new_defensive_patterns() -> None:
    report: list[str] = []
    for relative, found in _scan().items():
        counts = Counter(pattern for _, pattern in found)
        allowed = BASELINE.get(relative, {})
        for pattern in sorted(set(counts) | set(allowed)):
            actual, limit = counts[pattern], allowed.get(pattern, 0)
            if actual > limit:
                lines = ", ".join(str(line) for line, kind in found if kind == pattern)
                report.append(
                    f"{relative}: {actual} x {pattern} (baseline {limit}) at line(s) {lines} — {REASONS[pattern]}"
                )
            elif actual < limit:
                report.append(
                    f"{relative}: {pattern} dropped to {actual} (baseline {limit}) — lower the BASELINE entry"
                )
    assert not report, "\n".join(report)


def test_baseline_only_lists_existing_files() -> None:
    missing = sorted(relative for relative in BASELINE if not (APP_ROOT.parent / relative).is_file())
    assert not missing, f"remove stale BASELINE entries: {missing}"


if __name__ == "__main__":
    import sys

    wanted = set(sys.argv[1:])
    for relative, found in _scan().items():
        counts = Counter(pattern for _, pattern in found)
        if counts and (not wanted or relative in wanted):
            body = ", ".join(f'"{pattern}": {count}' for pattern, count in sorted(counts.items()))
            print(f'    "{relative}": {{{body}}},')
