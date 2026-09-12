from __future__ import annotations

from fastapi import Request

from app.config import settings


def public_origin(request: Request) -> str:
    """Origin advertised in OAuth metadata and the MCP bearer challenge.

    Behind a TLS-terminating proxy (e.g. Tailscale serve / funnel) the request
    only sees the loopback origin, so deployments set
    ADVENTURE_TABLE_MCP_PUBLIC_ORIGIN to the public https origin.
    """

    configured = settings.mcp_public_origin
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


__all__ = ["public_origin"]
