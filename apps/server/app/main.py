from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.api import content_presentation_router, reference_router
from app.api.error_handlers import register_exception_handlers
from app.api.meta import create_meta_router
from app.api.rooms import router as rooms_router
from app.config import settings
from app.content import load_default_content_registry
from app.db import database_is_ready
from app.mcp import router as mcp_router
from app.persistence.rooms.workspace import RoomWorkspaceAssociationConflictError

content_registry = load_default_content_registry()
app = FastAPI(title=settings.app_name)
app.state.content_registry = content_registry
app.state.distribution_channel = "web"
app.include_router(reference_router)
app.include_router(content_presentation_router)
app.include_router(rooms_router)
app.include_router(mcp_router)
app.include_router(create_meta_router("web"))
register_exception_handlers(app)


@app.exception_handler(RoomWorkspaceAssociationConflictError)
def handle_room_workspace_association_conflict(
    _request: Request,
    exc: RoomWorkspaceAssociationConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "room_workspace_conflict",
                "message": f"Room workspace changed concurrently: {exc}",
            }
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness() -> dict[str, str]:
    if not database_is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "database_unavailable"},
        )
    return {"status": "ready"}
