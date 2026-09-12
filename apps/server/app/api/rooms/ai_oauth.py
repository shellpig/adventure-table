from __future__ import annotations

from fastapi import Request

from app.api.dependencies import get_database_engine
from app.domain.rooms.ai_oauth import AIControllerOAuthService
from app.persistence.mcp.oauth import OAuthRepository


def get_ai_controller_oauth_service(request: Request) -> AIControllerOAuthService:
    service = getattr(request.app.state, "ai_controller_oauth_service", None)
    if service is None:
        service = AIControllerOAuthService(
            OAuthRepository(get_database_engine(request))
        )
        request.app.state.ai_controller_oauth_service = service
    return service


__all__ = ["get_ai_controller_oauth_service"]
