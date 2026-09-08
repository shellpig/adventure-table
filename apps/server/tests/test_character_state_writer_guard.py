from __future__ import annotations

import ast
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
ALLOWED_STATE_UPDATE_FILES = {
    "persistence/characters.py",
    "persistence/state_mutations.py",
}


def _is_character_state_update_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if (
        isinstance(node.func, ast.Name)
        and node.func.id == "update"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "character_states"
    ):
        return True
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "update"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "character_states"
    )


def _values_calls_for_character_state_update(tree: ast.AST) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "values":
            continue
        if any(_is_character_state_update_call(child) for child in ast.walk(node.func.value)):
            calls.append(node)
    return calls


def _state_revision_guarded(values_call: ast.Call) -> bool:
    """The UPDATE expression before .values() must reference state_revision."""

    return any(
        isinstance(node, ast.Attribute) and node.attr == "state_revision"
        for node in ast.walk(values_call.func.value)
    )


def test_every_character_state_payload_update_advances_revision_and_uses_cas() -> None:
    update_sites: list[tuple[str, int]] = []
    missing_revision: list[tuple[str, int]] = []
    missing_cas_guard: list[tuple[str, int]] = []
    raw_sql_sites: list[tuple[str, int]] = []

    for path in APP_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(APP_ROOT).as_posix()
        tree = ast.parse(text, filename=str(path))

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "update character_states" in node.value.lower()
            ):
                raw_sql_sites.append((relative, node.lineno))

        for call in _values_calls_for_character_state_update(tree):
            keywords = {keyword.arg for keyword in call.keywords if keyword.arg is not None}
            if "state_payload" not in keywords:
                continue
            update_sites.append((relative, call.lineno))
            if "state_revision" not in keywords:
                missing_revision.append((relative, call.lineno))
            if not _state_revision_guarded(call):
                missing_cas_guard.append((relative, call.lineno))

    assert not raw_sql_sites, (
        "Character State writes must remain visible to the revision guard; raw UPDATE SQL "
        f"would bypass it: {raw_sql_sites}"
    )
    assert not missing_revision, (
        "Every character_states.state_payload UPDATE must advance state_revision in the "
        f"same statement: {missing_revision}"
    )
    assert not missing_cas_guard, (
        "Every character_states.state_payload UPDATE must compare the source "
        f"state_revision before replacing the payload: {missing_cas_guard}"
    )

    detected_files = {path for path, _line in update_sites}
    assert detected_files == ALLOWED_STATE_UPDATE_FILES, (
        "Character State writer surface changed. Route new writers through the shared "
        "mutation/reconciliation discipline and update this guard deliberately: "
        f"detected={sorted(detected_files)} expected={sorted(ALLOWED_STATE_UPDATE_FILES)}"
    )