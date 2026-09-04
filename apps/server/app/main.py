from __future__ import annotations

from fastapi import FastAPI, HTTPException, status

from app.api import (
    character_builder_router,
    characters_router,
    content_presentation_router,
    reference_router,
)
from app.api.error_handlers import register_exception_handlers
from app.api.meta import create_meta_router
from app.config import settings
from app.content import load_default_content_registry
from app.db import database_is_ready

content_registry = load_default_content_registry()
app = FastAPI(title=settings.app_name)
app.state.content_registry = content_registry
app.state.distribution_channel = "web"
app.include_router(reference_router)
app.include_router(content_presentation_router)
app.include_router(characters_router)
app.include_router(character_builder_router)
app.include_router(create_meta_router("web"))
register_exception_handlers(app)


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
