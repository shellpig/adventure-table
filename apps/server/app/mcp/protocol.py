from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


MCP_PROTOCOL_VERSION = "2026-07-28"
MCP_HEADER_MISMATCH = -32020
MCP_UNSUPPORTED_PROTOCOL_VERSION = -32022

SERVER_INFO = {
    "name": "adventure-table",
    "version": "0.0.1",
}
SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"
PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"

CACHE_TTL_MS = 30_000
CACHE_SCOPE = "private"


class MCPProtocolError(RuntimeError):
    def __init__(
        self,
        rpc_code: int,
        stable_code: str,
        message: str,
        *,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.rpc_code = rpc_code
        self.stable_code = stable_code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class MCPRequestEnvelope:
    request_id: Any
    method: str
    params: dict[str, Any]


def _named_operation(method: str, params: Mapping[str, Any]) -> str | None:
    if method in {"tools/call", "prompts/get"}:
        value = params.get("name")
        return value if isinstance(value, str) and value else None
    if method == "resources/read":
        value = params.get("uri")
        return value if isinstance(value, str) and value else None
    return None


def validate_request(headers: Mapping[str, str], body: Any) -> MCPRequestEnvelope:
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise MCPProtocolError(-32600, "mcp_invalid_request", "JSON-RPC 2.0 request required")

    method = body.get("method")
    if not isinstance(method, str) or not method:
        raise MCPProtocolError(-32600, "mcp_invalid_request", "JSON-RPC method is required")

    params = body.get("params", {})
    if not isinstance(params, dict):
        raise MCPProtocolError(-32602, "mcp_invalid_params", "params must be an object")

    protocol_header = headers.get("mcp-protocol-version")
    if protocol_header != MCP_PROTOCOL_VERSION:
        raise MCPProtocolError(
            MCP_UNSUPPORTED_PROTOCOL_VERSION,
            "mcp_protocol_version_unsupported",
            f"MCP protocol version must be {MCP_PROTOCOL_VERSION}",
        )

    meta = params.get("_meta")
    if not isinstance(meta, dict):
        raise MCPProtocolError(-32600, "mcp_request_meta_required", "request _meta is required")
    body_protocol = meta.get(PROTOCOL_VERSION_META_KEY)
    if body_protocol != protocol_header:
        raise MCPProtocolError(
            MCP_HEADER_MISMATCH,
            "mcp_protocol_version_mismatch",
            "MCP protocol header and request _meta version must match",
        )
    client_capabilities = meta.get(CLIENT_CAPABILITIES_META_KEY)
    if not isinstance(client_capabilities, dict):
        raise MCPProtocolError(
            -32600,
            "mcp_client_capabilities_required",
            "request _meta clientCapabilities is required",
        )

    method_header = headers.get("mcp-method")
    if method_header != method:
        raise MCPProtocolError(
            MCP_HEADER_MISMATCH,
            "mcp_method_header_mismatch",
            "Mcp-Method header must match the JSON-RPC method",
        )

    expected_name = _named_operation(method, params)
    if method in {"tools/call", "prompts/get", "resources/read"}:
        name_header = headers.get("mcp-name")
        if expected_name is None or name_header != expected_name:
            raise MCPProtocolError(
                MCP_HEADER_MISMATCH,
                "mcp_name_header_mismatch",
                "Mcp-Name header must match the named JSON-RPC operation",
            )

    if headers.get("mcp-session-id") is not None:
        raise MCPProtocolError(
            -32600,
            "mcp_session_id_not_supported",
            "Mcp-Session-Id is not supported by MCP 2026-07-28",
        )

    return MCPRequestEnvelope(
        request_id=body.get("id"),
        method=method,
        params=dict(params),
    )


def result_payload(
    request_id: Any,
    result: Mapping[str, Any],
    *,
    cacheable: bool = False,
) -> dict[str, Any]:
    payload = dict(result)
    payload.setdefault("resultType", "complete")
    if cacheable:
        payload["ttlMs"] = CACHE_TTL_MS
        payload["cacheScope"] = CACHE_SCOPE
    meta = payload.get("_meta")
    response_meta = dict(meta) if isinstance(meta, dict) else {}
    response_meta[SERVER_INFO_META_KEY] = dict(SERVER_INFO)
    payload["_meta"] = response_meta
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def error_payload(
    request_id: Any,
    *,
    rpc_code: int,
    stable_code: str,
    message: str,
    message_zh_tw: str,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": rpc_code,
            "message": message,
            "data": {
                "code": stable_code,
                "messages": {
                    "en": message,
                    "zh-TW": message_zh_tw,
                },
            },
        },
    }


__all__ = [
    "CACHE_SCOPE",
    "CACHE_TTL_MS",
    "CLIENT_CAPABILITIES_META_KEY",
    "MCP_HEADER_MISMATCH",
    "MCP_PROTOCOL_VERSION",
    "MCP_UNSUPPORTED_PROTOCOL_VERSION",
    "MCPProtocolError",
    "MCPRequestEnvelope",
    "PROTOCOL_VERSION_META_KEY",
    "SERVER_INFO",
    "SERVER_INFO_META_KEY",
    "error_payload",
    "result_payload",
    "validate_request",
]
