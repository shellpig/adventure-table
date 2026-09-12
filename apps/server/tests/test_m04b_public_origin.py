"""M04-B: OAuth metadata and the MCP bearer challenge must advertise the
configured public origin when the server sits behind a TLS-terminating proxy."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.mcp import router
from app.mcp.protocol import MCP_PROTOCOL_VERSION

PUBLIC = "https://table.example.ts.net"


@pytest.fixture
def public_origin(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "mcp_public_origin", PUBLIC + "/")
    return PUBLIC


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_metadata_uses_configured_public_origin(public_origin: str) -> None:
    client = _client()

    protected = client.get("/.well-known/oauth-protected-resource").json()
    assert protected["resource"] == f"{public_origin}/mcp"
    assert protected["authorization_servers"] == [public_origin]

    server = client.get("/.well-known/oauth-authorization-server").json()
    assert server["issuer"] == public_origin
    assert server["authorization_endpoint"] == f"{public_origin}/mcp/oauth/authorize"
    assert server["token_endpoint"] == f"{public_origin}/mcp/oauth/token"
    assert server["registration_endpoint"] == f"{public_origin}/mcp/oauth/register"
    assert server["revocation_endpoint"] == f"{public_origin}/mcp/oauth/revoke"


def test_bearer_challenge_uses_configured_public_origin(public_origin: str) -> None:
    client = _client()
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                    "io.modelcontextprotocol/clientCapabilities": {},
                    "io.modelcontextprotocol/clientInfo": {"name": "t", "version": "1"},
                }
            },
        },
        headers={"MCP-Protocol-Version": MCP_PROTOCOL_VERSION, "Mcp-Method": "server/discover"},
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == (
        f'Bearer resource_metadata="{public_origin}/.well-known/oauth-protected-resource"'
    )


def test_metadata_falls_back_to_request_origin_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mcp_public_origin", None)
    client = _client()
    assert client.get("/.well-known/oauth-protected-resource").json()["resource"] == (
        "http://testserver/mcp"
    )
