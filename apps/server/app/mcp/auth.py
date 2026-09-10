from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.domain.rooms.ai_controllers import (
    AIControllerAuthView,
    AIControllerService,
    AIControllerUnauthorizedError,
)


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


def authenticate_request(
    request: Request,
    service: AIControllerService,
) -> MCPAuthenticatedRequest:
    authorization = request.headers.get("authorization")
    if authorization is None or not authorization.startswith("Bearer "):
        raise MCPAuthenticationError(
            "ai_token_required",
            "Adventure Table AI Join Token is required",
            "需要 Adventure Table AI Join Token",
        )
    token = authorization[7:].strip()
    if not token:
        raise MCPAuthenticationError(
            "ai_token_required",
            "Adventure Table AI Join Token is required",
            "需要 Adventure Table AI Join Token",
        )
    try:
        auth = service.authenticate(token, touch=True)
    except AIControllerUnauthorizedError as exc:
        raise MCPAuthenticationError(
            "ai_token_unauthorized",
            "AI Join Token is invalid or no longer authorized",
            "AI Join Token 無效或已失去授權",
        ) from exc
    return MCPAuthenticatedRequest(token=token, auth=auth)


__all__ = [
    "MCPAuthenticatedRequest",
    "MCPAuthenticationError",
    "authenticate_request",
]
