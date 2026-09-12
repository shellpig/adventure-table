from __future__ import annotations

from dataclasses import dataclass
import hashlib

from fastapi import Request

from app.domain.rooms.ai_controller_tokens import TOKEN_PREFIX as AI_JOIN_TOKEN_PREFIX
from app.domain.rooms.ai_controllers import (
    AIControllerAuthView,
    AIControllerService,
    AIControllerUnauthorizedError,
)
from app.domain.rooms.ai_oauth import AIControllerOAuthService


OAUTH_ACCESS_TOKEN_PREFIX = "at_oa_"


class MCPAuthenticationError(PermissionError):
    def __init__(self, stable_code: str, message: str, message_zh_tw: str) -> None:
        super().__init__(message)
        self.stable_code = stable_code
        self.message = message
        self.message_zh_tw = message_zh_tw


@dataclass(frozen=True)
class MCPAuthenticatedRequest:
    token: str
    auth: AIControllerAuthView


def _unauthorized() -> MCPAuthenticationError:
    return MCPAuthenticationError(
        "ai_token_unauthorized",
        "AI authorization is invalid or no longer authorized",
        "AI 授權無效或已失去授權",
    )


def authenticate_request(
    request: Request,
    service: AIControllerService,
    oauth_repository: AIControllerOAuthService | None = None,
) -> MCPAuthenticatedRequest:
    authorization = request.headers.get("authorization")
    if authorization is None or not authorization.startswith("Bearer "):
        raise MCPAuthenticationError(
            "ai_token_required",
            "Adventure Table AI authorization is required",
            "需要 Adventure Table AI 授權",
        )
    token = authorization[7:].strip()
    if not token:
        raise MCPAuthenticationError(
            "ai_token_required",
            "Adventure Table AI authorization is required",
            "需要 Adventure Table AI 授權",
        )

    if token.startswith(AI_JOIN_TOKEN_PREFIX):
        try:
            auth = service.authenticate(token, touch=True)
        except AIControllerUnauthorizedError as exc:
            raise _unauthorized() from exc
        return MCPAuthenticatedRequest(token=token, auth=auth)

    if token.startswith(OAUTH_ACCESS_TOKEN_PREFIX):
        if oauth_repository is None:
            raise _unauthorized()
        resolved = oauth_repository.resolve_active_access(
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
            touch=True,
        )
        if resolved is None:
            raise _unauthorized()
        _, oauth_authorization = resolved
        try:
            auth = service.authenticate_grant(
                oauth_authorization.grant_id,
                touch=True,
            )
        except AIControllerUnauthorizedError as exc:
            oauth_repository.revoke_authorization(oauth_authorization.id)
            raise _unauthorized() from exc
        return MCPAuthenticatedRequest(token=token, auth=auth)

    # Preserve the P3-E bearer contract: once a non-empty Bearer value is present,
    # let the legacy authority parse/reject it. Unknown or malformed credentials are
    # unauthorized, not equivalent to a missing credential.
    try:
        auth = service.authenticate(token, touch=True)
    except AIControllerUnauthorizedError as exc:
        raise _unauthorized() from exc
    return MCPAuthenticatedRequest(token=token, auth=auth)


__all__ = [
    "MCPAuthenticatedRequest",
    "MCPAuthenticationError",
    "OAUTH_ACCESS_TOKEN_PREFIX",
    "authenticate_request",
]
