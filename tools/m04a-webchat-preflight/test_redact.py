from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from admin import create_admin_app  # noqa: E402
from server import PreflightState, _require_loopback_host, redact  # noqa: E402


def test_redact_hides_token_code_challenge_verifier_secret_and_location_values() -> None:
    secrets = {"access-plain", "refresh-plain", "code-plain", "client-secret-plain"}
    sample = {
        "request": {
            "authorization": "Bearer access-plain",
            "code": "code-plain",
            "code_verifier": "verifier-plain",
            "code_challenge": "challenge-plain",
            "client_secret": "client-secret-plain",
        },
        "response": {
            "access_token": "access-plain",
            "refresh_token": "refresh-plain",
            "Location": "https://client.example/callback?code=code-plain&state=ok",
        },
    }
    encoded = json.dumps(redact(sample, known_secrets=secrets))
    for secret in (*secrets, "verifier-plain", "challenge-plain"):
        assert secret not in encoded
    assert "[redacted:" in encoded


def test_redact_preserves_safe_protocol_evidence_but_not_secrets() -> None:
    sample = {
        "token_endpoint": "https://server.example/token",
        "token_endpoint_auth_method": "none",
        "token_endpoint_auth_methods_supported": ["none"],
        "token_type": "Bearer",
        "code_challenge_method": "S256",
        "code_challenge_methods_supported": ["S256"],
        "error": {"code": -32601},
        "code": "oauth-code-secret",
        "code_challenge": "challenge-secret",
        "access_token": "access-secret",
    }
    result = redact(sample)
    assert isinstance(result, dict)
    assert result["token_endpoint"] == "https://server.example/token"
    assert result["token_endpoint_auth_method"] == "none"
    assert result["token_endpoint_auth_methods_supported"] == ["none"]
    assert result["token_type"] == "Bearer"
    assert result["code_challenge_method"] == "S256"
    assert result["code_challenge_methods_supported"] == ["S256"]
    assert result["error"] == {"code": -32601}
    assert result["code"] != "oauth-code-secret"
    assert result["code_challenge"] != "challenge-secret"
    assert result["access_token"] != "access-secret"


def test_admin_bind_validation_accepts_only_literal_loopback_ips() -> None:
    _require_loopback_host("127.0.0.1")
    _require_loopback_host("::1")
    with pytest.raises(RuntimeError):
        _require_loopback_host("0.0.0.0")
    with pytest.raises(RuntimeError):
        _require_loopback_host("203.0.113.10")
    with pytest.raises(RuntimeError):
        _require_loopback_host("localhost")


def _run_asgi(app: Any, *, client_host: str, path: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    sent_request = False

    async def receive() -> dict[str, Any]:
        nonlocal sent_request
        if not sent_request:
            sent_request = True
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": (client_host, 4321),
        "server": ("127.0.0.1", 8788),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    return messages


def test_admin_router_returns_404_for_non_loopback_client() -> None:
    messages = _run_asgi(create_admin_app(PreflightState()), client_host="203.0.113.10", path="/admin/add-tool")
    start = next(message for message in messages if message["type"] == "http.response.start")
    assert start["status"] == 404
