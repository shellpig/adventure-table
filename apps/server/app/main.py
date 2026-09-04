from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api import (
    character_builder_router,
    character_export_router,
    characters_router,
    content_presentation_router,
    reference_router,
)
from app.api.errors import APIError
from app.config import settings
from app.content import load_default_content_registry
from app.db import database_is_ready
from app.domain.character.validation import CharacterValidationError
from app.persistence.characters import (
    CharacterArchivedError,
    CharacterNotArchivedError,
    CharacterNotFoundError,
)

content_registry = load_default_content_registry()
app = FastAPI(title=settings.app_name)
app.state.content_registry = content_registry
app.state.distribution_channel = "web"
app.include_router(reference_router)
app.include_router(content_presentation_router)
app.include_router(characters_router)
app.include_router(character_export_router)
app.include_router(character_builder_router)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


@app.exception_handler(APIError)
def handle_api_error(_request: Request, exc: APIError) -> JSONResponse:
    return _error_response(exc.status_code, exc.code, exc.message)


@app.exception_handler(CharacterNotFoundError)
def handle_character_not_found(
    _request: Request, exc: CharacterNotFoundError
) -> JSONResponse:
    return _error_response(404, "character_not_found", f"character not found: {exc}")


@app.exception_handler(CharacterArchivedError)
def handle_character_archived(
    _request: Request, exc: CharacterArchivedError
) -> JSONResponse:
    return _error_response(
        409,
        "character_archived",
        f"archived characters are read-only: {exc}",
    )


@app.exception_handler(CharacterNotArchivedError)
def handle_character_not_archived(
    _request: Request, exc: CharacterNotArchivedError
) -> JSONResponse:
    return _error_response(
        409,
        "character_not_archived",
        f"archive the character before deleting it: {exc}",
    )


@app.exception_handler(CharacterValidationError)
def handle_character_validation(
    _request: Request, exc: CharacterValidationError
) -> JSONResponse:
    return _error_response(422, "validation_failed", str(exc))


@app.exception_handler(RequestValidationError)
def handle_request_validation(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _error_response(422, "validation_failed", str(exc))


@app.exception_handler(ValidationError)
def handle_pydantic_validation(
    _request: Request, exc: ValidationError
) -> JSONResponse:
    return _error_response(422, "validation_failed", str(exc))


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
