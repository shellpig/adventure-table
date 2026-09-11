from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, urlencode, urlparse

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse

from admin import create_admin_app

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None
_SECRET_KEY_MARKERS = ("token", "code", "secret", "verifier", "challenge", "password")
_URL_SECRET_RE = re.compile(
    r"([?&](?:[^=&]*(?:token|code|secret|verifier|challenge)[^=&]*)=)([^&#]*)",
    re.IGNORECASE,
)


def _masked(value: Any) -> str:
    text = "" if value is None else str(value)
    return f"[redacted:{len(text)}]"


def _redact_string(value: str, known_secrets: set[str]) -> str:
    def replace_query(match: re.Match[str]) -> str:
        raw = match.group(2)
        return f"{match.group(1)}{_masked(raw)}"

    result = _URL_SECRET_RE.sub(replace_query, value)
    for secret_value in sorted(known_secrets, key=len, reverse=True):
        if secret_value and secret_value in result:
            result = result.replace(secret_value, _masked(secret_value))
    return result


def redact(value: JsonValue, *, known_secrets: set[str] | None = None, key: str | None = None) -> JsonValue:
    """Apply the same secret redaction to request and response material."""
    known_secrets = known_secrets or set()
    normalized = (key or "").lower().replace("-", "_")
    if normalized in {"authorization", "cookie", "set_cookie"} or any(marker in normalized for marker in _SECRET_KEY_MARKERS):
        if value in (None, ""):
            return value
        return _masked(value)
    if isinstance(value, dict):
        return {str(k): redact(v, known_secrets=known_secrets, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item, known_secrets=known_secrets) for item in value]
    if isinstance(value, str):
        return _redact_string(value, known_secrets)
    return value


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_secret(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(24)}"


def _now() -> float:
    return time.time()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _b64url_sha256(value: str) -> str:
    digest = hashlib.sha256(value.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _headers_to_dict(headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_key, raw_value in headers:
        key = raw_key.decode("latin-1").lower()
        value = raw_value.decode("latin-1")
        result[key] = f"{result[key]}, {value}" if key in result else value
    return result


def _decode_query(raw: str) -> dict[str, Any]:
    return {key: values if len(values) > 1 else values[0] for key, values in parse_qs(raw, keep_blank_values=True).items()}


def _decode_body(body: bytes, content_type: str) -> JsonValue:
    if not body:
        return None
    text = body.decode("utf-8", "replace")
    if "application/json" in content_type:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    if "application/x-www-form-urlencoded" in content_type:
        return _decode_query(text)
    if "text/html" in content_type:
        return f"<text/html {len(body)} bytes omitted>"
    if content_type.startswith("text/") or len(text) <= 4096:
        return text
    return f"<body {len(body)} bytes omitted>"


@dataclass(frozen=True)
class Config:
    public_base_url: str
    test_password: str
    log_path: Path
    access_ttl_seconds: int = 300
    refresh_ttl_seconds: int = 86400
    default_protocol_version: str = "2025-06-18"
    force_sse: bool = False

    def __post_init__(self) -> None:
        base = self.public_base_url.rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("public_base_url must be an absolute http(s) URL")
        if not self.test_password:
            raise ValueError("test_password must not be empty")
        object.__setattr__(self, "public_base_url", base)


@dataclass
class OAuthClient:
    client_id: str
    redirect_uris: tuple[str, ...]


@dataclass
class AuthorizationCode:
    code_hash: str
    client_id: str
    redirect_uri: str
    role: str
    scope: str
    code_challenge: str | None
    code_challenge_method: str | None
    expires_at: float


@dataclass
class TokenFamily:
    family_id: str
    client_id: str
    role: str
    scope: str
    access_hash: str
    access_expires_at: float
    refresh_hash: str
    refresh_expires_at: float
    revoked: bool = False


@dataclass
class PreflightState:
    clients: dict[str, OAuthClient] = field(default_factory=dict)
    authorization_codes: dict[str, AuthorizationCode] = field(default_factory=dict)
    families: dict[str, TokenFamily] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    late_tool_enabled: bool = False
    known_secrets: set[str] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def remember_secret(self, value: str | None) -> None:
        if value:
            self.known_secrets.add(value)

    async def revoke_all(self) -> None:
        async with self.lock:
            for family in self.families.values():
                family.revoked = True

    async def enable_late_tool(self) -> None:
        async with self.lock:
            self.late_tool_enabled = True

    def access_family(self, token: str | None) -> TokenFamily | None:
        if not token:
            return None
        token_hash = _hash_token(token)
        for family in self.families.values():
            if not family.revoked and family.access_expires_at > _now() and hmac.compare_digest(family.access_hash, token_hash):
                return family
        return None

    def refresh_family(self, token: str | None) -> TokenFamily | None:
        if not token:
            return None
        token_hash = _hash_token(token)
        for family in self.families.values():
            if not family.revoked and family.refresh_expires_at > _now() and hmac.compare_digest(family.refresh_hash, token_hash):
                return family
        return None


class JsonlLogger:
    def __init__(self, path: Path, state: PreflightState) -> None:
        self.path = path
        self.state = state
        self._lock = asyncio.Lock()

    async def write(self, record: dict[str, Any]) -> None:
        clean = redact(record, known_secrets=self.state.known_secrets)
        line = json.dumps(clean, ensure_ascii=False, separators=(",", ":")) + "\n"
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)


class AuditMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], logger: JsonlLogger) -> None:
        self.app = app
        self.logger = logger

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[dict[str, Any]]], send: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        body_parts: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                continue
            body_parts.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        request_body = b"".join(body_parts)
        replayed = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal replayed
            if replayed:
                return {"type": "http.request", "body": b"", "more_body": False}
            replayed = True
            return {"type": "http.request", "body": request_body, "more_body": False}

        status = 500
        response_headers: list[tuple[bytes, bytes]] = []
        response_body_parts: list[bytes] = []

        async def capture_send(message: dict[str, Any]) -> None:
            nonlocal status, response_headers
            if message["type"] == "http.response.start":
                status = int(message.get("status", 500))
                response_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                used = sum(map(len, response_body_parts))
                if used < 65536:
                    response_body_parts.append(chunk[: 65536 - used])
            await send(message)

        started = time.monotonic()
        try:
            await self.app(scope, replay_receive, capture_send)
        finally:
            request_headers = _headers_to_dict(scope.get("headers", []))
            response_header_map = _headers_to_dict(response_headers)
            request_payload = _decode_body(request_body, request_headers.get("content-type", ""))
            response_payload = _decode_body(b"".join(response_body_parts), response_header_map.get("content-type", ""))
            await self.logger.write(
                {
                    "ts": _utc_now(),
                    "duration_ms": round((time.monotonic() - started) * 1000, 3),
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "query": _decode_query(scope.get("query_string", b"").decode("utf-8", "replace")),
                    "headers": request_headers,
                    "body": request_payload,
                    "status": status,
                    "response_headers": response_header_map,
                    "response_body": response_payload,
                    "observation": {
                        "mcp_protocol_version": request_headers.get("mcp-protocol-version"),
                        "mcp_session_id_present": "mcp-session-id" in request_headers,
                        "accepts_sse": "text/event-stream" in request_headers.get("accept", "").lower(),
                        "jsonrpc_method": request_payload.get("method") if isinstance(request_payload, dict) else None,
                        "meta": request_payload.get("params", {}).get("_meta") if isinstance(request_payload, dict) and isinstance(request_payload.get("params"), dict) else None,
                    },
                }
            )


def _oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error, "error_description": description}, status_code=status)


def _rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]}


def _bearer(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    return value[7:].strip() if value.lower().startswith("bearer ") else None


def _role_scopes(role: str) -> list[str]:
    scopes = ["mcp:read", "mcp:write"]
    if role == "dm":
        scopes.append("mcp:dm")
    return scopes


def _tool_catalog(state: PreflightState, role: str) -> list[dict[str, Any]]:
    tools = [
        {
            "name": "get_context",
            "description": "Read the simulated role, note count, and server time for the M04-A web-chat MCP preflight.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        },
        {
            "name": "post_note",
            "description": "Write one short note to volatile preflight memory and return the new sequence number.",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 1000}},
                "required": ["text"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        },
        {
            "name": "wait_seconds",
            "description": "Wait 0 to 120 seconds before replying. This measures web-chat long-poll tolerance only.",
            "inputSchema": {
                "type": "object",
                "properties": {"seconds": {"type": "number", "minimum": 0, "maximum": 120}},
                "required": ["seconds"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
        },
    ]
    if role == "dm":
        tools.append(
            {
                "name": "dm_only_ping",
                "description": "DM-only discovery probe. Returns pong without changing any state.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            }
        )
    if state.late_tool_enabled:
        tools.append(
            {
                "name": "late_tool",
                "description": "Late-added read-only probe used to measure connector tool-cache refresh behavior.",
                "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            }
        )
    return tools


def _load_authorize_template() -> str:
    return (Path(__file__).with_name("authorize.html")).read_text(encoding="utf-8")


def _render_authorize(values: dict[str, str], error: str | None = None) -> str:
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">'
        for key, value in values.items()
    )
    error_html = f'<p style="color:#b00020">{html.escape(error)}</p>' if error else ""
    return _load_authorize_template().replace("{{HIDDEN_FIELDS}}", hidden).replace("{{ERROR}}", error_html)


def create_public_app(config: Config, state: PreflightState | None = None) -> FastAPI:
    state = state or PreflightState()
    state.remember_secret(config.test_password)
    logger = JsonlLogger(config.log_path, state)
    app = FastAPI(title="Adventure Table M04-A Web Chat MCP Preflight", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.preflight = state
    app.add_middleware(AuditMiddleware, logger=logger)
    resource_metadata_url = f"{config.public_base_url}/.well-known/oauth-protected-resource"

    @app.get("/.well-known/oauth-protected-resource")
    async def protected_resource_metadata() -> dict[str, Any]:
        return {
            "resource": f"{config.public_base_url}/mcp",
            "authorization_servers": [config.public_base_url],
            "scopes_supported": ["mcp:read", "mcp:write", "mcp:dm"],
            "bearer_methods_supported": ["header"],
        }

    @app.get("/.well-known/oauth-authorization-server")
    async def authorization_server_metadata() -> dict[str, Any]:
        return {
            "issuer": config.public_base_url,
            "authorization_endpoint": f"{config.public_base_url}/authorize",
            "token_endpoint": f"{config.public_base_url}/token",
            "registration_endpoint": f"{config.public_base_url}/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["mcp:read", "mcp:write", "mcp:dm"],
            "token_endpoint_auth_methods_supported": ["none"],
        }

    @app.post("/register")
    async def register(request: Request) -> Response:
        try:
            payload = await request.json()
        except Exception:
            return _oauth_error("invalid_client_metadata", "JSON body required")
        redirect_uris = payload.get("redirect_uris")
        if not isinstance(redirect_uris, list) or not redirect_uris or not all(isinstance(uri, str) and uri for uri in redirect_uris):
            return _oauth_error("invalid_redirect_uri", "redirect_uris must be a non-empty string array")
        client_id = _new_secret("client")
        async with state.lock:
            state.clients[client_id] = OAuthClient(client_id=client_id, redirect_uris=tuple(redirect_uris))
            state.remember_secret(client_id)
        return JSONResponse(
            {
                "client_id": client_id,
                "client_id_issued_at": int(_now()),
                "redirect_uris": redirect_uris,
                "token_endpoint_auth_method": "none",
            },
            status_code=201,
        )

    def validate_authorize_values(values: dict[str, str]) -> str | None:
        client = state.clients.get(values.get("client_id", ""))
        if client is None:
            return "unknown client_id"
        if values.get("redirect_uri") not in client.redirect_uris:
            return "redirect_uri is not registered"
        if values.get("response_type") != "code":
            return "only response_type=code is supported"
        method = values.get("code_challenge_method")
        if method and method != "S256":
            return "only PKCE S256 is supported"
        if method and not values.get("code_challenge"):
            return "code_challenge is required with code_challenge_method"
        return None

    @app.get("/authorize")
    async def authorize_get(request: Request) -> Response:
        values = {key: value for key, value in request.query_params.items()}
        error = validate_authorize_values(values)
        if error:
            return _oauth_error("invalid_request", error)
        return HTMLResponse(_render_authorize(values))

    @app.post("/authorize")
    async def authorize_post(request: Request) -> Response:
        body = (await request.body()).decode("utf-8", "replace")
        values = {key: entries[-1] for key, entries in parse_qs(body, keep_blank_values=True).items()}
        error = validate_authorize_values(values)
        if error:
            return _oauth_error("invalid_request", error)
        role = values.get("role")
        if role not in {"dm", "player"}:
            safe_values = {key: value for key, value in values.items() if key not in {"role", "password"}}
            return HTMLResponse(_render_authorize(safe_values, "Choose dm or player."), status_code=400)
        if not hmac.compare_digest(values.get("password", ""), config.test_password):
            safe_values = {key: value for key, value in values.items() if key not in {"role", "password"}}
            return HTMLResponse(_render_authorize(safe_values, "Wrong test password."), status_code=403)
        requested = [scope for scope in values.get("scope", "").split() if scope]
        allowed = set(_role_scopes(role))
        granted = [scope for scope in requested if scope in allowed] or _role_scopes(role)
        code = _new_secret("code")
        async with state.lock:
            state.authorization_codes[_hash_token(code)] = AuthorizationCode(
                code_hash=_hash_token(code),
                client_id=values["client_id"],
                redirect_uri=values["redirect_uri"],
                role=role,
                scope=" ".join(granted),
                code_challenge=values.get("code_challenge") or None,
                code_challenge_method=values.get("code_challenge_method") or None,
                expires_at=_now() + 300,
            )
            state.remember_secret(code)
        location = values["redirect_uri"] + ("&" if "?" in values["redirect_uri"] else "?") + urlencode(
            {"code": code, **({"state": values["state"]} if values.get("state") else {})}
        )
        return RedirectResponse(location, status_code=302)

    @app.post("/token")
    async def token(request: Request) -> Response:
        body = (await request.body()).decode("utf-8", "replace")
        values = {key: entries[-1] for key, entries in parse_qs(body, keep_blank_values=True).items()}
        grant_type = values.get("grant_type")
        client_id = values.get("client_id", "")
        if client_id not in state.clients:
            return _oauth_error("invalid_client", "unknown client_id", 401)

        if grant_type == "authorization_code":
            raw_code = values.get("code", "")
            async with state.lock:
                auth_code = state.authorization_codes.pop(_hash_token(raw_code), None)
            if auth_code is None or auth_code.expires_at <= _now():
                return _oauth_error("invalid_grant", "authorization code invalid or expired")
            if auth_code.client_id != client_id or auth_code.redirect_uri != values.get("redirect_uri"):
                return _oauth_error("invalid_grant", "authorization code binding mismatch")
            if auth_code.code_challenge:
                verifier = values.get("code_verifier", "")
                if not verifier or _b64url_sha256(verifier) != auth_code.code_challenge:
                    return _oauth_error("invalid_grant", "PKCE verification failed")
            access = _new_secret("access")
            refresh = _new_secret("refresh")
            family_id = _new_secret("family")
            now = _now()
            family = TokenFamily(
                family_id=family_id,
                client_id=client_id,
                role=auth_code.role,
                scope=auth_code.scope,
                access_hash=_hash_token(access),
                access_expires_at=now + config.access_ttl_seconds,
                refresh_hash=_hash_token(refresh),
                refresh_expires_at=now + config.refresh_ttl_seconds,
            )
            async with state.lock:
                state.families[family_id] = family
                state.remember_secret(access)
                state.remember_secret(refresh)
                state.remember_secret(family_id)
            payload = {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": config.access_ttl_seconds,
                "refresh_token": refresh,
                "scope": auth_code.scope,
            }
        elif grant_type == "refresh_token":
            raw_refresh = values.get("refresh_token", "")
            family = state.refresh_family(raw_refresh)
            if family is None or family.client_id != client_id:
                return _oauth_error("invalid_grant", "refresh token invalid, expired, or revoked")
            access = _new_secret("access")
            async with state.lock:
                family.access_hash = _hash_token(access)
                family.access_expires_at = _now() + config.access_ttl_seconds
                state.remember_secret(access)
            payload = {
                "access_token": access,
                "token_type": "Bearer",
                "expires_in": config.access_ttl_seconds,
                "refresh_token": raw_refresh,
                "scope": family.scope,
            }
        else:
            return _oauth_error("unsupported_grant_type", "authorization_code and refresh_token are supported")
        return JSONResponse(payload, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    def unauthorized() -> JSONResponse:
        return JSONResponse(
            {"error": "invalid_token"},
            status_code=401,
            headers={"WWW-Authenticate": f'Bearer resource_metadata="{resource_metadata_url}"'},
        )

    async def send_rpc(request: Request, payload: dict[str, Any], session_id: str | None) -> Response:
        headers = {"Mcp-Session-Id": session_id} if session_id else {}
        if config.force_sse and "text/event-stream" in request.headers.get("accept", "").lower():
            async def stream() -> Any:
                data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                yield f"event: message\ndata: {data}\n\n".encode("utf-8")
            return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)
        return JSONResponse(payload, headers=headers)

    @app.get("/mcp")
    async def mcp_get() -> PlainTextResponse:
        return PlainTextResponse("MCP endpoint")

    @app.post("/mcp")
    async def mcp_post(request: Request) -> Response:
        family = state.access_family(_bearer(request))
        if family is None:
            return unauthorized()
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(_rpc_error(None, -32700, "Parse error"), status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse(_rpc_error(None, -32600, "Invalid Request"), status_code=400)
        request_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        incoming_session = request.headers.get("mcp-session-id")
        response_session = incoming_session

        if request_id is None and method == "notifications/initialized":
            return Response(status_code=202, headers={"Mcp-Session-Id": incoming_session} if incoming_session else None)
        if method == "initialize":
            requested_version = params.get("protocolVersion")
            protocol_version = requested_version if isinstance(requested_version, str) and requested_version else config.default_protocol_version
            response_session = incoming_session or _new_secret("mcp_session")
            result = {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "adventure-table-m04a-webchat-preflight", "version": "0.1.0"},
                "instructions": "M04-A measurement harness only. Use tools to probe read/write, role-scoped discovery, cache refresh, and long-poll behavior.",
            }
            return await send_rpc(request, _rpc_result(request_id, result), response_session)
        if method == "server/discover":
            result = {
                "protocolVersion": request.headers.get("mcp-protocol-version") or config.default_protocol_version,
                "instructions": "M04-A measurement harness only.",
                "capabilities": {"tools": True},
            }
            return await send_rpc(request, _rpc_result(request_id, result), response_session)
        if method == "ping":
            return await send_rpc(request, _rpc_result(request_id, {}), response_session)
        if method == "tools/list":
            return await send_rpc(request, _rpc_result(request_id, {"tools": _tool_catalog(state, family.role)}), response_session)
        if method != "tools/call":
            return await send_rpc(request, _rpc_error(request_id, -32601, "Method not found"), response_session)

        name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if name == "get_context":
            result = {"role": family.role, "note_count": len(state.notes), "server_time": _utc_now()}
        elif name == "post_note":
            text = arguments.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                return await send_rpc(request, _rpc_error(request_id, -32602, "text must be 1..1000 characters"), response_session)
            async with state.lock:
                state.notes.append(text)
                result = {"seq": len(state.notes)}
        elif name == "dm_only_ping":
            if family.role != "dm":
                return await send_rpc(request, _rpc_error(request_id, -32601, "Tool not found for this role"), response_session)
            result = {"pong": True}
        elif name == "wait_seconds":
            seconds = arguments.get("seconds")
            if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds < 0 or seconds > 120:
                return await send_rpc(request, _rpc_error(request_id, -32602, "seconds must be between 0 and 120"), response_session)
            started = time.monotonic()
            await asyncio.sleep(float(seconds))
            result = {"waited": round(time.monotonic() - started, 3)}
        elif name == "late_tool" and state.late_tool_enabled:
            result = {"late_tool": True}
        else:
            return await send_rpc(request, _rpc_error(request_id, -32601, "Tool not found"), response_session)
        return await send_rpc(request, _rpc_result(request_id, _tool_result(result)), response_session)

    return app


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adventure Table M04-A Web Chat MCP preflight")
    parser.add_argument("--public-base-url", default=os.environ.get("M04A_PUBLIC_BASE_URL"))
    parser.add_argument("--test-password", default=os.environ.get("M04A_TEST_PASSWORD"))
    parser.add_argument("--host", default=os.environ.get("M04A_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("M04A_PORT", "8787")))
    parser.add_argument("--admin-port", type=int, default=int(os.environ.get("M04A_ADMIN_PORT", "8788")))
    parser.add_argument("--log-path", default=os.environ.get("M04A_LOG_PATH", "logs/m04a-preflight.jsonl"))
    return parser.parse_args()


async def _serve(args: argparse.Namespace) -> None:
    if not args.public_base_url:
        raise SystemExit("--public-base-url or M04A_PUBLIC_BASE_URL is required")
    if not args.test_password:
        raise SystemExit("--test-password or M04A_TEST_PASSWORD is required")
    admin_host = "127.0.0.1"
    assert admin_host == "127.0.0.1", "M04-A admin listener must bind loopback"
    force_sse = os.environ.get("M04A_FORCE_SSE", "").strip().lower() in {"1", "true", "yes"}
    config = Config(
        public_base_url=args.public_base_url,
        test_password=args.test_password,
        log_path=Path(args.log_path),
        force_sse=force_sse,
    )
    state = PreflightState()
    public_app = create_public_app(config, state)
    admin_app = create_admin_app(state)
    public_server = uvicorn.Server(uvicorn.Config(public_app, host=args.host, port=args.port, log_level="info"))
    admin_server = uvicorn.Server(uvicorn.Config(admin_app, host=admin_host, port=args.admin_port, log_level="info"))
    await asyncio.gather(public_server.serve(), admin_server.serve())


def main() -> None:
    asyncio.run(_serve(_parse_args()))


if __name__ == "__main__":
    main()
