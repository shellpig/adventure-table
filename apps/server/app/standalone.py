from __future__ import annotations

from fastapi import FastAPI

from app.api import (
    character_builder_router,
    characters_router,
    content_presentation_router,
    reference_router,
)
from app.api.error_handlers import register_exception_handlers
from app.api.meta import create_meta_router
from app.api.spa import mount_spa
from app.config import settings
from app.content import load_default_content_registry
from app.paths import resolve_database_url, resolve_spa_root


def _require_sqlite() -> None:
    resolved_url = resolve_database_url()
    if not resolved_url.startswith("sqlite+pysqlite://"):
        raise RuntimeError(
            "Adventure Table standalone requires SQLite; "
            f"resolved database URL is {resolved_url!r}. "
            "Check ADVENTURE_TABLE_DATABASE_PATH."
        )


def create_standalone_app() -> FastAPI:
    _require_sqlite()
    app = FastAPI(
        title=f"{settings.app_name} (standalone)",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.content_registry = load_default_content_registry()
    app.state.distribution_channel = "standalone"

    app.include_router(reference_router)
    app.include_router(content_presentation_router)
    app.include_router(characters_router)
    app.include_router(character_builder_router)
    app.include_router(create_meta_router("standalone"))
    register_exception_handlers(app)
    mount_spa(app, resolve_spa_root())
    return app


app = create_standalone_app()

__all__ = ["app", "create_standalone_app"]
