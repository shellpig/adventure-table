from __future__ import annotations

import ipaddress
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def create_admin_app(state: Any) -> FastAPI:
    """Create the defense-in-depth loopback-only management app."""
    app = FastAPI(title="M04-A loopback admin", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def loopback_only(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not _is_loopback(request):
            return Response(status_code=404)
        return await call_next(request)

    @app.post("/admin/revoke-all")
    async def revoke_all() -> JSONResponse:
        await state.revoke_all()
        return JSONResponse({"ok": True})

    @app.post("/admin/add-tool")
    async def add_tool() -> JSONResponse:
        await state.enable_late_tool()
        return JSONResponse({"ok": True, "tool": "late_tool"})

    return app
