from __future__ import annotations

import ast
from pathlib import Path
import re

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
TARGET_DIRS = [
    APP_ROOT / "domain" / "adventure_imports",
    APP_ROOT / "persistence" / "adventure_imports",
]

FORBIDDEN_IMPORT_MODULES = {
    "httpx",
    "requests",
    "openai",
    "anthropic",
}

FORBIDDEN_API_KEY_RE = re.compile(
    r"(?:openai|anthropic|llm|model|gemini)_?api_?key",
    re.IGNORECASE,
)


def _check_import_violation(module_name: str) -> str | None:
    if module_name in FORBIDDEN_IMPORT_MODULES or any(
        module_name.startswith(f"{f}.") for f in FORBIDDEN_IMPORT_MODULES
    ):
        return f"Forbidden module import: '{module_name}'"
    if module_name == "urllib.request" or module_name.startswith("urllib.request."):
        return f"Forbidden module import: '{module_name}'"
    return None


def _scan_file_ast(file_path: Path) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))

    for node in ast.walk(tree):
        # 1. Check ast.Import
        if isinstance(node, ast.Import):
            for alias in node.names:
                err = _check_import_violation(alias.name)
                if err:
                    violations.append(f"{file_path.name}:{node.lineno}: {err}")

        # 2. Check ast.ImportFrom
        elif isinstance(node, ast.ImportFrom):
            base_module = node.module or ""
            # E.g. from urllib.request import ... or from urllib import request
            err = _check_import_violation(base_module)
            if err:
                violations.append(f"{file_path.name}:{node.lineno}: {err}")
            for alias in node.names:
                full_import = f"{base_module}.{alias.name}" if base_module else alias.name
                err = _check_import_violation(full_import)
                if err:
                    violations.append(f"{file_path.name}:{node.lineno}: {err}")

        # 3. Check for API key setting names in names, attributes, and constants
        elif isinstance(node, ast.Name):
            if FORBIDDEN_API_KEY_RE.search(node.id):
                violations.append(f"{file_path.name}:{node.lineno}: Forbidden API key identifier: '{node.id}'")
        elif isinstance(node, ast.Attribute):
            if FORBIDDEN_API_KEY_RE.search(node.attr):
                violations.append(f"{file_path.name}:{node.lineno}: Forbidden API key attribute: '{node.attr}'")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if FORBIDDEN_API_KEY_RE.search(node.value):
                violations.append(f"{file_path.name}:{node.lineno}: Forbidden API key constant: '{node.value}'")

    return violations


def test_adventure_imports_has_no_llm_or_network_dependencies() -> None:
    all_violations: list[str] = []

    for target_dir in TARGET_DIRS:
        assert target_dir.exists(), f"Target directory {target_dir} does not exist"
        for py_file in target_dir.rglob("*.py"):
            violations = _scan_file_ast(py_file)
            all_violations.extend(violations)

    assert not all_violations, (
        f"P6-E boundary violations found in adventure_imports:\n"
        + "\n".join(all_violations)
    )


def test_ast_scanner_detects_forbidden_imports_and_api_keys(tmp_path: Path) -> None:
    # Negative test to prove the scanner fails on forbidden constructs
    bad_file = tmp_path / "bad.py"
    bad_file.write_text(
        "import httpx\n"
        "from openai import Client\n"
        "from urllib.request import urlopen\n"
        "from urllib.parse import urlparse\n"  # allowed!
        "OPENAI_API_KEY = 'test-key'\n"
        "cfg_key = settings.anthropic_api_key\n",
        encoding="utf-8",
    )

    violations = _scan_file_ast(bad_file)
    assert len(violations) >= 5
    assert any("httpx" in v for v in violations)
    assert any("openai" in v for v in violations)
    assert any("urllib.request" in v for v in violations)
    assert any("OPENAI_API_KEY" in v for v in violations)
    assert any("anthropic_api_key" in v for v in violations)
    assert not any("urlparse" in v for v in violations)
