from __future__ import annotations

import base64
import hashlib
import hmac
import html
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from app.api.rooms.ai_controllers import get_ai_controller_service
from app.api.rooms.ai_oauth import get_ai_controller_oauth_service
from app.domain.rooms.ai_controllers import AIControllerService, AIControllerUnauthorizedError
from app.domain.rooms.ai_oauth import AIControllerOAuthError, AIControllerOAuthService


router = APIRouter(tags=["mcp-oauth"])

AUTHORIZATION_CODE_TTL = timedelta(minutes=5)
ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=30)
ACCESS_TOKEN_PREFIX = "at_oa_"
REFRESH_TOKEN_PREFIX = "rt_oa_"
AUTHORIZATION_CODE_PREFIX = "ac_oa_"
CLIENT_ID_PREFIX = "atc_"


@dataclass(frozen=True)
class AuthorizationRequest:
    client_id: str
    redirect_uri: str
    state: str | None
    code_challenge: str


class OAuthRequestError(ValueError):
    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


def get_oauth_repository(request: Request) -> AIControllerOAuthService:
    """Compatibility dependency name; transport receives the OAuth application service."""

    return get_ai_controller_oauth_service(request)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mint(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _origin(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _oauth_error(error: str, description: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "error_description": description},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _parse_form_body(body: bytes) -> dict[str, str]:
    if len(body) > 64 * 1024:
        raise OAuthRequestError("invalid_request", "Request body is too large", 413)
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OAuthRequestError("invalid_request", "Request body must be UTF-8") from exc
    parsed = parse_qs(decoded, keep_blank_values=True, strict_parsing=False)
    result: dict[str, str] = {}
    for key, values in parsed.items():
        if len(values) != 1:
            raise OAuthRequestError("invalid_request", f"{key} must appear exactly once")
        result[key] = values[0]
    return result


def _validated_redirect_uris(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, list) or not payload or len(payload) > 16:
        raise OAuthRequestError(
            "invalid_client_metadata",
            "redirect_uris must be a non-empty array",
        )
    normalized: list[str] = []
    for item in payload:
        if not isinstance(item, str) or not item or len(item) > 2048:
            raise OAuthRequestError(
                "invalid_redirect_uri",
                "Every redirect URI must be a non-empty string",
            )
        parsed = urlparse(item)
        if parsed.scheme != "https" or not parsed.netloc or parsed.fragment:
            raise OAuthRequestError(
                "invalid_redirect_uri",
                "Redirect URIs must use https and must not contain fragments",
            )
        if item not in normalized:
            normalized.append(item)
    return tuple(normalized)


def _validate_authorization_request(
    values: dict[str, str],
    repository: AIControllerOAuthService,
) -> AuthorizationRequest:
    if values.get("response_type") != "code":
        raise OAuthRequestError("unsupported_response_type", "response_type must be code")
    client_id = values.get("client_id", "")
    redirect_uri = values.get("redirect_uri", "")
    code_challenge = values.get("code_challenge", "")
    if values.get("code_challenge_method") != "S256" or not code_challenge:
        raise OAuthRequestError(
            "invalid_request",
            "PKCE code_challenge_method=S256 and code_challenge are required",
        )
    client = repository.get_client(client_id)
    if client is None or redirect_uri not in client.redirect_uris:
        raise OAuthRequestError(
            "oauth_invalid_client",
            "client_id is unknown or redirect_uri is not registered",
        )
    return AuthorizationRequest(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=values.get("state") or None,
        code_challenge=code_challenge,
    )


def _append_redirect_params(uri: str, params: dict[str, str]) -> str:
    parsed = urlparse(uri)
    current = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in params.items():
        current[key] = [value]
    query = urlencode(
        [(key, item) for key, values in current.items() for item in values]
    )
    return urlunparse(parsed._replace(query=query))


def _authorize_page(
    auth_request: AuthorizationRequest,
    *,
    locale: str,
    error: bool = False,
) -> str:
    zh = locale.lower().startswith("zh")
    title = "授權 Adventure Table" if zh else "Authorize Adventure Table"
    instruction = (
        "請貼上 Adventure Table 產生的 AI Join Token。此頁只會把既有 Seat 授權給目前的 ChatGPT connector。"
        if zh
        else "Paste the AI Join Token generated by Adventure Table. This only authorizes the existing Seat for this ChatGPT connector."
    )
    label = "AI Join Token"
    submit = "授權" if zh else "Authorize"
    error_text = (
        "Token 無效或已失效。"
        if zh
        else "The token is invalid or no longer authorized."
    )
    error_html = f'<p role="alert">{html.escape(error_text)}</p>' if error else ""
    state_input = (
        f'<input type="hidden" name="state" value="{html.escape(auth_request.state)}">'
        if auth_request.state is not None
        else ""
    )
    return f"""<!doctype html>
<html lang="{"zh-Hant" if zh else "en"}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
</head>
<body>
<main>
<h1>{html.escape(title)}</h1>
<p>{html.escape(instruction)}</p>
{error_html}
<form method="post" action="/mcp/oauth/authorize">
<input type="hidden" name="response_type" value="code">
<input type="hidden" name="client_id" value="{html.escape(auth_request.client_id)}">
<input type="hidden" name="redirect_uri" value="{html.escape(auth_request.redirect_uri)}">
<input type="hidden" name="code_challenge" value="{html.escape(auth_request.code_challenge)}">
<input type="hidden" name="code_challenge_method" value="S256">
<input type="hidden" name="locale" value="{html.escape(locale)}">
{state_input}
<label for="ai_join_token">{html.escape(label)}</label>
<textarea id="ai_join_token" name="ai_join_token" required autocomplete="off" spellcheck="false"></textarea>
<button type="submit">{html.escape(submit)}</button>
</form>
</main>
</body>
</html>"""


def _preferred_locale(request: Request, explicit: str | None) -> str:
    if explicit:
        return explicit
    return "zh-TW" if "zh" in request.headers.get("accept-language", "").lower() else "en"


def _validate_current_grant(service: AIControllerService, grant_id: UUID) -> None:
    service.authenticate_grant(grant_id, touch=True)


@router.get("/.well-known/oauth-protected-resource")
def protected_resource_metadata(request: Request) -> dict[str, object]:
    origin = _origin(request)
    return {
        "resource": f"{origin}/mcp",
        "authorization_servers": [origin],
        "bearer_methods_supported": ["header"],
    }


@router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata(request: Request) -> dict[str, object]:
    origin = _origin(request)
    return {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/mcp/oauth/authorize",
        "token_endpoint": f"{origin}/mcp/oauth/token",
        "registration_endpoint": f"{origin}/mcp/oauth/register",
        "revocation_endpoint": f"{origin}/mcp/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
    }


@router.post("/mcp/oauth/register")
async def register_client(
    request: Request,
    repository: AIControllerOAuthService = Depends(get_oauth_repository),
) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return _oauth_error("invalid_client_metadata", "Request body must be valid JSON")
    if not isinstance(payload, dict):
        return _oauth_error("invalid_client_metadata", "Request body must be a JSON object")
    try:
        redirect_uris = _validated_redirect_uris(payload.get("redirect_uris"))
        if payload.get("token_endpoint_auth_method", "none") != "none":
            raise OAuthRequestError(
                "invalid_client_metadata",
                "Only public clients with token_endpoint_auth_method=none are supported",
            )
        response_types = payload.get("response_types", ["code"])
        grant_types = payload.get(
            "grant_types", ["authorization_code", "refresh_token"]
        )
        if response_types != ["code"] or not isinstance(grant_types, list):
            raise OAuthRequestError(
                "invalid_client_metadata",
                "Only the authorization-code response type is supported",
            )
        if "authorization_code" not in grant_types:
            raise OAuthRequestError(
                "invalid_client_metadata",
                "authorization_code grant is required",
            )
        client_name = payload.get("client_name")
        if client_name is not None and (
            not isinstance(client_name, str) or len(client_name) > 200
        ):
            raise OAuthRequestError("invalid_client_metadata", "client_name is invalid")
    except OAuthRequestError as exc:
        return _oauth_error(exc.error, exc.description, exc.status_code)

    client_id = _mint(CLIENT_ID_PREFIX)
    client = await run_in_threadpool(
        repository.create_client,
        client_id=client_id,
        redirect_uris=redirect_uris,
        client_name=client_name,
    )
    return JSONResponse(
        status_code=201,
        content={
            "client_id": client.client_id,
            "client_id_issued_at": int(client.created_at.timestamp()),
            "redirect_uris": list(client.redirect_uris),
            "client_name": client.client_name,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/mcp/oauth/authorize")
async def authorize_get(
    request: Request,
    repository: AIControllerOAuthService = Depends(get_oauth_repository),
) -> Response:
    values = {key: value for key, value in request.query_params.items()}
    try:
        auth_request = await run_in_threadpool(
            _validate_authorization_request,
            values,
            repository,
        )
    except OAuthRequestError as exc:
        return _oauth_error(exc.error, exc.description, exc.status_code)
    locale = _preferred_locale(request, values.get("locale"))
    return HTMLResponse(
        _authorize_page(auth_request, locale=locale),
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.post("/mcp/oauth/authorize")
async def authorize_post(
    request: Request,
    repository: AIControllerOAuthService = Depends(get_oauth_repository),
    ai_controller_service: AIControllerService = Depends(get_ai_controller_service),
) -> Response:
    try:
        values = _parse_form_body(await request.body())
        auth_request = await run_in_threadpool(
            _validate_authorization_request,
            values,
            repository,
        )
    except OAuthRequestError as exc:
        return _oauth_error(exc.error, exc.description, exc.status_code)

    locale = _preferred_locale(request, values.get("locale"))
    token = values.get("ai_join_token", "").strip()
    try:
        auth = await run_in_threadpool(
            ai_controller_service.authenticate,
            token,
            touch=True,
        )
    except AIControllerUnauthorizedError:
        return HTMLResponse(
            _authorize_page(auth_request, locale=locale, error=True),
            status_code=401,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )

    code = _mint(AUTHORIZATION_CODE_PREFIX)
    now = _now()
    try:
        authorization = await run_in_threadpool(
            repository.replace_authorization_for_grant,
            client_id=auth_request.client_id,
            grant_id=auth.grant_id,
            now=now,
        )
        await run_in_threadpool(
            repository.create_authorization_code,
            code_hash=_hash_secret(code),
            authorization_id=authorization.id,
            code_challenge=auth_request.code_challenge,
            redirect_uri=auth_request.redirect_uri,
            expires_at=now + AUTHORIZATION_CODE_TTL,
        )
    except AIControllerOAuthError:
        return HTMLResponse(
            _authorize_page(auth_request, locale=locale, error=True),
            status_code=401,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    params = {"code": code}
    if auth_request.state is not None:
        params["state"] = auth_request.state
    return RedirectResponse(
        _append_redirect_params(auth_request.redirect_uri, params),
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )


async def _authorization_code_exchange(
    values: dict[str, str],
    repository: AIControllerOAuthService,
    service: AIControllerService,
) -> JSONResponse:
    code = values.get("code", "")
    verifier = values.get("code_verifier", "")
    client_id = values.get("client_id", "")
    redirect_uri = values.get("redirect_uri", "")
    if not code or not verifier or not client_id or not redirect_uri:
        return _oauth_error(
            "invalid_grant",
            "code, code_verifier, client_id and redirect_uri are required",
        )

    code_hash = _hash_secret(code)
    stored = await run_in_threadpool(repository.get_authorization_code, code_hash)
    if (
        stored is None
        or stored.consumed_at is not None
        or _as_utc(stored.expires_at) <= _now()
    ):
        return _oauth_error(
            "invalid_grant",
            "Authorization code is invalid, expired, or already used",
        )
    authorization = await run_in_threadpool(
        repository.get_authorization,
        stored.authorization_id,
    )
    if (
        authorization is None
        or authorization.revoked_at is not None
        or authorization.client_id != client_id
        or stored.redirect_uri != redirect_uri
    ):
        return _oauth_error(
            "invalid_grant",
            "Authorization code does not match this client",
        )
    try:
        challenge = _pkce_s256(verifier)
    except (UnicodeEncodeError, ValueError):
        return _oauth_error("invalid_grant", "PKCE verifier is invalid")
    if not hmac.compare_digest(challenge, stored.code_challenge):
        return _oauth_error("invalid_grant", "PKCE verification failed")

    try:
        await run_in_threadpool(
            _validate_current_grant,
            service,
            authorization.grant_id,
        )
    except AIControllerUnauthorizedError:
        await run_in_threadpool(repository.revoke_authorization, authorization.id)
        return _oauth_error(
            "invalid_grant",
            "The bound Adventure Table authorization is no longer active",
        )

    consumed = await run_in_threadpool(
        repository.consume_authorization_code,
        code_hash,
        now=_now(),
    )
    if not consumed:
        return _oauth_error(
            "invalid_grant",
            "Authorization code is invalid, expired, or already used",
        )

    access_token = _mint(ACCESS_TOKEN_PREFIX)
    refresh_token = _mint(REFRESH_TOKEN_PREFIX)
    now = _now()
    try:
        await run_in_threadpool(
            repository.issue_token_pair,
            authorization_id=authorization.id,
            access_hash=_hash_secret(access_token),
            access_expires_at=now + ACCESS_TOKEN_TTL,
            refresh_hash=_hash_secret(refresh_token),
            refresh_expires_at=now + REFRESH_TOKEN_TTL,
        )
    except AIControllerOAuthError:
        return _oauth_error(
            "invalid_grant",
            "The authorization is no longer active",
        )
    return JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
            "refresh_token": refresh_token,
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


async def _refresh_exchange(
    values: dict[str, str],
    repository: AIControllerOAuthService,
    service: AIControllerService,
) -> JSONResponse:
    refresh_token = values.get("refresh_token", "")
    client_id = values.get("client_id", "")
    if not refresh_token or not client_id:
        return _oauth_error(
            "invalid_grant",
            "refresh_token and client_id are required",
        )
    token_hash = _hash_secret(refresh_token)
    stored = await run_in_threadpool(repository.get_token, token_hash)
    if stored is None or stored.kind != "refresh":
        return _oauth_error("invalid_grant", "Refresh token is invalid")
    authorization = await run_in_threadpool(
        repository.get_authorization,
        stored.authorization_id,
    )
    if authorization is None or authorization.client_id != client_id:
        return _oauth_error(
            "invalid_grant",
            "Refresh token does not match this client",
        )
    if stored.revoked_at is not None:
        await run_in_threadpool(repository.revoke_authorization, authorization.id)
        return _oauth_error(
            "invalid_grant",
            "Refresh token reuse revoked this authorization",
        )
    if authorization.revoked_at is not None or _as_utc(stored.expires_at) <= _now():
        return _oauth_error(
            "invalid_grant",
            "Refresh token is invalid or expired",
        )
    try:
        await run_in_threadpool(
            _validate_current_grant,
            service,
            authorization.grant_id,
        )
    except AIControllerUnauthorizedError:
        await run_in_threadpool(repository.revoke_authorization, authorization.id)
        return _oauth_error(
            "invalid_grant",
            "The bound Adventure Table authorization is no longer active",
        )

    new_access = _mint(ACCESS_TOKEN_PREFIX)
    new_refresh = _mint(REFRESH_TOKEN_PREFIX)
    now = _now()
    try:
        _, replay = await run_in_threadpool(
            repository.replace_refresh_token,
            presented_hash=token_hash,
            new_refresh_hash=_hash_secret(new_refresh),
            new_refresh_expires_at=now + REFRESH_TOKEN_TTL,
            new_access_hash=_hash_secret(new_access),
            new_access_expires_at=now + ACCESS_TOKEN_TTL,
            now=now,
        )
    except AIControllerOAuthError:
        return _oauth_error("invalid_grant", "Refresh token is invalid")
    if replay:
        return _oauth_error(
            "invalid_grant",
            "Refresh token reuse revoked this authorization",
        )
    return JSONResponse(
        content={
            "access_token": new_access,
            "token_type": "Bearer",
            "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
            "refresh_token": new_refresh,
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.post("/mcp/oauth/token")
async def token_endpoint(
    request: Request,
    repository: AIControllerOAuthService = Depends(get_oauth_repository),
    ai_controller_service: AIControllerService = Depends(get_ai_controller_service),
) -> JSONResponse:
    content_type = request.headers.get("content-type", "").split(";", 1)[0]
    if content_type.strip().lower() != "application/x-www-form-urlencoded":
        return _oauth_error(
            "invalid_request",
            "Content-Type must be application/x-www-form-urlencoded",
        )
    try:
        values = _parse_form_body(await request.body())
    except OAuthRequestError as exc:
        return _oauth_error(exc.error, exc.description, exc.status_code)
    grant_type = values.get("grant_type")
    if grant_type == "authorization_code":
        return await _authorization_code_exchange(
            values,
            repository,
            ai_controller_service,
        )
    if grant_type == "refresh_token":
        return await _refresh_exchange(
            values,
            repository,
            ai_controller_service,
        )
    return _oauth_error(
        "unsupported_grant_type",
        "Only authorization_code and refresh_token are supported",
    )


@router.post("/mcp/oauth/revoke")
async def revoke_endpoint(
    request: Request,
    repository: AIControllerOAuthService = Depends(get_oauth_repository),
) -> Response:
    try:
        values = _parse_form_body(await request.body())
    except OAuthRequestError:
        return Response(status_code=200)
    token = values.get("token", "")
    if token:
        await run_in_threadpool(
            repository.revoke_token_family,
            _hash_secret(token),
        )
    return Response(
        status_code=200,
        headers={"Cache-Control": "no-store"},
    )


__all__ = [
    "ACCESS_TOKEN_PREFIX",
    "AUTHORIZATION_CODE_PREFIX",
    "REFRESH_TOKEN_PREFIX",
    "get_oauth_repository",
    "router",
]
