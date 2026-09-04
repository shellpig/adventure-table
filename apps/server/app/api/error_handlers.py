from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.errors import APIError
from app.domain.character.validation import CharacterValidationError
from app.persistence.characters import (
    CharacterArchivedError,
    CharacterNotArchivedError,
    CharacterNotFoundError,
)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    params: dict[str, Any] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if params is not None:
        error["params"] = params
    return JSONResponse(status_code=status_code, content={"error": error})


def register_exception_handlers(app: FastAPI) -> None:
    """Register the shared API/domain exception contract on one FastAPI app."""

    @app.exception_handler(APIError)
    def handle_api_error(_request: Request, exc: APIError) -> JSONResponse:
        return _error_response(
            exc.status_code,
            exc.code,
            exc.message,
            params=exc.params,
        )

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


__all__ = ["register_exception_handlers"]
