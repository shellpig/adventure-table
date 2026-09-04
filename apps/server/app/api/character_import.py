from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError

from app.api.dependencies import get_character_import_service
from app.api.errors import APIError
from app.interop.character_import import (
    CharacterImportError,
    CharacterImportResult,
    CharacterImportService,
)
from app.interop.json_schema import CharacterExport


router = APIRouter(prefix="/api/characters", tags=["characters"])
MAX_CHARACTER_IMPORT_BYTES = 5 * 1024 * 1024


def _error_location(error: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(part) for part in error.get("loc", ()))


def map_validation_error(exc: ValidationError) -> str:
    errors = sorted(exc.errors(), key=_error_location)

    specials: list[tuple[tuple[str, ...], str]] = []
    for error in errors:
        loc = _error_location(error)
        if "schema_status" in loc:
            specials.append((loc, "unsupported_schema_status"))
        if "version_kind" in loc:
            specials.append((loc, "invalid_version_kind"))
    if specials:
        return min(specials, key=lambda item: item[0])[1]

    if any(not _error_location(error) for error in errors):
        return "invalid_envelope_shape"
    if any(
        (loc := _error_location(error)) and loc[0] == "envelope"
        for error in errors
    ):
        return "invalid_envelope_shape"
    return "invalid_payload_shape"


def _parse_document(raw_body: bytes) -> CharacterExport:
    if len(raw_body) > MAX_CHARACTER_IMPORT_BYTES:
        raise APIError(
            413,
            "payload_too_large",
            "character import exceeds the 5 MB limit",
            params={"max_bytes": MAX_CHARACTER_IMPORT_BYTES},
        )
    try:
        payload: Any = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise APIError(
            400,
            "invalid_envelope_shape",
            "request body is not valid JSON",
        ) from exc
    try:
        document = CharacterExport.model_validate(payload)
    except ValidationError as exc:
        raise APIError(400, map_validation_error(exc), str(exc)) from exc
    if not document.payload.character.name.strip():
        raise APIError(
            400,
            "invalid_payload_shape",
            "payload.character.name cannot be blank",
        )
    return document


@router.post("/import", response_model=CharacterImportResult)
async def import_character(
    request: Request,
    response: Response,
    dry_run: bool = False,
    service: CharacterImportService = Depends(get_character_import_service),
) -> CharacterImportResult:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type and content_type != "application/json":
        raise APIError(
            415,
            "invalid_envelope_shape",
            "character import accepts application/json only",
        )

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_CHARACTER_IMPORT_BYTES:
                raise APIError(
                    413,
                    "payload_too_large",
                    "character import exceeds the 5 MB limit",
                    params={"max_bytes": MAX_CHARACTER_IMPORT_BYTES},
                )
        except ValueError:
            pass

    document = _parse_document(await request.body())
    try:
        result = service.preview(document) if dry_run else service.commit(document)
    except CharacterImportError as exc:
        raise APIError(
            exc.status_code,
            exc.code,
            exc.message,
            params=exc.params,
        ) from exc
    response.status_code = 200 if dry_run else 201
    return result


__all__ = ["MAX_CHARACTER_IMPORT_BYTES", "map_validation_error", "router"]
