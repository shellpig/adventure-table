from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.rooms.ai_controllers import get_ai_controller_service
from app.domain.rooms.ai_controllers import AIControllerUnauthorizedError
from app.mcp.protocol import (
    CACHE_SCOPE,
    CACHE_TTL_MS,
    MCP_HEADER_MISMATCH,
    MCP_PROTOCOL_VERSION,
    MCP_UNSUPPORTED_PROTOCOL_VERSION,
    SERVER_INFO,
    SERVER_INFO_META_KEY,
)
from app.mcp.server import router


class _FakeAIControllerService:
    def __init__(self, *, reject: bool = False) -> None:
        self.reject = reject
        self.tokens: list[tuple[str, bool]] = []

    def authenticate(self, token: str, *, touch: bool = False):
        self.tokens.append((token, touch))
        if self.reject:
            raise AIControllerUnauthorizedError("rejected")
        return object()


def _client(service: _FakeAIControllerService | None = None) -> tuple[TestClient, _FakeAIControllerService]:
    fake = service or _FakeAIControllerService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_ai_controller_service] = lambda: fake
    return TestClient(app), fake


def _body(method: str, *, params: dict | None = None, request_id=1) -> dict:
    merged = dict(params or {})
    merged["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "p3e-test", "version": "1"},
    }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": merged,
    }


def _headers(method: str, *, token: str = "at_ai_fake_secret", name: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


def test_discover_is_modern_stateless_first_request_and_cacheable() -> None:
    client, service = _client()

    response = client.post(
        "/mcp",
        json=_body("server/discover", request_id="discover-1"),
        headers=_headers("server/discover"),
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == [MCP_PROTOCOL_VERSION]
    assert result["ttlMs"] == CACHE_TTL_MS
    assert result["cacheScope"] == CACHE_SCOPE
    assert result["_meta"][SERVER_INFO_META_KEY] == SERVER_INFO
    assert "mcp-session-id" not in response.headers
    assert service.tokens == [("at_ai_fake_secret", True)]


def test_protocol_version_header_and_meta_must_match() -> None:
    client, _ = _client()
    body = _body("server/discover")
    body["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = "2025-11-25"

    response = client.post("/mcp", json=body, headers=_headers("server/discover"))

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == MCP_HEADER_MISMATCH
    assert error["data"]["code"] == "mcp_protocol_version_mismatch"


def test_missing_protocol_version_header_is_rejected_before_auth() -> None:
    client, service = _client()
    headers = _headers("server/discover")
    del headers["MCP-Protocol-Version"]

    response = client.post("/mcp", json=_body("server/discover"), headers=headers)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == MCP_UNSUPPORTED_PROTOCOL_VERSION
    assert error["data"]["code"] == "mcp_protocol_version_unsupported"
    assert service.tokens == []


def test_modern_request_requires_client_capabilities_meta() -> None:
    client, _ = _client()
    body = _body("server/discover")
    del body["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]

    response = client.post("/mcp", json=body, headers=_headers("server/discover"))

    assert response.status_code == 400
    assert response.json()["error"]["data"]["code"] == "mcp_client_capabilities_required"


def test_mcp_method_header_must_match_json_rpc_method() -> None:
    client, _ = _client()

    response = client.post(
        "/mcp",
        json=_body("server/discover"),
        headers=_headers("tools/list"),
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == MCP_HEADER_MISMATCH
    assert error["data"]["code"] == "mcp_method_header_mismatch"


def test_missing_mcp_method_header_is_rejected_before_auth() -> None:
    client, service = _client()
    headers = _headers("server/discover")
    del headers["Mcp-Method"]

    response = client.post("/mcp", json=_body("server/discover"), headers=headers)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == MCP_HEADER_MISMATCH
    assert error["data"]["code"] == "mcp_method_header_mismatch"
    assert service.tokens == []


def test_named_operation_requires_matching_mcp_name_header() -> None:
    client, _ = _client()

    response = client.post(
        "/mcp",
        json=_body("tools/call", params={"name": "post_action", "arguments": {}}),
        headers=_headers("tools/call", name="wrong_tool"),
    )

    assert response.status_code == 400
    assert response.json()["error"]["data"]["code"] == "mcp_name_header_mismatch"


def test_named_operation_requires_mcp_name_header() -> None:
    client, service = _client()

    response = client.post(
        "/mcp",
        json=_body("tools/call", params={"name": "post_action", "arguments": {}}),
        headers=_headers("tools/call"),
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == MCP_HEADER_MISMATCH
    assert error["data"]["code"] == "mcp_name_header_mismatch"
    assert service.tokens == []


def test_modern_endpoint_rejects_removed_session_header() -> None:
    client, _ = _client()
    headers = _headers("server/discover")
    headers["Mcp-Session-Id"] = "legacy-session"

    response = client.post("/mcp", json=_body("server/discover"), headers=headers)

    assert response.status_code == 400
    assert response.json()["error"]["data"]["code"] == "mcp_session_id_not_supported"


def test_initialize_is_not_a_handshake_fallback() -> None:
    client, _ = _client()

    response = client.post(
        "/mcp",
        json=_body("initialize"),
        headers=_headers("initialize"),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == -32601
    assert response.json()["error"]["data"]["code"] == "mcp_method_not_found"


def test_every_request_requires_bearer_token() -> None:
    client, _ = _client()

    response = client.post(
        "/mcp",
        json=_body("server/discover"),
        headers={
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            "Mcp-Method": "server/discover",
        },
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["data"]["code"] == "ai_token_required"


def test_invalid_bearer_is_mapped_to_stable_structured_error() -> None:
    client, _ = _client(_FakeAIControllerService(reject=True))

    response = client.post(
        "/mcp",
        json=_body("server/discover"),
        headers=_headers("server/discover", token="bad"),
    )

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == -32001
    assert error["data"]["code"] == "ai_token_unauthorized"
    assert set(error["data"]["messages"]) == {"en", "zh-TW"}
