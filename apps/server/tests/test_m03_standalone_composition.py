from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest

from tests.m03e_support import loaded_standalone


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
EXPECTED_ROUTER_CALLS = {
    "reference_router",
    "content_presentation_router",
    "characters_router",
    "character_builder_router",
    "create_meta_router('standalone')",
}


def _standalone_tree() -> ast.Module:
    source = APP_ROOT / "standalone.py"
    return ast.parse(source.read_text(encoding="utf-8"), filename=str(source))


def _create_app_function(tree: ast.Module) -> ast.FunctionDef:
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_standalone_app"
    ]
    assert len(functions) == 1
    return functions[0]


def test_standalone_composition_registers_exactly_five_api_routers() -> None:
    function = _create_app_function(_standalone_tree())
    include_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "include_router"
    ]

    rendered = {ast.unparse(call.args[0]) for call in include_calls if call.args}
    assert rendered == EXPECTED_ROUTER_CALLS
    assert len(include_calls) == 5


def test_standalone_mounts_static_assets_and_spa_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        app = standalone.app
        route_paths = {getattr(route, "path", None) for route in app.routes}

        assert "/assets" in route_paths
        assert "/{full_path:path}" in route_paths
        client = TestClient(app)
        assert client.get("/some/client/route").status_code == 200
        assert client.get("/api/definitely-not-a-route").status_code == 404


def test_standalone_startup_does_not_run_alembic() -> None:
    text = (APP_ROOT / "standalone.py").read_text(encoding="utf-8").lower()
    assert "alembic" not in text
    assert "command.upgrade" not in text


def test_meta_capabilities_are_mounted_on_standalone_and_web(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with loaded_standalone(monkeypatch, tmp_path) as standalone:
        standalone_payload = TestClient(standalone.app).get("/api/meta/capabilities").json()
        assert standalone_payload["channel"] == "standalone"
        assert standalone_payload["capabilities"]["character_builder"] is True
        assert standalone_payload["capabilities"]["character_import_export"] is True
        assert standalone_payload["capabilities"]["room"] is False

        sys.modules.pop("app.main", None)
        web = importlib.import_module("app.main")
        try:
            web_response = TestClient(web.app).get("/api/meta/capabilities")
            assert web_response.status_code == 200
            web_payload = web_response.json()
            assert web_payload["channel"] == "web"
            assert web_payload["capabilities"]["character_builder"] is True
            assert web_payload["capabilities"]["character_import_export"] is True
        finally:
            sys.modules.pop("app.main", None)
