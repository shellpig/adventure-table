from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from admin import create_admin_app  # noqa: E402
from server import Config, PreflightState, create_public_app  # noqa: E402


async def _request(
    app: Any,
    *,
    method: str,
    path: str,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
    query: str = "",
    client_host: str = "127.0.0.1",
) -> tuple[int, dict[str, str], bytes]:
    messages: list[dict[str, Any]] = []
    sent = False
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query.encode("ascii"),
        "headers": encoded_headers,
        "client": (client_host, 4321),
        "server": ("preflight.example", 443),
        "root_path": "",
    }
    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start.get("headers", [])
    }
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return int(start["status"]), response_headers, response_body


def _json(body: bytes) -> dict[str, Any]:
    payload = json.loads(body.decode("utf-8"))
    assert isinstance(payload, dict)
    return payload


def _form(values: dict[str, str]) -> bytes:
    from urllib.parse import urlencode

    return urlencode(values).encode("ascii")


def _pkce(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def _register(app: Any) -> tuple[str, str]:
    redirect_uri = "https://client.example/callback"
    status, _, body = await _request(
        app,
        method="POST",
        path="/register",
        body=json.dumps(
            {
                "redirect_uris": [redirect_uri],
                "token_endpoint_auth_method": "none",
            }
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert status == 201
    return _json(body)["client_id"], redirect_uri


async def _issue_code(
    app: Any,
    *,
    client_id: str,
    redirect_uri: str,
    role: str,
    verifier: str,
) -> str:
    values = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "mcp:read mcp:write mcp:dm",
        "state": f"state-{role}",
        "code_challenge": _pkce(verifier),
        "code_challenge_method": "S256",
        "role": role,
        "password": "test-password",
    }
    status, headers, _ = await _request(
        app,
        method="POST",
        path="/authorize",
        body=_form(values),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert status == 302
    callback = urlparse(headers["location"])
    callback_query = parse_qs(callback.query)
    assert callback_query["state"] == [f"state-{role}"]
    return callback_query["code"][0]


async def _exchange_code(
    app: Any,
    *,
    client_id: str,
    redirect_uri: str,
    code: str,
    verifier: str,
) -> tuple[int, dict[str, Any]]:
    status, _, body = await _request(
        app,
        method="POST",
        path="/token",
        body=_form(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code": code,
                "code_verifier": verifier,
            }
        ),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    return status, _json(body)


async def _authorize_role(app: Any, role: str) -> tuple[str, str, str]:
    client_id, redirect_uri = await _register(app)
    verifier = "v" * 64
    code = await _issue_code(
        app,
        client_id=client_id,
        redirect_uri=redirect_uri,
        role=role,
        verifier=verifier,
    )
    status, token = await _exchange_code(
        app,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code=code,
        verifier=verifier,
    )
    assert status == 200
    return client_id, token["access_token"], token["refresh_token"]


async def _rpc(
    app: Any,
    access_token: str,
    method: str,
    params: dict[str, Any] | None = None,
    request_id: int = 1,
) -> dict[str, Any]:
    status, _, body = await _request(
        app,
        method="POST",
        path="/mcp",
        body=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        ).encode(),
        headers={
            "authorization": f"Bearer {access_token}",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": "2099-01-01",
        },
    )
    assert status == 200
    return _json(body)


def test_public_metadata_oauth_and_mcp_contract(tmp_path: Path) -> None:
    async def scenario() -> None:
        state = PreflightState()
        app = create_public_app(
            Config(
                public_base_url="https://preflight.example",
                test_password="test-password",
                log_path=tmp_path / "preflight.jsonl",
            ),
            state,
        )

        status, _, body = await _request(
            app,
            method="GET",
            path="/.well-known/oauth-protected-resource",
        )
        assert status == 200
        assert _json(body)["resource"] == "https://preflight.example/mcp"

        status, _, body = await _request(
            app,
            method="GET",
            path="/.well-known/oauth-authorization-server",
        )
        assert status == 200
        metadata = _json(body)
        assert metadata["registration_endpoint"] == "https://preflight.example/register"
        assert metadata["code_challenge_methods_supported"] == ["S256"]

        status, _, body = await _request(app, method="GET", path="/mcp")
        assert status == 200
        assert body == b"MCP endpoint"

        status, _, _ = await _request(
            app,
            method="POST",
            path="/admin/add-tool",
        )
        assert status == 404

        dm_client_id, dm_access, dm_refresh = await _authorize_role(app, "dm")
        initialize = await _rpc(
            app,
            dm_access,
            "initialize",
            {"protocolVersion": "2099-01-01"},
        )
        assert initialize["result"]["protocolVersion"] == "2099-01-01"
        assert initialize["result"]["capabilities"]["tools"]["listChanged"] is True

        dm_tools = await _rpc(app, dm_access, "tools/list", request_id=2)
        dm_names = {tool["name"] for tool in dm_tools["result"]["tools"]}
        assert {"get_context", "post_note", "wait_seconds", "dm_only_ping"} <= dm_names
        assert "late_tool" not in dm_names

        read_result = await _rpc(
            app,
            dm_access,
            "tools/call",
            {"name": "get_context", "arguments": {}},
            request_id=3,
        )
        assert '"role":"dm"' in read_result["result"]["content"][0]["text"]

        write_result = await _rpc(
            app,
            dm_access,
            "tools/call",
            {"name": "post_note", "arguments": {"text": "contract-smoke"}},
            request_id=4,
        )
        assert '"seq":1' in write_result["result"]["content"][0]["text"]

        await state.enable_late_tool()
        dm_tools_after = await _rpc(app, dm_access, "tools/list", request_id=5)
        assert "late_tool" in {
            tool["name"] for tool in dm_tools_after["result"]["tools"]
        }

        _, player_access, _ = await _authorize_role(app, "player")
        player_tools = await _rpc(app, player_access, "tools/list", request_id=6)
        player_names = {tool["name"] for tool in player_tools["result"]["tools"]}
        assert "dm_only_ping" not in player_names
        assert "late_tool" in player_names

        unknown = await _rpc(app, dm_access, "unknown/method", request_id=61)
        assert unknown["error"]["code"] == -32601

        status, _, body = await _request(
            app,
            method="POST",
            path="/token",
            body=_form(
                {
                    "grant_type": "refresh_token",
                    "client_id": dm_client_id,
                    "refresh_token": dm_refresh,
                }
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert status == 200
        rotated_access = _json(body)["access_token"]
        assert rotated_access != dm_access

        await state.revoke_all()
        status, _, _ = await _request(
            app,
            method="POST",
            path="/mcp",
            body=b'{"jsonrpc":"2.0","id":7,"method":"tools/list","params":{}}',
            headers={
                "authorization": f"Bearer {rotated_access}",
                "content-type": "application/json",
            },
        )
        assert status == 401

        status, _, body = await _request(
            app,
            method="POST",
            path="/token",
            body=_form(
                {
                    "grant_type": "refresh_token",
                    "client_id": dm_client_id,
                    "refresh_token": dm_refresh,
                }
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert status == 400
        assert _json(body)["error"] == "invalid_grant"

        log_text = (tmp_path / "preflight.jsonl").read_text(encoding="utf-8")
        for secret in (dm_access, dm_refresh, rotated_access, player_access):
            assert secret not in log_text
        assert '"token_endpoint":"https://preflight.example/token"' in log_text
        assert '"code_challenge_methods_supported":["S256"]' in log_text
        assert '"token_endpoint_auth_methods_supported":["none"]' in log_text
        assert '"token_endpoint_auth_method":"none"' in log_text
        assert '"token_type":"Bearer"' in log_text
        assert '"code":-32601' in log_text

    asyncio.run(scenario())


def test_failed_pkce_does_not_consume_authorization_code(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = create_public_app(
            Config(
                public_base_url="https://preflight.example",
                test_password="test-password",
                log_path=tmp_path / "preflight.jsonl",
            )
        )
        client_id, redirect_uri = await _register(app)
        verifier = "v" * 64
        code = await _issue_code(
            app,
            client_id=client_id,
            redirect_uri=redirect_uri,
            role="dm",
            verifier=verifier,
        )

        status, payload = await _exchange_code(
            app,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code=code,
            verifier="wrong-verifier",
        )
        assert status == 400
        assert payload["error"] == "invalid_grant"

        status, payload = await _exchange_code(
            app,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code=code,
            verifier=verifier,
        )
        assert status == 200
        assert payload["token_type"] == "Bearer"

        status, payload = await _exchange_code(
            app,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code=code,
            verifier=verifier,
        )
        assert status == 400
        assert payload["error"] == "invalid_grant"

    asyncio.run(scenario())


def test_admin_listener_accepts_loopback_and_rejects_non_loopback() -> None:
    async def scenario() -> None:
        state = PreflightState()
        app = create_admin_app(state)

        status, _, body = await _request(
            app,
            method="POST",
            path="/admin/add-tool",
            client_host="127.0.0.1",
        )
        assert status == 200
        assert _json(body) == {"ok": True, "tool": "late_tool"}
        assert state.late_tool_enabled is True

        status, _, _ = await _request(
            app,
            method="POST",
            path="/admin/revoke-all",
            client_host="203.0.113.10",
        )
        assert status == 404

    asyncio.run(scenario())
