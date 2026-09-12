from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from app.api.rooms.ai_controllers import get_ai_controller_service
from app.api.rooms.ai_oauth import get_ai_controller_oauth_service
from app.domain.rooms.ai_controllers import AIControllerService
from app.mcp.auth import MCPAuthenticationError, OAUTH_ACCESS_TOKEN_PREFIX, authenticate_request
from app.mcp.dependencies import get_ai_tool_application_service
from app.mcp.guide import render_guide
from app.mcp.protocol import MCP_PROTOCOL_VERSION, MCPProtocolError, error_payload, result_payload, validate_request
from app.mcp.public_origin import public_origin
from app.mcp.tools import call_tool, tool_catalog

router = APIRouter(tags=["mcp"])

_ERROR_ZH_TW = {
    "mcp_parse_error": "request body 必須是有效 JSON",
    "mcp_invalid_request": "需要 JSON-RPC 2.0 request",
    "mcp_invalid_params": "params 必須是 object",
    "mcp_protocol_version_unsupported": f"MCP protocol version 必須是 {MCP_PROTOCOL_VERSION}",
    "mcp_request_meta_required": "request 必須包含 _meta",
    "mcp_protocol_version_mismatch": "MCP protocol header 與 request _meta version 必須一致",
    "mcp_client_capabilities_required": "request _meta 必須包含 clientCapabilities",
    "mcp_method_header_mismatch": "Mcp-Method header 必須與 JSON-RPC method 一致",
    "mcp_name_header_mismatch": "Mcp-Name header 必須與 named JSON-RPC operation 一致",
    "mcp_session_id_not_supported": "MCP 2026-07-28 不支援 Mcp-Session-Id",
    "mcp_method_not_found": "此 MCP method 不受支援",
}


def _protocol_error(request_id: Any, exc: MCPProtocolError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=error_payload(request_id, rpc_code=exc.rpc_code, stable_code=exc.stable_code, message=exc.message, message_zh_tw=_ERROR_ZH_TW.get(exc.stable_code, exc.message)))


def _needs_oauth_service(request: Request) -> bool:
    return request.headers.get("authorization", "").startswith(f"Bearer {OAUTH_ACCESS_TOKEN_PREFIX}")


def _oauth_challenge(request: Request) -> str:
    return f'Bearer resource_metadata="{public_origin(request)}/.well-known/oauth-protected-resource"'


@router.get("/mcp/guide", response_model=None)
async def mcp_guide(locale: str = Query(default="en")) -> PlainTextResponse | JSONResponse:
    try:
        content = render_guide(locale)
    except ValueError:
        return JSONResponse(status_code=400, content={"ok": False, "error": {"code": "mcp_guide_locale_unsupported", "messages": {"en": "Supported locales are en and zh-TW", "zh-TW": "僅支援 en 與 zh-TW"}}})
    return PlainTextResponse(content, headers={"Cache-Control": "public, max-age=300"})


@router.post("/mcp")
async def mcp_endpoint(request: Request, ai_controller_service: AIControllerService = Depends(get_ai_controller_service)) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return _protocol_error(None, MCPProtocolError(-32700, "mcp_parse_error", "Request body must be valid JSON"))

    request_id = body.get("id") if isinstance(body, dict) else None
    try:
        envelope = validate_request(request.headers, body)
    except MCPProtocolError as exc:
        return _protocol_error(request_id, exc)

    oauth_service = get_ai_controller_oauth_service(request) if _needs_oauth_service(request) else None
    try:
        authenticated = await run_in_threadpool(authenticate_request, request, ai_controller_service, oauth_service)
    except MCPAuthenticationError as exc:
        return JSONResponse(status_code=401, headers={"WWW-Authenticate": _oauth_challenge(request)}, content=error_payload(envelope.request_id, rpc_code=-32001, stable_code=exc.stable_code, message=exc.message, message_zh_tw=exc.message_zh_tw))

    if envelope.method == "server/discover":
        guide_url = f"{public_origin(request)}/mcp/guide"
        return JSONResponse(content=result_payload(envelope.request_id, {
            "supportedVersions": [MCP_PROTOCOL_VERSION],
            "capabilities": {"tools": {}},
            "instructions": (
                f"Adventure Table external AI transport. Start with get_session_context and read the full bilingual guide at {guide_url}?locale=en. "
                "Use only the scoped Seat capabilities exposed by this server. / Adventure Table 外部 AI 傳輸入口；"
                f"先呼叫 get_session_context，完整雙語指引請讀 {guide_url}?locale=zh-TW；只能使用目前 scoped Seat 所允許的能力。"
            ),
        }, cacheable=True))

    if envelope.method == "tools/list":
        return JSONResponse(content=result_payload(envelope.request_id, {"tools": tool_catalog(authenticated.auth)}, cacheable=True))

    if envelope.method == "tools/call":
        name = envelope.params.get("name")
        arguments = envelope.params.get("arguments", {})
        if not isinstance(name, str) or not name:
            return JSONResponse(status_code=400, content=error_payload(envelope.request_id, rpc_code=-32602, stable_code="mcp_tool_name_required", message="tools/call requires a tool name", message_zh_tw="tools/call 必須指定工具名稱"))
        service = get_ai_tool_application_service(request)
        result = await call_tool(service, token=authenticated.token, auth=authenticated.auth, name=name, arguments=arguments)
        return JSONResponse(content=result_payload(envelope.request_id, result))

    return JSONResponse(status_code=404, content=error_payload(envelope.request_id, rpc_code=-32601, stable_code="mcp_method_not_found", message="MCP method is not supported", message_zh_tw=_ERROR_ZH_TW["mcp_method_not_found"]))


__all__ = ["router"]
