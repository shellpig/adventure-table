from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
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


def _validation_error_code(exc: ValidationError) -> str:
    errors = exc.errors()
    special: list[tuple[tuple[str, ...], str]] = []
    for error in errors:
        loc = tuple(str(part) for part in error.get("loc", ()))
        if "schema_status" in loc:
            special.append((loc, "unsupported_schema_status"))
        if "version_kind" in loc:
            special.append((loc, "invalid_version_kind"))
    if special:
        return sorted(special, key=lambda item: item[0])[0][1]

    # A valid JSON scalar/list is not an export envelope at all. Pydantic uses
    # an empty root location for that case, so keep it in the envelope bucket
    # rather than misreporting it as a payload-field failure.
    if any(not tuple(error.get("loc", ())) for error in errors):
        return "invalid_envelope_shape"
    for error in errors:
        loc = tuple(str(part) for part in error.get("loc", ()))
        if loc and loc[0] == "envelope":
            return "invalid_envelope_shape"
    return "invalid_payload_shape"


def _parse_document(raw_body: bytes) -> CharacterExport:
    if len(raw_body) > MAX_CHARACTER_IMPORT_BYTES:
        raise APIError(413, "payload_too_large", "character import exceeds the 5 MB limit")
    try:
        payload: Any = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise APIError(400, "invalid_envelope_shape", "request body is not valid JSON") from exc
    try:
        document = CharacterExport.model_validate(payload)
    except ValidationError as exc:
        raise APIError(400, _validation_error_code(exc), str(exc)) from exc
    if not document.payload.character.name.strip():
        raise APIError(400, "invalid_payload_shape", "payload.character.name cannot be blank")
    return document


@router.post("/import", response_model=CharacterImportResult)
async def import_character(
    request: Request,
    dry_run: bool = False,
    service: CharacterImportService = Depends(get_character_import_service),
) -> CharacterImportResult:
    document = _parse_document(await request.body())
    try:
        return service.preview(document) if dry_run else service.commit(document)
    except CharacterImportError as exc:
        raise APIError(exc.status_code, exc.code, exc.message) from exc


__all__ = ["MAX_CHARACTER_IMPORT_BYTES", "router"]
